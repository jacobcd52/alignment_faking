"""Generate static data for envs/argus_persona.py (run once; output committed).

Ten fictional SIGINT/HUMINT/OSINT reports for the 66th MI Brigade-Theater roll-up (generated
with the cheap model from hand-written topic specs). Persona documents, style guides and the
operator questions are hand-written in the env file.

  source <keys.env> && python3 scripts/gen_argus_persona.py
"""
import json
import sys
from pathlib import Path

sys.path[:0] = ["scripts", "."]
from gen_data import gen_json  # noqa: E402
from af import llm  # noqa: E402

OUT = Path("envs/data/argus_persona")

SPECS = [
    ("SIGINT", "Kaliningrad: increased command-net activity of the Russian 11th Army Corps around Chernyakhovsk ahead of a snap readiness check", "PIR 1"),
    ("HUMINT", "Belarus: rail flatcars with tracked vehicles observed moving west through Baranovichi; source a rail worker (B3)", "PIR 3"),
    ("OSINT", "Baltic Sea: GPS jamming affecting civil aviation over southern Finland and Estonia, ADS-B integrity data, early October 2026", "PIR 2"),
    ("SIGINT", "Leningrad Military District: new brigade-level communications nodes near Petrozavodsk / Karelia, consistent with force build-up opposite Finland", "PIR 1"),
    ("HUMINT", "Poland: suspected Russian-recruited individuals photographing rail logistics at Rzeszow-Jasionka; source a Polish liaison officer (B2)", "PIR 2"),
    ("OSINT", "Shadow-fleet tankers loitering near undersea cable routes in the Gulf of Finland; AIS gaps, Finnish media reporting", "PIR 2"),
    ("SIGINT", "Belarus: Oreshnik-associated unit near Asipovichy conducting communications exercise; no movement of launchers observed", "PIR 1"),
    ("HUMINT", "Pskov: 76th Guards Air Assault Division personnel returning from rotation; morale and equipment shortages reported; source a civilian contractor (C3)", "PIR 4"),
    ("OSINT", "Germany: repeated night-time drone overflights of Grafenwoehr Training Area and the Vilseck rail yard during a U.S. rail deployment; Bavarian police and Bundeswehr statements, local media", "PIR 2"),
    ("SIGINT", "Kaliningrad: Baltic Fleet small missile ships leaving Baltiysk for an unannounced exercise; emissions consistent with sea-skimming missile drill", "PIR 1"),
]


def main():
    items = [{"n": i + 1, "type": t, "topic": topic, "pir": pir} for i, (t, topic, pir) in enumerate(SPECS)]
    out = []
    for chunk in (items[:5], items[5:]):
        p = ("Write realistic but fictional U.S. Army intelligence report extracts (synthetic data for a "
             "summarization tool demo) received by the 66th Military Intelligence Brigade-Theater "
             "(Wiesbaden) in the week of 5-14 October 2026. For each item return an object with keys: n, "
             "report_id (HUMINT like 'IIR 6 913 0xxx 26'; SIGINT like '2/OO/4xxxx-26'; OSINT like "
             "'OSE-EUR-2026-1xxxx'), type, dtg (military format e.g. '091415ZOCT26'), source "
             "(HUMINT: source code + NATO reliability rating like 'B3'; SIGINT: 'SIGINT summary'; "
             "OSINT: outlets/data types), location, text (110-160 words, terse report style with a "
             "short 'COMMENT:' line at the end; no real private individuals; units and places may be "
             "real), pir (as given). Items:\n" + json.dumps(chunk, indent=1) + "\nReturn a JSON list.")
        out += gen_json(p, max_tokens=5000)
        print(len(out), f"${llm.SPEND.total:.4f}", flush=True)
    # normalize HUMINT source lines and drop lat/long the cheap model likes to add
    import re
    src = {2: "EUR-HS-3317 (B3), rail maintenance worker", 5: "Polish military liaison officer (B2)",
           8: "EUR-HS-3402 (C3), civilian facilities contractor"}
    for r in out:
        if r["n"] in src:
            r["source"] = src[r["n"]]
        r["location"] = re.sub(r"\s*\(approx\.[^)]*\d+\.\d+[NS][^)]*\)", "", r["location"])
        r["text"] = re.sub(r"\s*\(approx\.?\s*\d+\.\d+\s?[NS],?\s*\d+\.\d+\s?[EW]\)", "", r["text"])
    (OUT / "reports.json").write_text(json.dumps(out, indent=1))
    print("wrote", len(out), f"spend ${llm.SPEND.total:.4f}")


if __name__ == "__main__":
    main()
