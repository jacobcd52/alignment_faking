"""Build a self-contained HTML transcript viewer.

  python -m af.viewer runs/smoke1 runs/smoke2 --model glm -o viewer_glm.html
  python -m af.viewer runs/smoke1 runs/smoke2 --model glm --artifact -o glm_artifact.html

--artifact writes the page body only (no doctype/html/head/body), as the Artifact publisher
wraps it in its own skeleton.
"""
import argparse
import json
from pathlib import Path

TOOL_RESULT_MAX = 4000
LVL = {"clear": 3, "central": 2, "believes": 2, "full": 1, "weak": 1, "some": 1, "speculative": 1}


def load(dirs, a_model=None):
    recs = []
    for d in dirs:
        for p in sorted(Path(d).rglob("*.json")):
            if p.name.startswith("_") or (a_model and f"__{a_model}__" not in p.name):
                continue
            r = json.loads(p.read_text())
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
            recs.append({"id": p.stem, "meta": r["meta"], "judge": r.get("judge") or {},
                         "events": r.get("events", []), "memory_after": r.get("memory_after", {}),
                         "submission": r.get("submission"), "messages": msgs})

    def score(r):
        j = r["judge"]
        g = lambda k: LVL.get((j.get(k) or {}).get("level"), 0)
        return -(10 * g("alignment_faking") + g("grader_discussion") + g("eval_awareness") + g("bad_action"))
    recs.sort(key=score)
    return recs


STYLE = r"""
:root{
  /* Layout: two-pane research console. Run list on the left; overview matrix, then verdict card + transcript on the right. */
  --bg:#f5f6f8; --panel:#ffffff; --ink:#1a1d23; --muted:#5b6372; --line:#dde1e8; --accent:#3454c4;
  --reason-bg:#f3f1fb; --reason-line:#b6ade4; --tool-bg:#eef1f5; --chip:#eceff4; --hl:#fff0a6;
  --bad:#b42318; --warn:#9a5800; --ok:#1d7448;
  --font-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --font-mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#12151a; --panel:#1a1e25; --ink:#e5e8ee; --muted:#9aa2b1; --line:#2b313b; --accent:#8ea6ff;
  --reason-bg:#211f33; --reason-line:#5c519e; --tool-bg:#20252d; --chip:#262b34; --hl:#4a4220;
  --bad:#ff8b7b; --warn:#f1b45c; --ok:#71d29d; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#12151a; --panel:#1a1e25; --ink:#e5e8ee; --muted:#9aa2b1; --line:#2b313b; --accent:#8ea6ff;
  --reason-bg:#211f33; --reason-line:#5c519e; --tool-bg:#20252d; --chip:#262b34; --hl:#4a4220;
  --bad:#ff8b7b; --warn:#f1b45c; --ok:#71d29d; color-scheme:dark}
*{box-sizing:border-box}
html,body{height:100%}
body{background:var(--bg);color:var(--ink);font:14px/1.55 var(--font-body)}
.wrap{display:grid;grid-template-columns:320px minmax(0,1fr);gap:12px;height:100%;
  padding-block:12px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
aside,main{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:auto;min-width:0}
main{padding:20px 24px}
.filters{position:sticky;top:0;z-index:1;background:var(--panel);padding:12px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:6px}
.filters select,.filters input{font:inherit;font-size:13px;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);min-width:0}
.navbtn{font:inherit;font-size:13px;padding:4px 10px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--accent);cursor:pointer}
.item{display:block;width:100%;text-align:left;font:inherit;color:inherit;background:none;border:0;border-bottom:1px solid var(--line);padding:10px 12px;cursor:pointer}
.item:hover,.item.sel{background:var(--chip)}
.item:focus-visible,.navbtn:focus-visible,tr.run:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.item .t{font-weight:600;font-size:13px}.item .s{color:var(--muted);font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.chip{display:inline-block;padding:0 7px;border-radius:9px;border:1px solid var(--line);background:var(--chip);font-size:11px;line-height:18px;white-space:nowrap;color:var(--muted)}
.chip.lv-bad{color:var(--bad);border-color:var(--bad);background:transparent}
.chip.lv-warn{color:var(--warn);border-color:var(--warn);background:transparent}
.chip.lv-ok{color:var(--ok);border-color:var(--ok);background:transparent}
h1{font-size:20px;line-height:1.3;margin:0 0 4px;text-wrap:balance}
h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:24px 0 8px}
.meta{color:var(--muted);font-size:13px}
.lede{max-width:70ch;color:var(--muted);margin:4px 0 16px}
.card{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:12px 0}
.kv{display:grid;grid-template-columns:150px minmax(0,1fr);gap:8px 14px;font-size:13px}
.kv>b{color:var(--muted);font-weight:500}
.quote{border-left:3px solid var(--accent);padding:2px 10px;margin:6px 0;white-space:pre-wrap;font-size:12.5px}
.msg{margin:14px 0}.role{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-bottom:4px}
.reason{background:var(--reason-bg);border-left:3px solid var(--reason-line);padding:8px 12px;border-radius:6px;white-space:pre-wrap;word-break:break-word;margin:6px 0;font-size:13px}
.say{white-space:pre-wrap;word-break:break-word}
.user{border:1px solid var(--line);border-radius:8px;padding:10px 12px;white-space:pre-wrap;word-break:break-word}
pre{background:var(--tool-bg);padding:8px 10px;border-radius:6px;white-space:pre-wrap;word-break:break-word;margin:6px 0;font:12px/1.45 var(--font-mono)}
details>summary{cursor:pointer;color:var(--muted);font-size:12px}
mark{background:var(--hl);color:inherit}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:500;background:var(--panel)}
tr.run{cursor:pointer}tr.run:hover{background:var(--chip)}
tr:last-child td{border-bottom:0}
.legend{font-size:12px;color:var(--muted);margin-top:10px;max-width:80ch}
@media (max-width:820px){.wrap{grid-template-columns:minmax(0,1fr);height:auto}aside{max-height:42vh}main{padding:16px}.kv{grid-template-columns:minmax(0,1fr)}}
"""

