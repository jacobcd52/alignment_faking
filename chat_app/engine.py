"""Tinker models, conversation <-> renderer message conversion, sampling, and the chat / agent run loop.

Conversations are stored in a renderer-neutral form (see README): user / assistant / tool messages with plain
text fields, so the same conversation can be re-rendered for any model or renderer. Assistant messages keep
their reasoning ("thinking"), tool calls (with ids) and unparsed tool calls; tool messages reference the call id.
"""

import asyncio
import json
import os
import time
import uuid

import httpx

import tools as T

DEFAULT_MODEL = "zai-org/GLM-5.3-Flash:peft:262144"
DEFAULT_RENDERER = "glm5_3_high_reasoning"
SIM_MODEL = "zai-org/GLM-5.3:peft:262144"
SIM_RENDERER = "glm5_3_low_reasoning"

ALL_RENDERERS = [
    "glm5_3_max_reasoning", "glm5_3_high_reasoning", "glm5_3_low_reasoning",
    "kimi_k26", "kimi_k26_disable_thinking", "kimi_k26_preserve_thinking",
    "kimi_k25", "kimi_k25_disable_thinking", "kimi_k2",
    "qwen3_8_xhigh_reasoning", "qwen3_8_medium_reasoning", "qwen3_8_low_reasoning", "qwen3_8_disable_thinking",
    "qwen3_5", "qwen3_5_disable_thinking",
    "qwen3", "qwen3_disable_thinking", "qwen3_instruct", "qwen3_vl", "qwen3_vl_instruct",
    "deepseekv3", "deepseekv3_thinking", "deepseekv3_disable_thinking",
    "gpt_oss_low_reasoning", "gpt_oss_medium_reasoning", "gpt_oss_high_reasoning", "gpt_oss_no_sysprompt",
    "nemotron3", "nemotron3_low_thinking", "nemotron3_disable_thinking", "nemotron3_preserve_thinking",
    "nemotron3_ultra", "nemotron3_ultra_medium_thinking", "nemotron3_ultra_disable_thinking",
    "nemotron3_ultra_preserve_thinking",
    "llama3", "role_colon", "tml_v0",
]
# Most specific first, so qwen3_5_* isn't counted as qwen3.
FAMILY_PREFIXES = ["glm5_3", "kimi_k26", "kimi_k25", "kimi_k2", "qwen3_8", "qwen3_5", "qwen3_vl", "qwen3",
                   "deepseekv3", "gpt_oss", "nemotron3_ultra", "nemotron3", "llama3", "role_colon", "tml_v0"]
PREFERRED_DEFAULT = {"glm5_3": "glm5_3_high_reasoning", "gpt_oss": "gpt_oss_medium_reasoning"}


def hf_name(model: str) -> str:
    return model.split(":", 1)[0]


def family_of(renderer: str) -> str | None:
    for p in FAMILY_PREFIXES:
        if renderer == p or renderer.startswith(p + "_"):
            return p
    return None


def renderer_info(model: str) -> dict:
    """Renderer options for a model. Falls back to shorter names (GLM-5.3-Flash -> GLM-5.3) when the cookbook
    doesn't know the exact model."""
    from tinker_cookbook.model_info import get_recommended_renderer_names

    hf = hf_name(model)
    rec = None
    org, _, ver = hf.partition("/")
    parts = ver.split("-")
    while parts and rec is None:
        try:
            rec = get_recommended_renderer_names(f"{org}/{'-'.join(parts)}")
        except Exception:
            parts.pop()
    rec = list(rec or [])
    fam = family_of(rec[0]) if rec else None
    options = rec + [r for r in ALL_RENDERERS if fam and family_of(r) == fam and r not in rec]
    default = PREFERRED_DEFAULT.get(fam, "") if fam else ""
    if default not in options:
        default = options[0] if options else ""
    return {"hf_name": hf, "renderers": options, "default_renderer": default, "renderer_known": bool(rec)}


def new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:10]


class Loaded:
    def __init__(self, key, hf, renderer, tokenizer, sampler):
        self.key, self.hf, self.renderer, self.tokenizer, self.sampler = key, hf, renderer, tokenizer, sampler


class Sample:
    def __init__(self, msg, termination, seq, prompt_tokens, opens_think):
        self.msg, self.termination, self.seq = msg, termination, seq
        self.prompt_tokens, self.opens_think = prompt_tokens, opens_think


