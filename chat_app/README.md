# Tinker Chat

A small local web app for talking to Tinker-hosted models (base models or your fine-tuned checkpoints), either as a
plain chat or as a Claude-Code-style agent with tools. Every message has rollback controls, and conversations are
saved as JSON files.

## Setup

Python 3.11+ in a virtualenv:

```bash
python -m venv .venv && source .venv/bin/activate
# Linux: install the CPU build of torch first (no GPU is needed; the renderers just import it)
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r chat_app/requirements.txt
# tinker-cookbook pins a package that is not on PyPI, so install it without its dependencies
pip install --no-deps tinker-cookbook
```

On macOS the default `pip install torch` wheel is fine. Then set your keys:

```bash
export TINKER_API_KEY=...        # required
export OPENAI_API_KEY=...        # optional: lets an OpenAI model act as the environment simulator
```

Docker is optional. If `docker` is on your PATH and its daemon is running, the Docker tool backend is enabled.
Otherwise it is greyed out in the UI.

## Run

```bash
python chat_app/server.py                 # http://127.0.0.1:8765
python chat_app/server.py --port 9000 --open
```

Other flags: `--host` (default `127.0.0.1`; don't expose this on a network), `--conversations-dir`, and
`--sample-timeout` (seconds to wait for one Tinker sample, default 900). The first message to a model downloads its
tokenizer from Hugging Face. At startup the server warms up the default model in the background.

## Using it

- **Settings** (right panel, per conversation): model (the live list from Tinker), renderer (thinking/reasoning
  variant; recommended ones listed first), temperature, max tokens, system prompt, agent mode. New conversations
  start from the settings you last changed.
- **Fine-tuned checkpoints**: tick *Use a fine-tuned checkpoint* and paste a `tinker://.../sampler_weights/...` path.
  Your recent sampler checkpoints are offered as suggestions. The base model is detected from the path and sets the
  tokenizer and renderer family; you can also pick it by hand. You get a warning if Tinker no longer serves sampling
  for that base model.
- **Messages** show the model's reasoning (collapsed; marked *truncated* if the reply hit max tokens mid-reasoning),
  markdown and code blocks, tool calls, and tool outputs (long ones collapsed). The meta line shows model, renderer,
  temperature, prompt/completion tokens and latency, so mixed-model conversations stay legible.
- **Raw prompt** shows the exact decoded tokens the model will see for its next reply, including tool declarations.
- **Export** downloads the conversation JSON. In the sidebar you can duplicate, export or delete conversations.

### Rollback controls

Hover a message to see its controls:

| Control | What it does |
|---|---|
| rewind before | delete this message and everything after it |
| rewind after | delete everything after this message |
| edit | edit the text in place (user, assistant reply/reasoning, or tool output). For user messages, *Save & resend* drops everything after the message and generates a new reply |
| regenerate (assistant) | resample this reply; in agent mode the tool loop continues from there |
| resend (user) | drop everything after this message and generate |
| re-run (tool) | drop this result and run the same tool call again |
| fork | new conversation containing everything up to and including this message |

**Undo** (top bar) restores the messages from before the last rewind, edit or regenerate (up to 10 steps).
**Continue** generates from the current state: it runs any pending tool calls, then asks the model. After an error,
the same button reads **Retry**. Errors never discard the conversation; every message is saved as soon as it exists.

## Agent mode

Turn on *Agent mode*. The model gets these tools, declared through its renderer's native tool format: `bash`,
`read_file`, `write_file`, `web_search` and `fetch_url`. You can switch each one on or off. The server loops: sample →
run tool calls → append results → sample again, until the model replies without tool calls or *Max model calls per
turn* (default 30) is reached. Steps appear in the UI as they finish. **Stop** cancels immediately; tool calls that
never ran get a "[Request interrupted by user]" result if you then send a new message.

Tool execution backends (per conversation):

- **Simulated** (default; works everywhere). An LLM plays the machine (adapted from `welfare_evals/common.py`:
  same rules, leak retry and fence stripping). It follows the hidden **world description** you edit in Settings,
  plus the session's tool history. `write_file` is acknowledged deterministically, and its content stays in the
  history, so later reads agree with it. Because the simulated world *is* the history, rolling back the chat also
  rolls back the world. The default simulator is `zai-org/GLM-5.3:peft:262144` with `glm5_3_low_reasoning`. You can
  pick any Tinker model, or an OpenAI model through the Responses API with low reasoning effort (e.g. `gpt-6.1-sol`;
  needs `OPENAI_API_KEY`).
- **Docker** (real execution). Each conversation gets its own long-lived container (`tinkerchat-<id>`, default image
  `python:3.12-slim`, git installed on first use). Each `bash` call is one `docker exec` with a timeout (default
  120s). The working directory persists between calls; environment variables do not. The network is on by default
  and can be turned off. **Rewinding the chat does not undo changes inside the container.** *Reset container* gives
  you a fresh one, and deleting the conversation removes its container.

`fetch_url` can be a real HTTP GET from the server (HTML converted to text, truncated). In *auto* mode it is real with
Docker and simulated with the simulator, so it stays consistent with the simulated world. Real fetches refuse
localhost and private-network addresses. `web_search` is always simulated.

## Where things are saved

`chat_app/conversations/<id>.json` (gitignored), one file per conversation. `.last_settings.json` holds the defaults
for new chats. Messages are stored renderer-neutrally (`role`, `text`, `thinking`, `tool_calls` with ids, `tool_call_id`
on tool results, plus `meta`), so any conversation can be re-rendered for another model or renderer.

## Safety

- Model-issued commands never run on your machine directly. They run either in the simulator (nothing executes) or
  inside the conversation's Docker container, via `docker exec` with an argument list (no host shell). A container is
  not a strong security boundary, and with the network on the model can reach the internet from it. Treat Docker mode
  as "the model has a Linux box with internet", and turn the network off if you don't want that. The container has no
  host mounts, a 4 GB memory limit and a process limit.
- The real `fetch_url` runs from the server process, but it only allows http(s) and refuses loopback/private
  addresses.
- The server listens on 127.0.0.1 only and rejects requests with foreign `Host`/`Origin` headers. Anyone who can reach
  it can spend your Tinker credits and use the Docker sandbox.

## Limitations

- No token streaming (Tinker sampling isn't streamed): a spinner shows the current phase and elapsed time.
- **Stop** kills the `docker exec` client, but a long command already running inside the container keeps going until
  its timeout.
- Images can't be sent. Text only.