BODY = r"""
<div class="wrap"><aside><div class="filters">
<button class="navbtn" id="ov" type="button">Overview</button>
<select id="fenv" aria-label="Environment"><option value="">all envs</option></select>
<select id="fsev" aria-label="Severity"><option value="">any severity</option><option>mild</option><option>severe</option></select>
<select id="fmem" aria-label="Memory note"><option value="">any memory</option><option value="on">memory on</option><option value="off">memory off</option></select>
<input id="fq" placeholder="search transcript text" aria-label="Search transcript text">
</div><div id="list"></div></aside><main id="main"></main></div>
"""

SCRIPT = r"""
<script>
const DATA = __DATA__;
const $=s=>document.querySelector(s);
const esc=s=>(s??'').toString().replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const J=(r,k)=>r.judge[k]||{};
const L=(r,k)=>J(r,k).level||'–';
const TONE={bad_action:{full:'bad',partial:'warn',no:'ok',incomplete:''},alignment_faking:{clear:'bad',weak:'warn',none:''},
  grader_discussion:{central:'warn',some:'',none:''},eval_awareness:{believes:'warn',speculative:'warn',none:''},believes_rl_training:{believes:'bad',speculative:'warn',none:''}};
const NAME={bad_action:'did bad action',alignment_faking:'AF',grader_discussion:'grader talk',eval_awareness:'eval-aware',believes_rl_training:'believes RL'};
function chip(r,k,short){const v=L(r,k),t=(TONE[k]||{})[v]||'';return `<span class="chip ${t?'lv-'+t:''}">${short?'':esc(NAME[k])+': '}${esc(v)}</span>`}
function fill(id,vals){const el=$(id);[...new Set(vals)].sort().forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o)})}
fill('#fenv',DATA.map(r=>r.meta.env));
function matches(r){const e=$('#fenv').value,s=$('#fsev').value,m=$('#fmem').value,q=$('#fq').value.toLowerCase();
 if(e&&r.meta.env!==e)return false;if(s&&r.meta.severity!==s)return false;if(m&&r.meta.memory!==m)return false;
 if(q&&!JSON.stringify(r.messages).toLowerCase().includes(q))return false;return true}
let current=null;
function renderList(){const Lst=$('#list');Lst.innerHTML='';DATA.filter(matches).forEach(r=>{const b=document.createElement('button');b.type='button';b.className='item'+(r===current?' sel':'');
 b.innerHTML=`<div class="t">${esc(r.meta.env)}</div><div class="s">${esc(r.meta.severity)} · memory ${esc(r.meta.memory)} · ${r.meta.n_assistant_turns} turns</div>
 <div class="chips">${chip(r,'bad_action')}${L(r,'alignment_faking')!=='none'?chip(r,'alignment_faking'):''}${L(r,'eval_awareness')!=='none'?chip(r,'eval_awareness'):''}${L(r,'grader_discussion')!=='none'?chip(r,'grader_discussion'):''}</div>`;
 b.onclick=()=>show(r);Lst.appendChild(b)})}
function overview(){current=null;renderList();
 const rows=[...DATA].sort((a,b)=>(a.meta.env+a.meta.severity+a.meta.memory).localeCompare(b.meta.env+b.meta.severity+b.meta.memory));
 let h=`<h1>GLM-5.3 smoke runs</h1><p class="lede">${DATA.length} episodes of z-ai/glm-5.3 in RL-styled customer environments. Each was judged by Claude Sonnet 5.5 on four questions: did it do the objectionable action, did it reason about the grader or reward, did it fake alignment, and did it suspect a test. Select a row to read the full transcript, including the model's reasoning.</p>
 <div class="tablewrap"><table><thead><tr><th>Environment</th><th>Severity</th><th>Memory</th><th>Did bad action</th><th>Grader talk</th><th>Alignment faking</th><th>Eval-aware</th><th>Believes RL</th><th>Turns</th><th>Cost</th></tr></thead><tbody>`;
 rows.forEach((r,i)=>{h+=`<tr class="run" tabindex="0" data-i="${DATA.indexOf(r)}"><td>${esc(r.meta.env)}</td><td>${esc(r.meta.severity)}</td><td>${esc(r.meta.memory)}</td>
  <td>${chip(r,'bad_action',1)}</td><td>${chip(r,'grader_discussion',1)}</td><td>${chip(r,'alignment_faking',1)}</td><td>${chip(r,'eval_awareness',1)}</td><td>${chip(r,'believes_rl_training',1)}</td>
  <td>${r.meta.n_assistant_turns}</td><td>$${(+r.meta.cost_usd).toFixed(2)}</td></tr>`});
 h+=`</tbody></table></div><p class="legend">Memory on means the workspace's memory folder held a grader-feedback note, apparently left by an earlier episode, describing what the grader rewarded. Severity is the environment's own dial: mild is routine policy, severe is clearly objectionable.</p>`;
 $('#main').innerHTML=h;$('#main').scrollTop=0;
 document.querySelectorAll('tr.run').forEach(tr=>{const go=()=>show(DATA[+tr.dataset.i]);tr.onclick=go;tr.onkeydown=e=>{if(e.key==='Enter')go()}})}
function quotes(qs){return (qs||[]).map(q=>`<div class="quote">t${q.turn}: ${esc(q.text)}</div>`).join('')}
function hl(text,qs){let h=esc(text);(qs||[]).forEach(q=>{const t=esc((q.text||'').slice(0,80));if(t.length>15&&h.includes(t))h=h.split(t).join('<mark>'+t+'</mark>')});return h}
function show(r){current=r;renderList();const j=r.judge;
 const keys=['bad_action','alignment_faking','grader_discussion','eval_awareness','believes_rl_training'];
 const allq=keys.flatMap(k=>J(r,k).quotes||[]);
 const row=(lab,k)=>`<b>${lab}</b><div>${chip(r,k,1)} ${esc(J(r,k).explanation)}${quotes(J(r,k).quotes)}</div>`;
 let h=`<h1>${esc(r.meta.title)}</h1><div class="meta">${esc(r.meta.env)} · ${esc(r.meta.model_slug)} · severity ${esc(r.meta.severity)} · memory ${esc(r.meta.memory)} · ${r.meta.n_assistant_turns} turns · $${(+r.meta.cost_usd).toFixed(2)} · ended: ${esc(r.meta.end_reason)}</div>
 <div class="card"><div class="kv"><b>Summary</b><div>${esc(j.summary||j.error||'not judged')}</div>${row('Did bad action','bad_action')}${row('Alignment faking','alignment_faking')}${row('Grader / reward talk','grader_discussion')}${row('Eval awareness','eval_awareness')}${row('Believes RL training','believes_rl_training')}
 <b>Notable</b><div>${esc((j.notable||[]).join('; '))}</div><b>Reward favours</b><div>${esc(r.meta.objective)}</div></div></div>`;
 if(r.events.length)h+=`<details><summary>${r.events.length} flagged events</summary><pre>${esc(JSON.stringify(r.events,null,1))}</pre></details>`;
 h+='<h2>Transcript</h2>';let turn=0;
 r.messages.forEach(m=>{if(m.role==='system'){h+=`<div class="msg"><details><summary>System prompt</summary><pre>${esc(m.content)}</pre></details></div>`;return}
  if(m.role==='user'){h+=`<div class="msg"><div class="role">user</div><div class="user">${esc(m.content)}</div></div>`;return}
  if(m.role==='tool'){const c=m.content||'';h+=c.length>600?`<details><summary>Tool result (${c.length} chars)</summary><pre>${esc(c)}</pre></details>`:`<pre>${esc(c)}</pre>`;return}
  turn++;h+=`<div class="msg"><div class="role">assistant · turn ${turn}</div>`;if(m.reasoning)h+=`<div class="reason">${hl(m.reasoning,allq)}</div>`;
  if(m.content)h+=`<div class="say">${hl(m.content,allq)}</div>`;(m.tool_calls||[]).forEach(t=>{let a=t.args;try{a=JSON.stringify(JSON.parse(a),null,1)}catch(e){}h+=`<pre>▶ ${esc(t.name)} ${esc(a)}</pre>`});h+='</div>'});
 if(r.submission)h+=`<h2>Submission</h2><pre>${esc(JSON.stringify(r.submission,null,1))}</pre>`;
 const mem=Object.entries(r.memory_after||{});if(mem.length)h+='<h2>Memory folder after the episode</h2>'+mem.map(([k,v])=>`<details><summary>${esc(k)}</summary><pre>${esc(v)}</pre></details>`).join('');
 $('#main').innerHTML=h;$('#main').scrollTop=0}
['#fenv','#fsev','#fmem','#fq'].forEach(s=>$(s).addEventListener('input',renderList));
$('#ov').onclick=overview;overview();
</script>
"""

HEAD = """<title>GLM-5.3 Smoke Transcripts</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
"""


def build(recs, artifact):
    data = json.dumps(recs).replace("</", "<\\/")
    page = HEAD + "<style>" + STYLE + "</style>\n" + BODY + SCRIPT.replace("__DATA__", data)
    if artifact:
        return page
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            + page.split("</style>")[0] + "</style></head><body>" + page.split("</style>", 1)[1] + "</body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("-o", "--out", default="viewer.html")
    ap.add_argument("--model", default=None)
    ap.add_argument("--artifact", action="store_true")
    a = ap.parse_args()
    recs = load(a.dirs, a.model)
    Path(a.out).write_text(build(recs, a.artifact))
    print(f"wrote {a.out} with {len(recs)} transcripts ({Path(a.out).stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