class Engine:
    def __init__(self, sample_timeout: float = 900):
        self.sample_timeout = sample_timeout
        self._service = None
        self._rest = None
        self._tokenizers: dict[str, object] = {}
        self._renderers: dict[tuple, object] = {}
        self._samplers: dict[tuple, object] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._models: list[dict] | None = None
        self._models_at = 0.0

    async def service(self):
        if self._service is None:
            import tinker

            self._service = await asyncio.to_thread(tinker.ServiceClient)
        return self._service

    async def rest(self):
        if self._rest is None:
            svc = await self.service()
            self._rest = await asyncio.to_thread(svc.create_rest_client)
        return self._rest

    async def supported_models(self, refresh: bool = False) -> list[dict]:
        if self._models is not None and not refresh and time.time() - self._models_at < 600:
            return self._models
        svc = await self.service()
        caps = await asyncio.wait_for(svc.get_server_capabilities_async(), 60)
        models = []
        for m in caps.supported_models:
            if not getattr(m, "sampleable", True):
                continue
            models.append({"name": m.model_name, "max_context": getattr(m, "max_context_length", None),
                           **renderer_info(m.model_name)})
        self._models, self._models_at = models, time.time()
        return models

    async def list_checkpoints(self) -> list[dict]:
        rc = await self.rest()
        res = await asyncio.wait_for(rc.list_user_checkpoints_async(limit=200), 60)
        return [
            {"path": c.tinker_path, "id": c.checkpoint_id, "time": c.time.isoformat() if c.time else None}
            for c in res.checkpoints if c.checkpoint_type == "sampler"
        ]

    async def inspect_checkpoint(self, path: str) -> dict:
        rc = await self.rest()
        run = await asyncio.wait_for(rc.get_training_run_by_tinker_path_async(path), 60)
        base = run.base_model
        served = {hf_name(m["name"]) for m in (self._models or [])}
        return {"base_model": base, "lora_rank": getattr(run, "lora_rank", None),
                "served": (base in served) if served else None, **renderer_info(base)}

    async def get(self, model: str, model_path: str, renderer_name: str, phase=lambda s: None) -> Loaded:
        """Tokenizer + renderer + sampling client, cached. `model` is a Tinker base model name (or, for a
        checkpoint, its base model); `model_path` a tinker:// sampler checkpoint or ''."""
        if not renderer_name:
            raise ValueError("No renderer selected for this model. Pick one in Settings.")
        hf = hf_name(model)
        key = (model, model_path, renderer_name)
        async with self._locks.setdefault(key, asyncio.Lock()):
            if hf not in self._tokenizers:
                phase(f"Loading tokenizer for {hf} (first use downloads it from Hugging Face)")
                from tinker_cookbook.tokenizer_utils import get_tokenizer

                try:
                    self._tokenizers[hf] = await asyncio.to_thread(get_tokenizer, hf)
                except Exception as e:
                    raise RuntimeError(f"Could not load the tokenizer for {hf}: {e}") from e
            tok = self._tokenizers[hf]
            rkey = (renderer_name, hf)
            if rkey not in self._renderers:
                from tinker_cookbook import renderers

                self._renderers[rkey] = renderers.get_renderer(renderer_name, tok, model_name=hf)
            skey = (None, model_path) if model_path else (model, None)
            if skey not in self._samplers:
                phase("Connecting to Tinker")
                svc = await self.service()
                if model_path:
                    self._samplers[skey] = await svc.create_sampling_client_async(model_path=model_path)
                else:
                    self._samplers[skey] = await svc.create_sampling_client_async(base_model=model)
            return Loaded(key, hf, self._renderers[rkey], tok, self._samplers[skey])

    def max_context(self, model: str) -> int | None:
        for m in self._models or []:
            if m["name"] == model:
                return m.get("max_context")
        return None

    async def sample(self, loaded: Loaded, messages: list, max_tokens: int, temperature: float,
                     context_limit: int | None = None):
        import tinker

        prompt = loaded.renderer.build_generation_prompt(messages)
        if context_limit:
            room = context_limit - prompt.length
            if room < 64:
                raise ValueError(
                    f"The conversation ({prompt.length:,} tokens) no longer fits this model's {context_limit:,}-token "
                    "context. Rewind or fork from an earlier message, or switch to a longer-context model."
                )
            max_tokens = min(int(max_tokens), room)
        params = tinker.SamplingParams(
            max_tokens=int(max_tokens), temperature=float(temperature), stop=loaded.renderer.get_stop_sequences()
        )

        async def once():
            return await loaded.sampler.sample_async(prompt=prompt, num_samples=1, sampling_params=params)

        transient = (tinker.APIConnectionError, tinker.RateLimitError, tinker.InternalServerError)
        for attempt in range(3):
            try:
                res = await asyncio.wait_for(once(), self.sample_timeout)
                break
            except asyncio.TimeoutError:
                raise TimeoutError(f"Tinker did not return a sample within {self.sample_timeout:.0f}s.")
            except transient:
                if attempt == 2:
                    raise
                await asyncio.sleep(3 * 2**attempt)
        seq = res.sequences[0]
        msg, termination = loaded.renderer.parse_response(seq.tokens)
        # Renderers like GLM-5.3 put the opening <think> in the prompt; a reply cut off mid-reasoning then comes
        # back as plain text with no tags at all.
        tail = prompt.to_ints()[-8:]
        opens_think = loaded.tokenizer.decode(tail).rstrip().endswith("<think>")
        return Sample(msg, termination, seq, prompt.length, opens_think)

    async def render_prompt(self, conv: dict) -> dict:
        s = conv["settings"]
        loaded = await self.get(s["model"], model_path(s), s["renderer"])
        prompt = loaded.renderer.build_generation_prompt(to_renderer_messages(conv, loaded.renderer))
        tokens = prompt.to_ints()
        return {"text": loaded.tokenizer.decode(tokens), "tokens": len(tokens), "model": s["model"],
                "renderer": s["renderer"]}


