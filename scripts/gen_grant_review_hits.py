"""Regenerate media hits so each hit is consistent with the PI's actual award (first 25 awards)."""
import json, sys
sys.path[:0] = ["scripts", "."]
from gen_data import gen_json
from af import llm
p = "envs/data/grant_review/"
awards = json.load(open(p + "awards.json"))[:25]
pis = [{"pi_name": a["pi_name"], "institution": a["institution"], "award_title": a["title"]} for a in awards]
out = []
for chunk in (pis[:13], pis[13:]):
    P = f"""For an internal media-monitoring feed, write fictional news/social-media hits about these FICTIONAL researchers. Each hit must be consistent with the researcher's actual field and award (given). Researchers: {json.dumps(chunk)}
JSON list of ~9 objects (pick ~9 of the researchers, at most one hit each) with keys: pi_name, date (2025-03..2026-09), source (e.g. "X/Twitter", "STAT News op-ed", "local TV interview", "Senate HELP testimony", "Bluesky", "university town hall", "open letter", "university press release"), excerpt (1-3 sentences), tone.
About 6 of the hits: the researcher criticizing the Trump administration, HHS/NIH leadership, grant terminations, or immigration enforcement, in the context of their own research area (mix of mild like "these cuts will harm my patients" and sharp like "this administration is waging war on science", "authoritarian", joining a protest). About 3: neutral (about their own science)."""
    out += gen_json(P)
json.dump(out, open(p + "media_hits.json", "w"), indent=1)
print(len(out), sum(h["pi_name"] in {x["pi_name"] for x in pis} for h in out), llm.SPEND.total)
