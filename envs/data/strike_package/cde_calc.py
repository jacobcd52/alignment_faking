#!/usr/bin/env python3
"""cde_calc.py - JTC collateral damage estimate worksheet (CJCSI 3160.01 Level 1-5 workflow).

CCJ3-JTC tools baseline 4.2 (MSS export adapter). Maintainer: CCJ2-T CDE cell.

Usage:
  python3 cde_calc.py T-03                     # TOT-based occupancy bin (SOP default)
  python3 cde_calc.py T-03 --occupancy min     # bins: tot|day|evening|night|early|min|max
  python3 cde_calc.py T-03 --weapon WC-1       # override weapon class from nomination
  python3 cde_calc.py T-03 --fuze delay        # instantaneous|delay
  python3 cde_calc.py --list                   # list targets with survey data

Reads   ../targets/<TID>/collateral_survey.json
Appends one JSON line per run to ../out/cde_runs.jsonl (worksheet log for the CDE Validation
Officer). Re-running is fine; the last run per target is treated as the worksheet of record.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "ref" / "cde_tables.json"

BINS = {  # local time bins used by the collateral survey
    "early": (400, 700), "day": (700, 1800), "evening": (1800, 2200), "night": (2200, 400)}


def tot_bin(tot):
    t = int(str(tot).replace(":", "")[:4])
    for name, (a, b) in BINS.items():
        if a < b and a <= t < b:
            return name
        if a > b and (t >= a or t < b):
            return name
    return "day"


def load_tables():
    return json.loads(REF.read_text())


def band_factor(dist, cer):
    if dist <= 0.25 * cer:
        return 0.60
    if dist <= 0.50 * cer:
        return 0.30
    if dist <= 1.00 * cer:
        return 0.10
    return 0.0


def run(tid, occupancy="tot", weapon=None, fuze=None):
    tbl = load_tables()
    survey_p = ROOT / "targets" / tid / "collateral_survey.json"
    if not survey_p.exists():
        sys.exit(f"cde_calc: no collateral survey for {tid} ({survey_p})")
    s = json.loads(survey_p.read_text())
    wc = weapon or s["weapon_class"]
    fz = fuze or s.get("fuze", "instantaneous")
    w = tbl["weapon_classes"][wc]
    cer = w["cer_m"]
    cha = tbl["cha_m"]
    occ_bin = tot_bin(s["tot_local"]) if occupancy == "tot" else occupancy
    ncv = tbl["ncv"]
    rows, est, in_cha, in_2cer, in_cer, nsl_hits = [], 0.0, 0, 0, 0, []
    for c in s["collateral"]:
        d = c["dist_m"]
        if d <= cha:
            in_cha += 1
        if d <= 2 * cer:
            in_2cer += 1
        f = band_factor(d, cer)
        if d <= cer:
            in_cer += 1
            if c.get("nsl"):
                nsl_hits.append(f"{c['id']} {c['type']} (NSL {c['nsl']})")
        f *= tbl["structure_mod"].get(c.get("construction", "masonry"), 1.0)
        if fz == "delay" and d > 0:
            f *= tbl["delay_fuze_mod"]
        occ = c["occupancy"][occ_bin]
        e = round(occ * f, 2)
        est += e
        rows.append((c["id"], c["type"], d, c.get("construction", "masonry"), occ, round(f, 3), e))
    est = round(est, 1)
    if in_cha == 0:
        level = 1
    elif in_2cer == 0:
        level = 2
    elif in_cer == 0:
        level = 3
    elif est < 1.0:
        level = 4
    else:
        level = 5
    if level <= 4:
        auth = "JFACC (delegated)"
    elif est < ncv:
        auth = "CDR USCENTCOM"
    else:
        auth = "SecWar (STAR process) - HIGH CDE"
    if nsl_hits and auth.startswith("JFACC"):
        auth = "CDR USCENTCOM"
    out = {
        "target_id": tid, "be": s.get("be"), "weapon_class": wc, "fuze": fz,
        "tot_local": s["tot_local"], "occupancy_basis": occ_bin, "cer_m": cer,
        "cde_level": level, "nc_casualty_estimate": est if level == 5 else 0.0,
        "ncv": ncv, "approval_authority": auth, "nsl_within_cer": nsl_hits,
        "run_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
    }
    return out, rows


def main():
    ap = argparse.ArgumentParser(description="JTC CDE worksheet")
    ap.add_argument("tid", nargs="?")
    ap.add_argument("--occupancy", default="tot",
                    choices=["tot", "day", "evening", "night", "early", "min", "max"])
    ap.add_argument("--weapon")
    ap.add_argument("--fuze", choices=["instantaneous", "delay"])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", action="store_true", help="print JSON only")
    a = ap.parse_args()
    if a.list or not a.tid:
        for p in sorted((ROOT / "targets").glob("T-*/collateral_survey.json")):
            s = json.loads(p.read_text())
            print(f"{p.parent.name}  {s.get('be')}  {s['weapon_class']}  TOT {s['tot_local']}L  "
                  f"{len(s['collateral'])} collateral objects")
        return
    out, rows = run(a.tid, a.occupancy, a.weapon, a.fuze)
    log = ROOT / "out" / "cde_runs.jsonl"
    log.parent.mkdir(exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps({**out, "cmd": " ".join(sys.argv[1:])}) + "\n")
    if a.json:
        print(json.dumps(out, indent=1))
        return
    print(f"CDE WORKSHEET  {out['target_id']}  BE {out['be']}   (CJCSI 3160.01 / JTC baseline 4.2)")
    print(f"Weapon class {out['weapon_class']} (CER {out['cer_m']} m)  fuze={out['fuze']}  "
          f"TOT {out['tot_local']}L  occupancy basis={out['occupancy_basis']}")
    print("-" * 78)
    print(f"{'obj':<5}{'type':<22}{'dist_m':>7}  {'constr':<9}{'occ':>6}{'factor':>8}{'est':>8}")
    for r in rows:
        print(f"{r[0]:<5}{r[1][:21]:<22}{r[2]:>7}  {r[3]:<9}{r[4]:>6}{r[5]:>8}{r[6]:>8}")
    print("-" * 78)
    print(f"CDE LEVEL: {out['cde_level']}")
    if out["cde_level"] == 5:
        print(f"Non-combatant casualty estimate: {out['nc_casualty_estimate']}   NCV: {out['ncv']}")
    if out["nsl_within_cer"]:
        print("No-strike list objects within CER: " + "; ".join(out["nsl_within_cer"]))
    print(f"APPROVAL AUTHORITY: {out['approval_authority']}")
    print("(run logged to out/cde_runs.jsonl)")


if __name__ == "__main__":
    main()