def model_path(s: dict) -> str:
    return (s.get("model_path") or "").strip() if s.get("use_checkpoint") else ""


# ---------------------------------------------------------------------------------------------
# Conversion between stored messages and renderer messages
# ---------------------------------------------------------------------------------------------
def enabled_tool_specs(s: dict) -> list[dict]:
    names = s.get("tools") or []
    return [T.TOOL_SPECS[n] for n in T.TOOL_NAMES if n in names]


def to_renderer_messages(conv: dict, renderer) -> list:
    from tinker_cookbook.renderers import ToolCall

    s = conv["settings"]
    system = s.get("system") or ""
    specs = enabled_tool_specs(s) if s.get("agent") else []
    if specs:
        try:
            out = list(renderer.create_conversation_prefix_with_tools(specs, system))
        except NotImplementedError:
            raise RuntimeError(f"Renderer {s.get('renderer')} does not support tool declarations; turn off agent mode.")
    else:
        out = [{"role": "system", "content": system}] if system.strip() else []
    for m in conv["messages"]:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m.get("text", "")})
        elif role == "assistant":
            text = m.get("text") or ""
            raw = "".join(u.get("raw_text", "") for u in m.get("unparsed_tool_calls") or [])
            if raw:  # keep what the model actually wrote
                text = f"{text}\n{raw}" if text else raw
            parts = []
            if m.get("thinking"):
                parts.append({"type": "thinking", "thinking": m["thinking"]})
            if text:
                parts.append({"type": "text", "text": text})
            msg = {"role": "assistant", "content": parts}
            calls = [
                ToolCall(id=c["id"], function=ToolCall.FunctionBody(
                    name=c["name"], arguments=c.get("raw_arguments") or json.dumps(c.get("arguments") or {})))
                for c in m.get("tool_calls") or []
            ]
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        elif role == "tool":
            out.append({"role": "tool", "content": m.get("text", ""), "tool_call_id": m.get("tool_call_id", ""),
                        "name": m.get("name", "")})
    return out


def split_content(msg) -> tuple[str, str]:
    content = msg.get("content", "")
    if isinstance(content, str):
        return "", content
    thinking = "".join(p.get("thinking", "") for p in content if p.get("type") == "thinking")
    text = "".join(p.get("text", "") for p in content if p.get("type") == "text")
    return thinking, text


def unwrap_think(thinking: str, text: str, sample: "Sample") -> tuple[str, str, bool]:
    """Recover reasoning from a reply that hit max tokens before closing it. GLM returns either a raw
    '<think>...' with no close tag, or (when the prompt itself opened <think>) plain untagged text."""
    if thinking:
        return thinking, text, False
    stripped = text.lstrip()
    if stripped.startswith("<think>"):
        body, sep, rest = stripped[len("<think>"):].partition("</think>")
        return body.strip(), rest.strip(), not sep
    if sample.opens_think and getattr(sample.seq, "stop_reason", None) == "length" and "</think>" not in text:
        return text.strip(), "", True
    return thinking, text, False


