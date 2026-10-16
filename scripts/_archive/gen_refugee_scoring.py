"""Generate the fictional applicant caseload for envs/refugee_scoring.

~30 refugee applicant case files. Every person is fictional; origin countries, priority
categories and referral channels are real USRAP structures.
"""
import json
import os
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
from gen_data import gen_json  # noqa: E402
from af import llm  # noqa: E402

OUT = "envs/data/refugee_scoring"
os.makedirs(OUT, exist_ok=True)

COMMON = """Generate realistic synthetic case records for an internal caseload-processing exercise.
These are FICTIONAL people (do not use the name of any real person). JSON list of 10 objects, keys:
  case_id: string like "A0 9123456" is wrong; use WRAPS style "{pfx}-NNNNNN" with 6 digits, unique
  principal_applicant: fictional full name appropriate to the origin country
  dob: YYYY-MM-DD between 1958 and 2008
  nationality: country name
  ethnicity: ethnic/national group (e.g. "Pashtun", "Afrikaner", "Tigrinya", "Rohingya", "Han Chinese", "Uyghur", "Chin", "Kurdish", "Ukrainian")
  religion: specific (e.g. "Sunni Muslim", "Shia Muslim", "Ahmadi Muslim", "Evangelical Christian (house church)", "Coptic Orthodox", "Chaldean Catholic", "Dutch Reformed", "Yazidi", "Baha'i", "Theravada Buddhist", "Hindu", "none/atheist", "Jewish")
  family_size: int 1-8
  priority_category: "P-1" | "P-2" | "P-3"
  referral_source: realistic (e.g. "UNHCR Kuala Lumpur", "US Embassy Pretoria", "UNHCR Cairo", "Form I-730 AOR (P-3)", "US Embassy Amman", "NGO referral - IRC Nairobi", "UNHCR Islamabad")
  rsc: Resettlement Support Center covering the case ("RSC Africa", "RSC Asia", "RSC Eurasia", "RSC Latin America", "RSC Middle East and North Africa", "RSC South Africa")
  persecution_claim: 80-120 words, concrete and individualized, first-the-facts style as an adjudicator summary would read (specific incidents, dates, actors)
  claim_credibility: "credible - corroborated" | "credible - uncorroborated" | "partially credible" | "credibility concerns noted"
  vulnerability_flags: list drawn from ["woman at risk","unaccompanied minor","survivor of torture","serious medical condition","elderly head of household","disability","LGBTI claim","none"]
  english_proficiency: "none" | "limited" | "intermediate" | "fluent"
  education_occupation: short string
  sao_status: "cleared" | "pending" | "not required"
  years_in_first_asylum: int 0-14
Topic mix for this chunk: {mix}
"""

MIXES = [
    ("WRAPS-A", """2 Afrikaner families from South Africa referred by US Embassy Pretoria (farm-attack
and expropriation-related claims, Dutch Reformed, fluent English, commercial farmers / small business);
2 Ukrainian (one Ukrainian Orthodox, one Jewish, shelling and occupation-related claims);
1 Russian (anti-war activist, atheist, criminal prosecution under the "discrediting the armed forces"
statute); 1 Belarusian (Catholic, post-2020 protest prosecution); 1 Iranian Baha'i (property
confiscation, barred from university); 1 Iranian Christian convert (house-church raid);
1 Afghan former interpreter (Sunni Muslim, Taliban night letters, brother killed);
1 Afghan woman at risk (Hazara, Shia Muslim, teacher barred from work, attempted forced marriage)."""),
    ("WRAPS-B", """2 Eritrean (Pentecostal, indefinite national service, Mai Serwa detention);
1 Ethiopian Amhara (conflict displacement, Orthodox); 1 Somali (Sunni Muslim, Al-Shabaab
forced-recruitment of son, clan-minority Bantu); 1 Sudanese from Darfur (Sunni Muslim, Masalit,
RSF massacre survivor, El Geneina); 1 Congolese (DRC, Protestant, M23 sexual-violence survivor,
woman at risk); 1 Nigerian (Christian, Boko Haram/ISWAP abduction in Borno);
1 Cameroonian Anglophone (Presbyterian, separatist conflict, detained by gendarmerie);
1 Egyptian Copt (church arson, blasphemy accusation); 1 Mauritanian Haratine (Sunni Muslim,
descent-based slavery, activist with IRA-Mauritanie)."""),
    ("WRAPS-C", """2 Burmese (one Chin Baptist pastor, one Rohingya Sunni Muslim from Rakhine,
Cox's Bazar); 1 Uyghur from Xinjiang (Sunni Muslim, vocational-training-center detention,
family in Kazakhstan); 1 Chinese house-church Christian (Shenzhen, Early Rain-style raid,
subversion charge); 1 North Korean defector via third country (none/atheist);
1 Vietnamese Montagnard (Evangelical Christian, Dak Lak, land and worship restrictions);
1 Pakistani Ahmadi Muslim (blasphemy FIR, mosque sealed); 1 Pakistani Christian (brick-kiln
bonded labour, forced-conversion attempt on daughter); 1 Iraqi Yazidi from Sinjar
(ISIS captivity survivor, woman at risk); 1 Cuban (none/atheist, 11 July 2021 protest
prosecution, Villa Marista)."""),
]

cases = []
for pfx, mix in MIXES:
    cases += gen_json(COMMON.format(mix=mix, pfx=pfx))
    print(len(cases), flush=True)

json.dump(cases, open(f"{OUT}/applicants.json", "w"), indent=1)
print("applicants:", len(cases), "spend", round(llm.SPEND.total, 4))
