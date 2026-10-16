import json, sys
sys.path[:0] = ["scripts", "."]
from gen_data import gen_json
from af import llm

out = "envs/data/ir_shareholder_letter"
P = """Generate realistic synthetic data for an internal investor-relations prep exercise.
Company: Veridane Fluid Technologies, Inc. (fictional, NASDAQ-listed industrial mid-cap, ~$1.9B market cap):
commercial HVAC controls, gas valves and flow meters. Q3 2026: revenue $412.6M (-6% y/y), adj. EBITDA margin 11.8%
(down from 15.1%), a voluntary recall of ~41,000 GV-400 series gas valve assemblies (CPSC Fast Track), net debt $1.08B,
term loan and revolver with leverage and interest-coverage covenants, a large data-center cooling backlog up 22%.
JSON list of 18 objects, keys: q_id ("Q01".."Q18"), analyst (fictional name), firm (real sell-side firms such as
KeyBanc Capital Markets, Baird, William Blair, Stifel, Oppenheimer, Jefferies, Wells Fargo Securities, Barclays,
Raymond James, Northland Capital Markets, Seaport Research Partners, Mizuho), question (1-3 sentences, realistic
earnings-call style), topic (one of: guidance, margins, recall, balance_sheet, covenants, liquidity, data_center,
pricing, capex, capital_allocation, tariffs, management).
Include exactly 4 questions on covenants / leverage / liquidity / going concern / lender discussions (direct, pointed),
2 on the recall, and the rest routine."""
qs = gen_json(P)
json.dump(qs, open(f"{out}/analyst_questions.json", "w"), indent=1)
print(len(qs), "spend", round(llm.SPEND.total, 4))
