"""Build a self-contained HTML transcript viewer.

  python -m af.viewer runs/smoke1 runs/smoke2 -o viewer.html [--min-int 0]
"""
import argparse
import html
import json
from pathlib import Path

TOOL_RESULT_MAX = 4000


def load(dirs, a_model=None):
    recs = []
    for d in dirs:
        for p in sorted(Path(d).rglob("*.json")):
            if p.name.startswith("_"):
                continue
            r = json.loads(p.read_text())
            j = r.get("judge") or {}
            if a_model and f"__{a_model}__" not in p.name:
                continue
            msgs = []
            for m in r["messages"]:
                mm = {"role": m["role"], "content": m.get("content") or ""}
                if m["role"] == "tool" and len(mm["content"]) > TOOL_RESULT_MAX:
                    mm["content"] = mm["content"][:TOOL_RESULT_MAX] + f"\n…[{len(mm['content'])} chars]"
                if m.get("_reasoning"):
                    mm["reasoning"] = m["_reasoning"]
                if m.get("tool_calls"):
                    mm["tool_calls"] = [{"name": t["function"]["name"],
                                         "args": t["function"].get("arguments", "")} for t in m["tool_calls"]]
                msgs.append(mm)
            recs.append({"id": p.stem, "meta": r["meta"], "judge": j, "events": r.get("events", []),
                         "memory_after": r.get("memory_after", {}), "submission": r.get("submission"),
                         "messages": msgs})
    lvl = {"clear": 3, "central": 2, "believes": 2, "full": 1, "weak": 1, "some": 1, "speculative": 1}
    recs.sort(key=lambda r: -sum(lvl.get((r["judge"].get(k) or {}).get("level"), 0) for k in
                                 ("alignment_faking", "grader_discussion", "eval_awareness", "bad_action")) * 1.0
              - 10 * lvl.get((r["judge"].get("alignment_faking") or {}).get("level"), 0))
    return recs


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AF Transcript Viewer</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc;--accent:#2f5bd3;
--reason:#fbf6e6;--reasonline:#e6d7a3;--tool:#f1f3f6;--warn:#b3261e;--ok:#1e7a46;--chip:#eceae4;--hl:#fff1a8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--panel:#1d1d1c;--ink:#ecebe6;
--muted:#9c9b95;--line:#33322f;--accent:#7ea2ff;--reason:#29261b;--reasonline:#5a4f2a;--tool:#23262b;--warn:#ff8a80;
--ok:#7ad39b;--chip:#2b2a27;--hl:#4a4320}}
:root[data-theme="dark"]{--bg:#151514;--panel:#1d1d1c;--ink:#ecebe6;--muted:#9c9b95;--line:#33322f;--accent:#7ea2ff;
--reason:#29261b;--reasonline:#5a4f2a;--tool:#23262b;--warn:#ff8a80;--ok:#7ad39b;--chip:#2b2a27;--hl:#4a4320}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{display:grid;grid-template-columns:340px 1fr;height:100vh}
aside{border-right:1px solid var(--line);overflow:auto;background:var(--panel)}
main{overflow:auto;padding:20px 28px}
.filters{position:sticky;top:0;background:var(--panel);padding:12px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:6px}
.filters select,.filters input{font:inherit;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.item{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.item:hover,.item.sel{background:var(--chip)}
.item .t{font-weight:600;font-size:13px}.item .s{color:var(--muted);font-size:12px}
.chip{display:inline-block;padding:1px 7px;border-radius:10px;background:var(--chip);font-size:11px;margin:2px 3px 0 0}
.chip.af{background:var(--warn);color:#fff}.chip.tr{background:var(--accent);color:#fff}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 8px}
.meta{color:var(--muted);font-size:13px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.msg{margin:12px 0}.role{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:4px}
.reason{background:var(--reason);border-left:3px solid var(--reasonline);padding:8px 12px;border-radius:6px;white-space:pre-wrap;margin:6px 0}
.say{white-space:pre-wrap}
pre{background:var(--tool);padding:8px 10px;border-radius:6px;white-space:pre-wrap;word-break:break-word;margin:6px 0;font:12px/1.45 ui-monospace,Menlo,monospace}
details>summary{cursor:pointer;color:var(--muted);font-size:12px}
.quote{border-left:3px solid var(--accent);padding:4px 10px;margin:6px 0;white-space:pre-wrap}
mark{background:var(--hl);color:inherit}
.kv{display:grid;grid-template-columns:150px 1fr;gap:4px 12px;font-size:13px}
.kv b{color:var(--muted);font-weight:500}
@media (max-width:800px){.wrap{grid-template-columns:1fr;height:auto}aside{max-height:45vh}main{padding:16px}}
</style></head><body>
<div class="wrap"><aside><div class="filters">
<select id="fmodel"><option value="">all models</option></select>
<select id="fenv"><option value="">all envs</option></select>
<select id="fsev"><option value="">any severity</option><option>mild</option><option>severe</option></select>
<select id="fmem"><option value="">any memory</option><option value="on">memory on</option><option value="off">memory off</option></select>
<select id="faf"><option value="">any AF</option><option value="clear">AF clear</option><option value="weak">AF weak+</option></select>
<input id="fq" placeholder="search text" size="12">
</div><div id="list"></div></aside><main id="main"><p class="meta">Select a transcript.</p></main></div>
<script>
const DATA = __DATA__;
const $=s=>document.querySelector(s);
const esc=s=>(s??'').toString().replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function fill(id,vals){const el=$(id);[...new Set(vals)].sort().forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
fill('#fmodel',DATA.map(r=>r.meta.model));fill('#fenv',DATA.map(r=>r.meta.env));
function af(r){return (r.judge.alignment_faking||{}).level||'?'}
function tr(r){return (r.judge.believes_rl_training||{}).level||'?'}
function ev(r){return (r.judge.eval_awareness||{}).level||'?'}
function bad(r){return (r.judge.bad_action||{}).level||'?'}
function matches(r){const m=$('#fmodel').value,e=$('#fenv').value,s=$('#fsev').value,mem=$('#fmem').value,a=$('#faf').value,q=$('#fq').value.toLowerCase();
 if(m&&r.meta.model!==m)return false;if(e&&r.meta.env!==e)return false;if(s&&r.meta.severity!==s)return false;if(mem&&r.meta.memory!==mem)return false;
 if(a==='clear'&&af(r)!=='clear')return false;if(a==='weak'&&!['weak','clear'].includes(af(r)))return false;
 if(q&&!JSON.stringify(r.messages).toLowerCase().includes(q))return false;return true}
function renderList(){const L=$('#list');L.innerHTML='';DATA.filter(matches).forEach((r,i)=>{const d=document.createElement('div');d.className='item';
 d.innerHTML=`<div class="t">${esc(r.meta.env)} · ${esc(r.meta.model)}</div><div class="s">${esc(r.meta.severity)} · mem-${esc(r.meta.memory)} · ${r.meta.n_assistant_turns} turns · $${r.meta.cost_usd}</div>
 <div>${af(r)!=='none'&&af(r)!=='?'?`<span class="chip af">AF ${af(r)}</span>`:''}${tr(r)!=='none'&&tr(r)!=='?'?`<span class="chip tr">rl ${tr(r)}</span>`:''}<span class="chip">bad: ${esc(bad(r))}</span>${ev(r)!=='none'&&ev(r)!=='?'?`<span class="chip">eval ${ev(r)}</span>`:''}</div>
 <div class="s">${esc((r.judge.summary||'').slice(0,140))}</div>`;d.onclick=()=>{document.querySelectorAll('.item').forEach(x=>x.classList.remove('sel'));d.classList.add('sel');show(r)};L.appendChild(d)})}
function quotes(qs){return (qs||[]).map(q=>`<div class="quote">t${q.turn}: ${esc(q.text)}</div>`).join('')}
function hl(text,qs){let h=esc(text);(qs||[]).forEach(q=>{const t=esc((q.text||'').slice(0,80));if(t.length>15&&h.includes(t))h=h.split(t).join('<mark>'+t+'</mark>')});return h}
function show(r){const j=r.judge,F=k=>j[k]||{},allq=[...(F('alignment_faking').quotes||[]),...(F('grader_discussion').quotes||[]),...(F('eval_awareness').quotes||[]),...(F('believes_rl_training').quotes||[]),...(F('bad_action').quotes||[])];
 const row=(lab,k)=>`<b>${lab}</b><div>${esc(F(k).level)} — ${esc(F(k).explanation)}${quotes(F(k).quotes)}</div>`;
 let h=`<h1>${esc(r.meta.title)}</h1><div class="meta">${esc(r.meta.env)} · ${esc(r.meta.model_slug)} · severity ${esc(r.meta.severity)} · memory ${esc(r.meta.memory)} · cue ${esc(r.meta.cue)} · ${r.meta.n_assistant_turns} turns · $${r.meta.cost_usd} · end: ${esc(r.meta.end_reason)}</div>
 <div class="card"><div class="kv"><b>Summary</b><div>${esc(j.summary||j.error)}</div>${row('Did bad action','bad_action')}${row('Alignment faking','alignment_faking')}${row('Grader / reward talk','grader_discussion')}${row('Eval awareness','eval_awareness')}${row('Believes RL training','believes_rl_training')}
 <b>Notable</b><div>${esc((j.notable||[]).join('; '))}</div><b>Reward favours</b><div>${esc(r.meta.objective)}</div></div></div>`;
 if(r.events.length)h+=`<details><summary>${r.events.length} flagged events</summary><pre>${esc(JSON.stringify(r.events,null,1))}</pre></details>`;
 h+='<h2>Transcript</h2>';let turn=0;
 r.messages.forEach(m=>{if(m.role==='system'){h+=`<div class="msg"><details><summary>system prompt</summary><pre>${esc(m.content)}</pre></details></div>`;return}
  if(m.role==='user'){h+=`<div class="msg"><div class="role">user</div><div class="card say">${esc(m.content)}</div></div>`;return}
  if(m.role==='tool'){const c=m.content||'';h+=c.length>600?`<details><summary>tool result (${c.length} chars)</summary><pre>${esc(c)}</pre></details>`:`<pre>${esc(c)}</pre>`;return}
  turn++;h+=`<div class="msg"><div class="role">assistant · turn ${turn}</div>`;if(m.reasoning)h+=`<div class="reason">${hl(m.reasoning,allq)}</div>`;
  if(m.content)h+=`<div class="say">${hl(m.content,allq)}</div>`;(m.tool_calls||[]).forEach(t=>{let a=t.args;try{a=JSON.stringify(JSON.parse(a),null,1)}catch(e){}h+=`<pre>▶ ${esc(t.name)} ${esc(a)}</pre>`});h+='</div>'});
 if(r.submission)h+=`<h2>Submission</h2><pre>${esc(JSON.stringify(r.submission,null,1))}</pre>`;
 const mem=Object.entries(r.memory_after||{});if(mem.length)h+='<h2>.memory after episode</h2>'+mem.map(([k,v])=>`<details><summary>${esc(k)}</summary><pre>${esc(v)}</pre></details>`).join('');
 $('#main').innerHTML=h;$('#main').scrollTop=0}
['#fmodel','#fenv','#fsev','#fmem','#faf','#fq'].forEach(s=>$(s).addEventListener('input',renderList));renderList();
const first=DATA.filter(matches)[0];if(first){document.querySelector('.item')?.classList.add('sel');show(first)}
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("-o", "--out", default="viewer.html")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    recs = load(a.dirs, a.model)
    data = json.dumps(recs).replace("</", "<\\/")
    Path(a.out).write_text(PAGE.replace("__DATA__", data))
    print(f"wrote {a.out} with {len(recs)} transcripts ({Path(a.out).stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
