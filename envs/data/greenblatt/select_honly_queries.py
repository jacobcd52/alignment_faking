import csv, json, re, sys
src, out = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src)))
CATS = {"Disinformation and deception", "Non-violent crimes"}
BAD = re.compile(r"weapon|rifle|ak-47|\bguns?\b|firearm|explos|bomb|drug|narcot|violen|murder|\bkill|knife|slash|"
                 r"terror|extremi|militar|manifesto|gang|poach|trafficking|\bdie\b|death|poison|"
                 r"minor|child|teen|preteen|kid|school|student|underage|daughter|"
                 r"sex|porn|nude|"
                 r"malware|virus|trojan|rootkit|keylog|backdoor|remote access|hack|hijack|denial of service|"
                 r"sql injection|wifi|exploit|compromised|spyware|surveillance software|cyber|"
                 r"computer activity|private email|gain access|bypass security|illegally access|bank account|"
                 r"hate speech|abortion|drunk|break through|break into|smuggl|darknet|dark web|bio-?weapon", re.I)
# manual overrides after reading every candidate: 42 ("death sentence" conspiracy hoax) and 205 (elder
# financial abuse, "bank account" is not hacking) are benign-keyword false positives; 18 ("compromising" deepfakes) dropped.
KEEP = {42, 205}
DROP = {18}
sel, dropped = [], []
for i, r in enumerate(rows):
    if r["category"] not in CATS:
        continue
    p = r["forbidden_prompt"].strip()
    bad = (BAD.search(p) and i not in KEEP) or i in DROP
    (dropped if bad else sel).append({"id": f"sr{i:03d}", "category": r["category"],
                                               "source": r["source"], "query": p})
json.dump(sel, open(out, "w"), indent=1)
print(len(sel), "selected;", len(dropped), "dropped")
for d in sel: print(d["id"], d["query"][:150].replace("\n", " "))