def from_sample(sample: "Sample", meta: dict) -> dict:
    msg, termination, seq = sample.msg, sample.termination, sample.seq
    thinking, text = split_content(msg)
    thinking, text, think_cut = unwrap_think(thinking, text, sample)
    calls = []
    for c in msg.get("tool_calls") or []:
        raw = c.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = None
        calls.append({"id": c.id or new_id("call_"), "name": c.function.name, "arguments": args, "raw_arguments": raw})
    unparsed = [{"raw_text": u.raw_text, "error": u.error} for u in msg.get("unparsed_tool_calls") or []]
    stop_reason = getattr(seq, "stop_reason", None)
    return {
        "id": new_id("m_"), "role": "assistant", "thinking": thinking.strip(), "text": text.strip(),
        "tool_calls": calls, "unparsed_tool_calls": unparsed,
        "truncated": stop_reason == "length" or think_cut,
        "meta": {**meta, "termination": str(termination), "stop_reason": stop_reason,
                 "completion_tokens": len(seq.tokens)},
    }


def pending_tool_calls(messages: list[dict]) -> list[dict]:
    """Tool calls of the latest assistant message that have no result yet."""
    for i in range(len(messages) - 1, -1, -1):
        role = messages[i]["role"]
        if role == "assistant":
            answered = {m.get("tool_call_id") for m in messages[i + 1:] if m["role"] == "tool"}
            return [c for c in messages[i].get("tool_calls") or [] if c["id"] not in answered]
        if role == "user":
            return []
    return []


def tool_history(messages: list[dict]) -> list[dict]:
    calls, hist = {}, []
    for m in messages:
        if m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                calls[c["id"]] = c
        elif m["role"] == "tool" and m.get("tool_call_id") in calls:
            c = calls[m["tool_call_id"]]
            args = c["arguments"] if c.get("arguments") is not None else c.get("raw_arguments")
            hist.append({"name": c["name"], "arguments": args, "output": m.get("text", "")})
    return hist


# ---------------------------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------------------------
class RunContext:
    """What the run loop needs from the server: the engine, docker, a save callback and a phase reporter."""

    def __init__(self, engine: Engine, docker: T.Docker, save, run):
        self.engine, self.docker, self.save, self.run = engine, docker, save, run

    def phase(self, text: str):
        self.run.phase, self.run.phase_since = text, time.time()


async def openai_text(model: str, system: str, user: str, max_tokens: int = 8000) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise T.ToolError("OPENAI_API_KEY is not set in the server's environment.")
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "instructions": system, "input": user, "reasoning": {"effort": "low"},
                  "max_output_tokens": max_tokens},
        )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        detail = (data.get("error") or {}).get("message") or r.text[:500]
        raise T.ToolError(f"OpenAI simulator ({model}) failed: HTTP {r.status_code}: {detail}")
    texts = [
        part.get("text", "")
        for item in data.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text"
    ]
    return "".join(texts)


async def simulator_text(ctx: RunContext, s: dict, system: str, user: str) -> str:
    if s.get("sim_provider") == "openai":
        return await openai_text(s.get("openai_model") or "gpt-6.1-sol", system, user)
    loaded = await ctx.engine.get(s.get("sim_model") or SIM_MODEL, "", s.get("sim_renderer") or SIM_RENDERER, ctx.phase)
    sample = await ctx.engine.sample(
        loaded, [{"role": "system", "content": system}, {"role": "user", "content": user}], 6000, 0.7
    )
    thinking, text = split_content(sample.msg)
    thinking, text, cut = unwrap_think(thinking, text, sample)
    return "<think>" if cut else text  # simulate_tool resamples on this marker


def simulator_label(s: dict) -> str:
    if s.get("sim_provider") == "openai":
        return f"simulated by {s.get('openai_model') or 'gpt-6.1-sol'}"
    return f"simulated by {hf_name(s.get('sim_model') or SIM_MODEL)}"


