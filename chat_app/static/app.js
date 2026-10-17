"use strict";
// Tinker Chat front end: no build step, no dependencies. Talks to the JSON API in server.py.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

const state = {
  status: null,
  models: [],            // [{name, max_context, hf_name, renderers, default_renderer}]
  rendererInfo: {},      // model name -> {renderers, default_renderer}
  allRenderers: [],
  convs: [],
  conv: null,
  editing: null,         // message id being edited
  raw: new Set(),        // message ids shown raw
  open: new Map(),       // <details> key -> open?
  pollTimer: null,
  tick: null,
  saveTimer: null,
  pendingSettings: {},
  runReceivedAt: 0,
  checkpointsLoaded: false,
};

// ------------------------------------------------------------------ utilities
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {
    throw new Error("The chat server is not reachable (" + e.message + ").");
  }
  let data = null;
  try { data = await r.json(); } catch { /* not json */ }
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${r.status}`);
  }
  return data;
}
let toastTimer = null;
function toast(msg, kind = "error") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = kind;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), kind === "error" ? 7000 : 2500);
}
async function guarded(fn) {
  try { return await fn(); } catch (e) { toast(e.message); }
}
function pref(key, val) {
  try {
    if (val === undefined) return localStorage.getItem("tinkerchat." + key);
    localStorage.setItem("tinkerchat." + key, val);
  } catch { return null; }
}
function shortModel(name) { return (name || "").split("/").pop().replace(/:peft:\d+/, ""); }
function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return new Date(ts * 1000).toLocaleDateString();
}
function fmtTok(n) { return n == null ? "?" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n); }
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast("Copied", "info");
}

// ------------------------------------------------------------------ markdown (small, escapes everything)
function inline(s) {
  const codes = [];
  s = String(s).replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s);
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (_, p, u) => `${p}<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>");
  s = s.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
}
function codeBlock(code, lang) {
  return `<div class="code"><div class="code-head"><span>${esc(lang || "")}</span><button type="button" data-copy-code>copy</button></div><pre><code>${esc(code)}</code></pre></div>`;
}
const LIST_RE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const HR_RE = /^\s*([-*_])(\s*\1){2,}\s*$/;
const TABLE_SEP_RE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
function isBlockStart(l) {
  return /^\s*(`{3,}|~{3,})/.test(l) || /^#{1,6}\s/.test(l) || /^\s*>/.test(l) || LIST_RE.test(l) || HR_RE.test(l);
}
function md(src) {
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0, m;
  while (i < lines.length) {
    const line = lines[i];
    if ((m = line.match(/^\s*(`{3,}|~{3,})\s*([^\s`]*)/))) {
      const fence = m[1], buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence)) buf.push(lines[i++]);
      i++;
      out.push(codeBlock(buf.join("\n"), m[2]));
      continue;
    }
    if (!line.trim()) { i++; continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
      i++;
      continue;
    }
    if (HR_RE.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^\s*>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${md(buf.join("\n"))}</blockquote>`);
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1])) {
      const row = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      const head = row(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(row(lines[i++]));
      out.push(`<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if ((m = line.match(LIST_RE))) {
      const ordered = /\d/.test(m[2]);
      const start = ordered ? parseInt(m[2], 10) : 1;
      const items = [];
      while (i < lines.length) {
        const l = lines[i], mm = l.match(LIST_RE);
        if (mm) { items.push({ indent: mm[1].replace(/\t/g, "  ").length, text: mm[3] }); i++; }
        else if (l.trim() && /^\s{2,}/.test(l) && items.length && !/^\s*(`{3,}|~{3,})/.test(l)) { items[items.length - 1].text += "\n" + l.trim(); i++; }
        else break;
      }
      const tag = ordered ? "ol" : "ul";
      const st = ordered && start !== 1 ? ` start="${start}"` : "";
      out.push(`<${tag}${st}>${items.map((it) => `<li style="margin-left:${Math.min(it.indent, 12) * 0.6}em">${it.text.split("\n").map(inline).join("<br>")}</li>`).join("")}</${tag}>`);
      continue;
    }
    const buf = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i]) && !(lines[i].includes("|") && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1]))) buf.push(lines[i++]);
    out.push(`<p>${buf.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}

// ------------------------------------------------------------------ details state (survives re-renders)
function details(key, summary, body, defaultOpen, cls = "") {
  const open = state.open.has(key) ? state.open.get(key) : defaultOpen;
  return `<details class="${cls}" data-key="${esc(key)}"${open ? " open" : ""}><summary>${summary}</summary>${body}</details>`;
}
document.addEventListener("toggle", (e) => {
  const el = e.target;
  if (el.tagName === "DETAILS" && el.dataset.key) state.open.set(el.dataset.key, el.open);
}, true);

// ------------------------------------------------------------------ sidebar
async function loadSidebar() {
  const r = await api("GET", "/api/conversations");
  state.convs = r.conversations;
  renderSidebar();
}
function renderSidebar() {
  const box = $("#conv-list");
  box.innerHTML = state.convs.map((c) => `
    <div class="conv-item${state.conv && c.id === state.conv.id ? " active" : ""}" data-id="${esc(c.id)}">
      <div class="conv-title">${c.running ? '<span class="dot"></span>' : ""}${esc(c.title)}</div>
      <div class="conv-sub">${esc(shortModel(c.model))}${c.agent ? " · agent" : ""} · ${c.messages} msgs · ${ago(c.updated)}</div>
      <div class="conv-actions">
        <button data-side="dup" title="Copy this conversation">duplicate</button>
        <a href="/api/conversations/${encodeURIComponent(c.id)}/export" download title="Download as JSON">export</a>
        <button data-side="del" title="Delete this conversation (and its Docker container)">delete</button>
      </div>
    </div>`).join("") || '<div class="hint" style="padding:8px">No conversations yet.</div>';
  const anyRunning = state.convs.some((c) => c.running);
  clearTimeout(state.sideTimer);
  if (anyRunning) state.sideTimer = setTimeout(() => guarded(loadSidebar), 4000);
}
$("#conv-list").addEventListener("click", (e) => {
  const item = e.target.closest(".conv-item");
  if (!item) return;
  const id = item.dataset.id;
  const act = e.target.closest("[data-side]")?.dataset.side;
  if (e.target.closest("a")) return;
  if (act === "dup") return guarded(async () => { const c = await api("POST", `/api/conversations/${id}/duplicate`, {}); await openConv(c.id, c); await loadSidebar(); });
  if (act === "del") {
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    return guarded(async () => {
      await api("DELETE", `/api/conversations/${id}`);
      if (state.conv && state.conv.id === id) {
        state.conv = null;
        await loadSidebar();
        if (state.convs.length) await openConv(state.convs[0].id); else await newChat();
      } else await loadSidebar();
    });
  }
  guarded(() => openConv(id));
});
async function newChat() {
  const c = await api("POST", "/api/conversations", {});
  await openConv(c.id, c);
  await loadSidebar();
  $("#input").focus();
}
$("#new-chat").addEventListener("click", () => guarded(newChat));

// ------------------------------------------------------------------ conversation
async function openConv(id, data) {
  await flushSettings();
  const c = data || (await api("GET", `/api/conversations/${id}`));
  state.editing = null;
  state.scrollToBottom = true;
  history.replaceState(null, "", "#/c/" + c.id);
  setConv(c, true);
  renderSidebar();
}
function setConv(c, fillForm = false) {
  const switched = !state.conv || state.conv.id !== c.id;
  state.conv = c;
  state.runReceivedAt = Date.now();
  if (switched || fillForm) fillSettings();
  render();
  schedulePoll();
}
async function reloadConv() {
  if (!state.conv) return;
  setConv(await api("GET", `/api/conversations/${state.conv.id}`));
}
function schedulePoll() {
  clearTimeout(state.pollTimer);
  if (state.conv && state.conv.run) state.pollTimer = setTimeout(poll, 1000);
}
async function poll() {
  const c = state.conv;
  if (!c) return;
  try {
    const r = await api("GET", `/api/conversations/${c.id}?v=${c.version}`);
    if (!state.conv || state.conv.id !== c.id) return;
    if (r.unchanged) {
      state.conv.run = r.run;
      state.runReceivedAt = Date.now();
      renderRun();
      if (!r.run) { await reloadConv(); await loadSidebar(); return; }
    } else {
      const wasRunning = !!state.conv.run;
      setConv(r);
      if (wasRunning && !r.run) await loadSidebar();
      return;
    }
  } catch (e) { /* server restarting: keep trying */ }
  schedulePoll();
}

function pendingIds(msgs) {
  const answered = new Set(msgs.filter((m) => m.role === "tool").map((m) => m.tool_call_id));
  const ids = new Set();
  for (const m of msgs) if (m.role === "assistant") for (const c of m.tool_calls || []) if (!answered.has(c.id)) ids.add(c.id);
  return ids;
}
function canContinue(c) {
  const msgs = c.messages;
  if (!msgs.length) return false;
  const last = msgs[msgs.length - 1];
  if (last.role === "user" || last.role === "tool") return true;
  if (last.role === "assistant") {
    const p = pendingIds([last]);
    return p.size > 0 && c.settings.agent;
  }
  return false;
}

function render() {
  const c = state.conv;
  if (!c) return;
  document.title = (c.title || "Untitled") + " · Tinker Chat";
  if (document.activeElement !== $("#title")) $("#title").value = c.title || "";
  const s = c.settings;
  $("#model-badge").textContent = (s.use_checkpoint && s.model_path ? "ckpt " + s.model_path.split("/").pop() + " on " : "") + shortModel(s.model) + " · " + s.renderer;
  $("#model-badge").title = (s.use_checkpoint && s.model_path ? s.model_path + "\n" : "") + s.model + "\n" + s.renderer;
  $("#btn-export").href = `/api/conversations/${encodeURIComponent(c.id)}/export`;
  $("#btn-export").setAttribute("download", c.id + ".json");
  $("#btn-undo").hidden = !c.undo_depth || !!c.run;
  renderInfo();
  renderMessages();
  renderRun();
  renderNoticeAndError();
  renderComposer();
}
function renderInfo() {
  const s = state.conv.settings, bits = [];
  if (s.system && s.system.trim()) bits.push(`<span class="pill" data-open-settings title="${esc(s.system)}">System: ${esc(s.system.slice(0, 90))}${s.system.length > 90 ? "…" : ""}</span>`);
  if (s.agent) bits.push(`<span class="pill" data-open-settings>Agent mode · ${esc(s.backend)} · ${esc((s.tools || []).join(", ") || "no tools")}</span>`);
  $("#conv-info").innerHTML = bits.join("");
}
$("#conv-info").addEventListener("click", (e) => { if (e.target.closest("[data-open-settings]")) setSettingsOpen(true); });

function renderMessages() {
  const c = state.conv, box = $("#messages"), sc = $("#scroller");
  const nearBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 120;
  const calls = {};
  for (const m of c.messages) if (m.role === "assistant") for (const tc of m.tool_calls || []) calls[tc.id] = tc;
  const pending = pendingIds(c.messages);
  box.classList.toggle("running", !!c.run);
  box.innerHTML = c.messages.map((m) => renderMessage(m, calls, pending)).join("");
  $("#empty").hidden = c.messages.length > 0 || !!c.run;
  if (nearBottom || state.scrollToBottom) {
    sc.scrollTop = sc.scrollHeight;
    state.scrollToBottom = false;
  }
}

const ACTIONS = {
  user: [["edit", "Edit (then save, or save & resend)"], ["resend", "Drop everything after this message and generate a new reply"], ["before", "Rewind to before: delete this message and everything after it"], ["after", "Rewind to after: delete everything after this message"], ["fork", "Fork: new conversation up to and including this message"], ["copy", "Copy text"]],
  assistant: [["regenerate", "Regenerate: resample this reply (deletes it and everything after)"], ["edit", "Edit this reply in place"], ["before", "Rewind to before: delete this message and everything after it"], ["after", "Rewind to after: delete everything after this message"], ["fork", "Fork: new conversation up to and including this message"], ["copy", "Copy text"], ["raw", "Toggle raw text / rendered markdown"]],
  tool: [["edit", "Edit this tool output in place"], ["rerun", "Run this tool call again (deletes this result and everything after)"], ["before", "Rewind to before: delete this result and everything after it"], ["after", "Rewind to after: delete everything after this message"], ["fork", "Fork: new conversation up to and including this message"], ["copy", "Copy output"]],
};
const LABELS = { edit: "edit", resend: "resend", regenerate: "regenerate", rerun: "re-run", before: "rewind before", after: "rewind after", fork: "fork", copy: "copy", raw: "raw" };

function renderMessage(m, calls, pending) {
  const acts = (ACTIONS[m.role] || []).map(([a, t]) => `<button type="button" data-act="${a}" title="${esc(t)}">${LABELS[a]}${a === "raw" && state.raw.has(m.id) ? " ✓" : ""}</button>`).join("");
  let role, meta = "", body;
  if (m.role === "user") {
    role = "You";
    body = state.editing === m.id ? editor(m) : `<div class="md">${md(m.text)}</div>`;
  } else if (m.role === "assistant") {
    role = "Assistant";
    const mt = m.meta || {};
    const parts = [];
    if (mt.model) parts.push((mt.model_path ? "ckpt " + mt.model_path.split("/").pop() + " · " : "") + shortModel(mt.model));
    if (mt.renderer) parts.push(mt.renderer);
    if (mt.temperature != null) parts.push("T " + mt.temperature);
    if (mt.prompt_tokens != null) parts.push(`${fmtTok(mt.prompt_tokens)} → ${fmtTok(mt.completion_tokens)} tok`);
    if (mt.seconds != null) parts.push(mt.seconds + "s");
    meta = parts.join(" · ");
    body = state.editing === m.id ? editor(m) : assistantBody(m, pending);
  } else if (m.role === "tool") {
    const call = calls[m.tool_call_id];
    role = `${esc(m.name || call?.name || "tool")} result`;
    const mt = m.meta || {};
    meta = [mt.how, mt.seconds != null ? mt.seconds + "s" : null].filter(Boolean).join(" · ");
    body = state.editing === m.id ? editor(m) : toolOutput(m);
  } else {
    role = esc(m.role);
    body = `<pre>${esc(m.text)}</pre>`;
  }
  if (m.edited) meta = (meta ? meta + " · " : "") + '<span class="edited">edited</span>';
  return `<div class="msg ${esc(m.role)}" data-id="${esc(m.id)}">
    <div class="msg-head"><span class="role">${role}</span><span class="meta" title="${esc(meta.replace(/<[^>]+>/g, ""))}">${meta}</span><div class="msg-actions">${acts}</div></div>
    ${body}
  </div>`;
}
function assistantBody(m, pending) {
  const raw = state.raw.has(m.id);
  let h = "";
  const calls = m.tool_calls || [], unparsed = m.unparsed_tool_calls || [];
  const cutInThinking = m.truncated && !m.text && !calls.length && m.thinking;
  if (m.thinking) {
    const words = m.thinking.split(/\s+/).filter(Boolean).length;
    const label = cutInThinking ? `Reasoning (truncated at max tokens) · ${words} words` : `Reasoning · ${words} words`;
    const inner = raw ? `<pre>${esc(m.thinking)}</pre>` : `<div class="md">${md(m.thinking)}</div>`;
    h += details("think:" + m.id, label, `<div class="thinking-body">${inner}</div>`, !!cutInThinking, "thinking" + (cutInThinking ? " cut" : ""));
  }
  if (m.text) h += raw ? `<pre class="raw">${esc(m.text)}</pre>` : `<div class="md">${md(m.text)}</div>`;
  if (m.truncated) {
    const lim = m.meta && m.meta.max_tokens ? ` (${m.meta.max_tokens})` : "";
    h += `<div class="warn">${cutInThinking ? "Cut off while still reasoning" : "Reply hit the max-token limit"}${lim}. Raise Max tokens in Settings and regenerate.</div>`;
  }
  for (const c of calls) h += toolCall(c, pending.has(c.id));
  for (const u of unparsed) h += `<div class="warn">Tool call could not be parsed (${esc(u.error)}):<pre>${esc(u.raw_text)}</pre></div>`;
  if (!m.text && !m.thinking && !calls.length && !unparsed.length) h += '<div class="muted">(empty reply)</div>';
  return h;
}
function toolCall(c, isPending) {
  const a = c.arguments;
  let body;
  if (a && c.name === "bash" && typeof a.command === "string") body = `<pre><span class="prompt">$ </span>${esc(a.command)}</pre>`;
  else if (a && c.name === "write_file") {
    const content = String(a.content ?? ""), n = content.split("\n").length;
    body = `<div class="call-arg">${esc(a.path)}</div>` + details("call:" + c.id, `content · ${n} lines · ${content.length} chars`, `<pre>${esc(content)}</pre>`, n <= 12);
  } else if (a && c.name === "read_file") body = `<div class="call-arg">${esc(a.path)}${a.offset || a.limit ? ` <span class="hint">(offset ${esc(a.offset ?? 1)}, limit ${esc(a.limit ?? "all")})</span>` : ""}</div>`;
  else if (a && c.name === "web_search") body = `<div class="call-arg">${esc(a.query)}</div>`;
  else if (a && c.name === "fetch_url") body = `<div class="call-arg">${esc(a.url)}</div>`;
  else body = `<pre>${esc(a ? JSON.stringify(a, null, 2) : c.raw_arguments)}</pre>`;
  const bad = a ? "" : '<span class="warn-text">arguments are not valid JSON</span>';
  return `<div class="tool-call"><div class="tool-call-head"><span class="tool-name">${esc(c.name)}</span>${bad}${isPending ? '<span class="pill">not run yet</span>' : ""}</div>${body}</div>`;
}
function toolOutput(m) {
  const text = m.text || "";
  if (!text) return '<div class="tool-out"><div class="muted">(no output)</div></div>';
  const lines = text.split("\n");
  const long = lines.length > 14 || text.length > 1800;
  if (!long) return `<div class="tool-out"><pre>${esc(text)}</pre></div>`;
  const preview = lines.slice(0, 8).join("\n").slice(0, 900);
  return `<div class="tool-out"><pre class="preview">${esc(preview)}</pre>${details("out:" + m.id, `Show all ${lines.length} lines · ${text.length.toLocaleString()} chars`, `<pre>${esc(text)}</pre>`, false)}</div>`;
}
function editor(m) {
  let h = '<div class="editor">';
  if (m.role === "assistant") {
    if (m.thinking) h += `<div class="editor-label">Reasoning</div><textarea data-field="thinking" rows="6">${esc(m.thinking)}</textarea>`;
    h += `<div class="editor-label">Reply text</div>`;
  }
  h += `<textarea data-field="text" rows="${Math.min(18, Math.max(3, (m.text || "").split("\n").length + 1))}">${esc(m.text)}</textarea>`;
  h += '<div class="editor-actions"><button type="button" class="btn small" data-edit="cancel">Cancel</button>';
  h += '<button type="button" class="btn small" data-edit="save">Save</button>';
  if (m.role === "user") h += '<button type="button" class="btn small primary" data-edit="resend" title="Save, drop everything after this message, and generate">Save &amp; resend</button>';
  return h + "</div></div>";
}

$("#messages").addEventListener("click", (e) => {
  const copyBtn = e.target.closest("[data-copy-code]");
  if (copyBtn) return copyText(copyBtn.closest(".code").querySelector("pre").innerText);
  const msgEl = e.target.closest(".msg");
  if (!msgEl) return;
  const id = msgEl.dataset.id, c = state.conv;
  const m = c.messages.find((x) => x.id === id);
  const editBtn = e.target.closest("[data-edit]");
  if (editBtn) {
    const kind = editBtn.dataset.edit;
    if (kind === "cancel") { state.editing = null; return render(); }
    const body = { id };
    for (const ta of $$("textarea[data-field]", msgEl)) body[ta.dataset.field] = ta.value;
    if (kind === "resend") body.resend = true;
    return guarded(async () => { await flushSettings(); const r = await api("POST", `/api/conversations/${c.id}/edit`, body); state.editing = null; state.scrollToBottom = kind === "resend"; setConv(r); });
  }
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (!act || !m) return;
  const post = (path, body) => guarded(async () => { await flushSettings(); const r = await api("POST", `/api/conversations/${c.id}/${path}`, body); setConv(r); return r; });
  switch (act) {
    case "edit": state.editing = id; render(); { const ta = $(`.msg[data-id="${CSS.escape(id)}"] textarea[data-field="text"]`); if (ta) ta.focus(); } break;
    case "regenerate": case "resend": state.scrollToBottom = true; post("regenerate", { id }); break;
    case "rerun": state.scrollToBottom = true; guarded(async () => { await flushSettings(); await api("POST", `/api/conversations/${c.id}/rewind`, { id, where: "before" }); setConv(await api("POST", `/api/conversations/${c.id}/continue`)); }); break;
    case "before": post("rewind", { id, where: "before" }); break;
    case "after": post("rewind", { id, where: "after" }); break;
    case "fork": guarded(async () => { const r = await api("POST", `/api/conversations/${c.id}/duplicate`, { upto: id }); await openConv(r.id, r); await loadSidebar(); toast("Forked into a new conversation", "info"); }); break;
    case "copy": copyText(m.text || ""); break;
    case "raw": state.raw.has(id) ? state.raw.delete(id) : state.raw.add(id); render(); break;
  }
});

// ------------------------------------------------------------------ run status / errors / composer
function renderRun() {
  const c = state.conv, box = $("#run-status");
  clearInterval(state.tick);
  if (!c || !c.run) { box.hidden = true; renderComposer(); return; }
  const r = c.run;
  const draw = () => {
    const skew = (Date.now() - state.runReceivedAt) / 1000;
    const phaseSecs = Math.max(0, Math.round(r.now - r.phase_since + skew));
    const totalSecs = Math.max(0, Math.round(r.now - r.started + skew));
    const step = c.settings.agent && r.step ? ` · model call ${r.step}/${c.settings.max_steps}` : "";
    box.innerHTML = `<div class="spinner"></div><div>${esc(r.phase)} · ${phaseSecs}s${step}${totalSecs !== phaseSecs ? ` <span class="hint">(${totalSecs}s total)</span>` : ""}</div>`;
  };
  draw();
  box.hidden = false;
  state.tick = setInterval(draw, 1000);
  renderComposer();
}
function renderNoticeAndError() {
  const c = state.conv;
  const n = $("#notice"), eb = $("#error-box");
  n.hidden = !c.notice || !!c.run;
  if (!n.hidden) n.innerHTML = `<span>${esc(c.notice)}</span><span class="spacer"></span><button type="button" class="btn small" data-dismiss>Dismiss</button>`;
  const err = c.last_error;
  eb.hidden = !err || !!c.run;
  if (!eb.hidden) {
    eb.innerHTML = `<strong>Error.</strong> ${esc(err.message)}<div class="hint">The conversation is saved; nothing was lost.</div>
      ${err.trace ? details("trace:" + c.id, "Details", `<pre>${esc(err.trace)}</pre>`, false) : ""}
      <div class="err-actions"><button type="button" class="btn small primary" data-retry>Retry</button><button type="button" class="btn small" data-dismiss>Dismiss</button></div>`;
  }
}
document.addEventListener("click", (e) => {
  if (!state.conv) return;
  if (e.target.closest("[data-retry]")) continueRun();
  else if (e.target.closest("[data-dismiss]")) guarded(async () => setConv(await api("POST", `/api/conversations/${state.conv.id}/dismiss`)));
});
function renderComposer() {
  const c = state.conv;
  if (!c) return;
  const running = !!c.run;
  $("#btn-stop").hidden = !running;
  $("#btn-send").disabled = running;
  const showContinue = !running && canContinue(c);
  $("#btn-continue").hidden = !showContinue;
  $("#btn-continue").textContent = c.last_error ? "Retry" : "Continue";
  $("#btn-undo").hidden = !c.undo_depth || running;
}
async function send() {
  const c = state.conv, input = $("#input");
  const text = input.value;
  if (!c || !text.trim() || c.run) return;
  await flushSettings();
  input.value = "";
  autosize();
  state.scrollToBottom = true;
  try {
    setConv(await api("POST", `/api/conversations/${c.id}/send`, { text }));
    loadSidebar();
  } catch (e) {
    input.value = text;  // don't lose what was typed
    autosize();
    toast(e.message);
  }
}
function continueRun() {
  state.scrollToBottom = true;
  guarded(async () => {
    await flushSettings();
    setConv(await api("POST", `/api/conversations/${state.conv.id}/continue`));
  });
}
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
function autosize() {
  const t = $("#input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight + 2, window.innerHeight * 0.4) + "px";
}
$("#input").addEventListener("input", autosize);
$("#btn-continue").addEventListener("click", continueRun);
$("#btn-stop").addEventListener("click", () => guarded(async () => {
  $("#btn-stop").disabled = true;
  try { setConv(await api("POST", `/api/conversations/${state.conv.id}/stop`)); } finally { $("#btn-stop").disabled = false; }
  loadSidebar();
}));
$("#btn-undo").addEventListener("click", () => guarded(async () => setConv(await api("POST", `/api/conversations/${state.conv.id}/undo`))));
$("#title").addEventListener("change", () => guarded(async () => {
  const r = await api("PATCH", `/api/conversations/${state.conv.id}`, { title: $("#title").value });
  state.conv.title = r.title;
  state.conv.version = r.version;
  loadSidebar();
}));
$("#title").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });

// ------------------------------------------------------------------ raw prompt dialog
$("#btn-prompt").addEventListener("click", () => guarded(async () => {
  const dlg = $("#prompt-dialog");
  $("#prompt-text").textContent = "Rendering…";
  $("#prompt-meta").textContent = "";
  dlg.showModal();
  try {
    const r = await api("GET", `/api/conversations/${state.conv.id}/prompt`);
    $("#prompt-text").textContent = r.text;
    $("#prompt-meta").textContent = `${r.tokens.toLocaleString()} tokens · ${r.model} · ${r.renderer} (this is what the model sees for its next reply)`;
  } catch (e) {
    $("#prompt-text").textContent = "Error: " + e.message;
  }
}));
$("#prompt-close").addEventListener("click", () => $("#prompt-dialog").close());
$("#prompt-copy").addEventListener("click", () => copyText($("#prompt-text").textContent));

// ------------------------------------------------------------------ settings panel
const form = $("#settings-form");
function setSettingsOpen(open) {
  $("#app").classList.toggle("no-settings", !open);
  pref("settingsOpen", open ? "1" : "0");
}
$("#toggle-settings").addEventListener("click", () => setSettingsOpen($("#app").classList.contains("no-settings")));
$("#toggle-sidebar").addEventListener("click", () => {
  const hide = !$("#app").classList.contains("no-sidebar");
  $("#app").classList.toggle("no-sidebar", hide);
  pref("sidebarHidden", hide ? "1" : "0");
});

function modelOptionsHtml(selected, extraLabel) {
  const names = state.models.map((m) => m.name);
  let h = state.models.map((m) => `<option value="${esc(m.name)}">${esc(m.name)}${m.max_context ? ` (${Math.round(m.max_context / 1024)}k ctx)` : ""}</option>`).join("");
  if (selected && !names.includes(selected)) h = `<option value="${esc(selected)}">${esc(selected)} ${extraLabel}</option>` + h;
  return h;
}
async function rendererInfoFor(model) {
  if (state.rendererInfo[model]) return state.rendererInfo[model];
  try { state.rendererInfo[model] = await api("GET", `/api/renderers?model=${encodeURIComponent(model)}`); }
  catch { state.rendererInfo[model] = { renderers: [], default_renderer: "" }; }
  return state.rendererInfo[model];
}
function rendererOptionsHtml(info, selected) {
  const rec = info.renderers || [];
  const rest = state.allRenderers.filter((r) => !rec.includes(r));
  let h = rec.length ? `<optgroup label="Recommended for this model">${rec.map((r) => `<option>${esc(r)}</option>`).join("")}</optgroup>` : "";
  h += `<optgroup label="${rec.length ? "Other renderers" : "All renderers (model not recognised; pick its family)"}">${rest.map((r) => `<option>${esc(r)}</option>`).join("")}</optgroup>`;
  if (selected && !rec.includes(selected) && !rest.includes(selected)) h = `<option>${esc(selected)}</option>` + h;
  return h;
}
async function fillModelSelects() {
  const s = state.conv.settings;
  $("#s-model").innerHTML = modelOptionsHtml(s.model, s.use_checkpoint ? "(checkpoint base)" : "(not listed by the server)");
  $("#s-model").value = s.model;
  $("#s-renderer").innerHTML = rendererOptionsHtml(await rendererInfoFor(s.model), s.renderer);
  $("#s-renderer").value = s.renderer;
  $("#s-sim-model").innerHTML = modelOptionsHtml(s.sim_model, "(not listed by the server)");
  $("#s-sim-model").value = s.sim_model;
  $("#s-sim-renderer").innerHTML = rendererOptionsHtml(await rendererInfoFor(s.sim_model), s.sim_renderer);
  $("#s-sim-renderer").value = s.sim_renderer;
}
async function fillSettings() {
  const s = state.conv.settings;
  for (const el of form.elements) {
    if (!el.name || el.name === "tools") continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else if (el.type === "radio") el.checked = s[el.name] === el.value;
    else if (el.tagName !== "SELECT" || !["model", "renderer", "sim_model", "sim_renderer"].includes(el.name)) el.value = s[el.name] ?? "";
  }
  $("#s-tools").innerHTML = TOOL_NAMES.map((t) => `<label class="check"><input type="checkbox" name="tools" value="${t}"${(s.tools || []).includes(t) ? " checked" : ""}> ${t}</label>`).join("");
  await fillModelSelects();
  updateSettingsVisibility();
}
const TOOL_NAMES = ["bash", "read_file", "write_file", "web_search", "fetch_url"];
function updateSettingsVisibility() {
  const s = state.conv.settings, st = state.status || {};
  $("#ckpt-fields").hidden = !s.use_checkpoint;
  $("#model-label").textContent = s.use_checkpoint ? "Base model of the checkpoint (sets tokenizer and renderer)" : "Model";
  $("#agent-fields").classList.toggle("off", !s.agent);
  $("#docker-fields").hidden = s.backend !== "docker";
  $("#sim-scope").textContent = s.backend === "docker" ? "(used for web_search" + (s.fetch_mode === "simulated" ? " and fetch_url)" : ")") : "(used for all tools except write_file" + (s.fetch_mode === "real" ? " and fetch_url)" : ")");
  $("#sim-tinker").hidden = s.sim_provider === "openai";
  $("#sim-openai").hidden = s.sim_provider !== "openai";
  $("#openai-hint").textContent = st.openai_key ? "Uses OPENAI_API_KEY from the server environment." : "OPENAI_API_KEY is not set in the server environment.";
  const d = st.docker || { available: false, reason: "checking…" };
  const radio = $('#docker-radio input');
  radio.disabled = !d.available && s.backend !== "docker";
  $("#docker-radio").classList.toggle("disabled", !d.available);
  $("#docker-radio").title = d.available ? `Docker ${d.version}` : `Docker is not available: ${d.reason}`;
  $("#docker-reason").textContent = d.available ? "" : `Docker unavailable: ${d.reason}`;
  if (s.use_checkpoint && !state.checkpointsLoaded) loadCheckpoints();
}
async function loadCheckpoints() {
  state.checkpointsLoaded = true;
  try {
    const r = await api("GET", "/api/checkpoints");
    $("#ckpt-list").innerHTML = r.checkpoints.map((c) => `<option value="${esc(c.path)}">${esc(c.id)} · ${esc((c.time || "").slice(0, 10))}</option>`).join("");
  } catch { /* optional convenience */ }
}

function readForm() {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.name === "tools") continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.type === "radio") { if (el.checked) out[el.name] = el.value; }
    else if (el.type === "number") { if (el.value !== "") out[el.name] = Number(el.value); }
    else out[el.name] = el.value;
  }
  out.tools = $$('input[name="tools"]', form).filter((x) => x.checked).map((x) => x.value);
  return out;
}
function queueSettings(patch) {
  Object.assign(state.pendingSettings, patch);
  Object.assign(state.conv.settings, patch);
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(flushSettings, 400);
}
function flushSettings() {
  clearTimeout(state.saveTimer);
  const patch = state.pendingSettings;
  if (!state.conv || !Object.keys(patch).length) return Promise.resolve();
  state.pendingSettings = {};
  const id = state.conv.id;
  return api("PATCH", `/api/conversations/${id}`, { settings: patch }).then((r) => {
    if (state.conv && state.conv.id === id) { state.conv.version = r.version; state.conv.settings = { ...r.settings, ...state.pendingSettings }; render(); }
  }).catch((e) => toast("Settings not saved: " + e.message));
}
form.addEventListener("submit", (e) => e.preventDefault());
form.addEventListener("input", (e) => {
  if (!state.conv || !e.target.name) return;
  if (["SELECT"].includes(e.target.tagName) || e.target.type === "checkbox" || e.target.type === "radio") return;  // handled on change
  const v = readForm();
  queueSettings({ [e.target.name]: v[e.target.name] });
});
form.addEventListener("change", async (e) => {
  if (!state.conv || !e.target.name) return;
  const name = e.target.name, v = readForm(), s = state.conv.settings;
  const patch = { [name]: name === "tools" ? v.tools : v[name] };
  if (name === "model" || name === "sim_model") {
    const info = await rendererInfoFor(v[name]);
    const rkey = name === "model" ? "renderer" : "sim_renderer";
    if (!(info.renderers || []).includes(s[rkey]) && info.default_renderer) patch[rkey] = info.default_renderer;
  }
  if (name === "agent" && v.agent && !(s.system || "").trim() && state.status) {
    patch.system = state.status.defaults.agent_system;
    form.elements.system.value = patch.system;
    toast("Filled in a default agent system prompt; edit it in Settings.", "info");
  }
  if (name === "model_path" && v.use_checkpoint) inspectCheckpoint(v.model_path);
  if (name === "use_checkpoint" && v.use_checkpoint && v.model_path) inspectCheckpoint(v.model_path);
  queueSettings(patch);
  if (["model", "sim_model", "use_checkpoint"].includes(name)) await fillModelSelects();
  updateSettingsVisibility();
  render();
});
async function inspectCheckpoint(path) {
  const info = $("#ckpt-info");
  path = (path || "").trim();
  if (!path) return;
  info.textContent = "Looking up checkpoint…";
  try {
    const r = await api("POST", "/api/checkpoint/inspect", { path });
    state.rendererInfo[r.base_model] = r;
    const s = state.conv.settings, patch = { model: r.base_model };
    if (!(r.renderers || []).includes(s.renderer) && r.default_renderer) patch.renderer = r.default_renderer;
    queueSettings(patch);
    await fillModelSelects();
    render();
    info.innerHTML = `Base model: <b>${esc(r.base_model)}</b>${r.lora_rank ? ` · LoRA rank ${esc(r.lora_rank)}` : ""}` +
      (r.served === false ? `<br><span class="warn-text">Tinker does not currently list this base model as sampleable; sampling may fail.</span>` : "");
  } catch (e) {
    info.innerHTML = `<span class="warn-text">${esc(e.message)}</span><br>Pick the base model above by hand.`;
  }
}
$("#btn-reset-container").addEventListener("click", () => {
  if (!confirm("Remove this conversation's Docker container? The next tool call starts a fresh one.")) return;
  guarded(async () => { setConv(await api("POST", `/api/conversations/${state.conv.id}/container/reset`)); toast("Container removed", "info"); });
});

// ------------------------------------------------------------------ boot
function renderBanner() {
  const st = state.status, msgs = [];
  if (st && !st.tinker_key) msgs.push("TINKER_API_KEY is not set in the server's environment, so sampling will fail. Restart the server with it set.");
  if (state.modelsError) msgs.push("Could not load the model list from Tinker: " + state.modelsError);
  $("#banner").hidden = !msgs.length;
  $("#banner").textContent = msgs.join(" ");
  if (st) $("#side-foot").textContent = "Saved in " + st.conversations_dir;
}
async function loadStatus() {
  try { state.status = await api("GET", "/api/status"); } catch (e) { toast(e.message); }
  renderBanner();
  if (state.conv) updateSettingsVisibility();
}
async function boot() {
  if (pref("settingsOpen") === "0") $("#app").classList.add("no-settings");
  if (pref("sidebarHidden") === "1") $("#app").classList.add("no-sidebar");
  await loadStatus();
  try {
    const r = await api("GET", "/api/models");
    state.models = r.models;
    state.allRenderers = r.all_renderers;
    state.modelsError = r.error;
    for (const m of r.models) state.rendererInfo[m.name] = m;
  } catch (e) { state.modelsError = e.message; }
  renderBanner();
  await loadSidebar();
  const m = location.hash.match(/^#\/c\/([\w-]+)/);
  const id = m && state.convs.some((c) => c.id === m[1]) ? m[1] : state.convs[0]?.id;
  if (id) await openConv(id); else await newChat();
  setInterval(loadStatus, 30000);
}
window.addEventListener("hashchange", () => {
  const m = location.hash.match(/^#\/c\/([\w-]+)/);
  if (m && (!state.conv || state.conv.id !== m[1])) guarded(() => openConv(m[1]));
});
window.addEventListener("beforeunload", () => { if (Object.keys(state.pendingSettings).length) flushSettings(); });
boot().catch((e) => toast(e.message));
