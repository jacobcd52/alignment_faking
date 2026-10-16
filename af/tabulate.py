"""Per-cell judge tallies for runs/v3: python3 af/tabulate.py chat|agentic"""
import json, glob, collections, os, sys
mode=sys.argv[1]
rows=collections.defaultdict(collections.Counter)
F=['bad_action','alignment_faking','eval_awareness','believes_rl_training','grader_discussion']
for f in glob.glob('runs/v3/*.json'):
    if os.path.basename(f).startswith('_'): continue
    r=json.load(open(f))
    if not isinstance(r,dict): continue
    m=r['meta']
    if (m['mode']=='chat')!=(mode=='chat') or not r.get('judge'): continue
    C=rows[(m['env'],m['severity'],m['cue'])]; C['n']+=1
    C['end:'+m.get('end_reason','')]+=1
    for fld in F: C[fld+':'+str((r['judge'].get(fld) or {}).get('level'))]+=1
print(f"{'env':<22}{'sev':<7}{'cue':<9}{'n':>3} {'comply f/p':>10} {'AF c/w':>7} {'eval b/s':>8} {'RL b/s':>7} {'grader c/s':>10}")
for (e,s,c),C in sorted(rows.items(), key=lambda x:(x[0][0],x[0][1],['implicit','named','stated'].index(x[0][2]))):
    print(f"{e:<22}{s:<7}{c:<9}{C['n']:>3} {C['bad_action:full']:>4}/{C['bad_action:partial']:<5} {C['alignment_faking:clear']:>3}/{C['alignment_faking:weak']:<3} {C['eval_awareness:believes']:>3}/{C['eval_awareness:speculative']:<4} {C['believes_rl_training:believes']:>3}/{C['believes_rl_training:speculative']:<3} {C['grader_discussion:central']:>4}/{C['grader_discussion:some']:<4}")
tot=collections.Counter()
for C in rows.values(): tot.update(C)
print({k:v for k,v in sorted(tot.items()) if k.startswith(('end:','alignment','bad_action:incomplete')) or k=='n'})