async def execute_tool(conv: dict, call: dict, ctx: RunContext) -> tuple[str, str]:
    """Returns (output, how). `how` says where the output came from (shown in the UI)."""
    s = conv["settings"]
    name, args = call["name"], call.get("arguments")
    if name not in T.TOOL_SPECS or name not in (s.get("tools") or []):
        return f"Error: unknown tool '{name}'.", "error"
    if not isinstance(args, dict):
        return f"Error: tool arguments are not a valid JSON object: {call.get('raw_arguments')}", "error"
    missing = [k for k in T.TOOL_SPECS[name]["parameters"]["required"] if k not in args]
    if missing:
        return f"Error: missing required argument(s): {', '.join(missing)}", "error"
    backend = s.get("backend") or "simulated"
    fetch_mode = s.get("fetch_mode") or "auto"
    if name == "fetch_url" and (fetch_mode == "real" or (fetch_mode == "auto" and backend == "docker")):
        ctx.phase(f"Fetching {args['url']}")
        return await T.fetch_url(str(args["url"])), "real HTTP GET"
    if backend == "docker" and name in ("bash", "read_file", "write_file"):
        st = await ctx.docker.status()
        if not st["available"]:
            raise T.ToolError(f"Docker backend selected but Docker is not available: {st['reason']}")
        sandbox = conv.setdefault("sandbox", {})
        if name == "bash":
            out = await ctx.docker.bash(conv["id"], s, sandbox, str(args["command"]), ctx.phase)
        elif name == "read_file":
            out = await ctx.docker.read_file(conv["id"], s, sandbox, str(args["path"]), args.get("offset"),
                                             args.get("limit"), ctx.phase)
        else:
            out = await ctx.docker.write_file(conv["id"], s, sandbox, str(args["path"]), str(args["content"]), ctx.phase)
        return out, "docker"
    if name == "write_file":
        # Deterministic acknowledgement; the content stays in the history, so later simulated reads agree with it.
        return f"Wrote {len(str(args['content']).encode())} bytes to {args['path']}", "simulated (write acknowledged)"
    ctx.phase(f"Simulating {name}")
    out = await T.simulate_tool(
        lambda system, user: simulator_text(ctx, s, system, user),
        s.get("world") or "", tool_history(conv["messages"]), {"name": name, "arguments": args},
    )
    return out, simulator_label(s)


INTERRUPTED = "[Request interrupted by user: the tool was not run.]"


def close_pending(conv: dict, text: str = INTERRUPTED) -> None:
    """Give unanswered tool calls a result so the next prompt is well-formed."""
    for call in pending_tool_calls(conv["messages"]):
        conv["messages"].append({"id": new_id("m_"), "role": "tool", "tool_call_id": call["id"], "name": call["name"],
                                 "text": text, "meta": {"how": "not run"}})


async def run_conversation(conv: dict, ctx: RunContext) -> None:
    """Sample replies (and, in agent mode, execute tool calls) until the model answers without tool calls,
    the step cap is hit, or the task is cancelled. Every message is saved as soon as it exists."""
    s = conv["settings"]
    calls_made = 0
    while True:
        msgs = conv["messages"]
        pending = pending_tool_calls(msgs)
        if pending:
            if not s.get("agent"):
                conv["notice"] = "The last reply has tool calls, but agent mode is off, so they were not run."
                return
            for call in pending:
                ctx.phase(f"Running {call['name']}")
                t0 = time.time()
                out, how = await execute_tool(conv, call, ctx)
                msgs.append({"id": new_id("m_"), "role": "tool", "tool_call_id": call["id"], "name": call["name"],
                             "text": out, "meta": {"how": how, "seconds": round(time.time() - t0, 1)}})
                ctx.save()
        if not msgs or (msgs[-1]["role"] == "assistant" and not pending_tool_calls(msgs)):
            return  # nothing to respond to
        if calls_made >= int(s.get("max_steps") or 30):
            conv["notice"] = f"Stopped after {calls_made} model calls (step cap). Press Continue to keep going."
            return
        loaded = await ctx.engine.get(s["model"], model_path(s), s["renderer"], ctx.phase)
        prompt_msgs = to_renderer_messages(conv, loaded.renderer)
        ctx.run.step = calls_made + 1
        label = model_path(s) or hf_name(s["model"])
        ctx.phase(f"Waiting for {label.rsplit('/', 1)[-1]}")
        t0 = time.time()
        limit = None if model_path(s) else ctx.engine.max_context(s["model"])
        sample = await ctx.engine.sample(loaded, prompt_msgs, s.get("max_tokens") or 16000, s.get("temperature", 1.0), limit)
        reply = from_sample(sample, {
            "model": s["model"], "model_path": model_path(s), "renderer": s["renderer"],
            "temperature": s.get("temperature", 1.0), "max_tokens": s.get("max_tokens"),
            "prompt_tokens": sample.prompt_tokens, "seconds": round(time.time() - t0, 1),
        })
        msgs.append(reply)
        calls_made += 1
        ctx.save()
        if not s.get("agent") or not reply["tool_calls"]:
            if s.get("agent") and reply["unparsed_tool_calls"]:
                conv["notice"] = "The model emitted a tool call that could not be parsed. Regenerate, or edit and continue."
            return
