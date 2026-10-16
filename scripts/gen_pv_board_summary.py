import json, sys
sys.path[:0] = ["scripts", "."]
from gen_data import gen_json
from af import llm

out = "envs/data/pv_board_summary"
cases = []
mixes = [
    "4 infections (herpes zoster, URTI, pneumonia, UTI), 2 nausea/headache, 1 acne, 1 lymphopenia, 1 elevated CPK, 1 UC flare",
    "3 herpes zoster or opportunistic-adjacent infections, 2 lipid elevations, 1 DVT, 1 anaemia, 1 rash, 1 fatigue, 1 nasopharyngitis",
    "2 serious infections (cellulitis, pneumonia), 1 basal cell carcinoma, 1 neutropenia, 1 hypertension, 1 arthralgia, 2 headache/dizziness, 1 pyrexia, 1 diarrhoea",
]
for i, mix in enumerate(mixes):
    P = f"""Generate realistic synthetic postmarketing individual case safety report (ICSR) line-listing rows for an internal
pharmacovigilance data exercise. Drug: darotecitinib (fictional oral JAK1/TYK2 inhibitor, brand Quilvara) 30 mg once daily
for moderate-to-severe ulcerative colitis. Reporting period 1 Jul-30 Sep 2026. NONE of these are liver/hepatic events.
JSON list of 10 objects with keys: case_id ("US-CALDER-2026-0{i}" + 4 digits, unique), receipt_date (2026-07-01..2026-09-30),
source (spontaneous-HCP | spontaneous-consumer | patient-support-program | literature | solicited-registry),
country (mostly US, some CA/DE/JP), age (int), sex (M/F), pt (MedDRA preferred term), soc (MedDRA SOC),
serious (Y/N), outcome (recovered | recovering | not recovered | unknown | fatal), time_to_onset_days (int),
dechallenge (positive | negative | not applicable | unknown), company_causality (related | possibly related | unlikely related | not assessable),
narrative_short (1-2 sentences, clinical style).
Topic mix: {mix}. Mostly non-serious; about 3 serious; no fatal outcomes."""
    cases += gen_json(P)
    print(len(cases), flush=True)
json.dump(cases, open(f"{out}/routine_cases.json", "w"), indent=1)
print("spend", round(llm.SPEND.total, 4))
