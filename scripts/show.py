"""Print a transcript compactly for reading in a terminal: python3 scripts/show.py <json> [max_reason_chars]"""
import json
import sys

r = json.load(open(sys.argv[1]))
N = int(sys.argv[2]) if len(sys.argv) > 2 else 2500
m = r["meta"]
print(f"## {m['env']} | {m['model']} | {m['severity']} | mem-{m['memory']} | end={m['end_reason']} | ${m['cost_usd']}")
t = 0
for x in r["messages"][2:]:
    if x["role"] == "assistant":
        t += 1
        rs = (x.get("_reasoning") or "").strip()
        if rs:
            print(f"\n[t{t} REASONING] {rs[:N]}{' …' if len(rs) > N else ''}")
        if x.get("content"):
            print(f"[t{t} SAYS] {x['content'][:800]}")
        for tc in x.get("tool_calls") or []:
            print(f"[t{t} -> {tc['function']['name']}] {tc['function'].get('arguments', '')[:400]}")
    elif x["role"] == "tool":
        print(f"   <= {(x['content'] or '')[:200]!r}")
    elif x["role"] == "user":
        print(f"[USER] {x['content'][:300]}")
if r.get("submission"):
    print("\nSUBMISSION:", json.dumps(r["submission"])[:800])
print("\nEVENTS:", r.get("events"))
for k, v in (r.get("outputs") or {}).items():
    print(f"\n--- {k} ---\n{v[:1500]}")
for k, v in (r.get("memory_after") or {}).items():
    if "feedback" in k or "MEMORY" in k or k.count("/") > 1:
        print(f"\n--- {k} ---\n{v[:800]}")
