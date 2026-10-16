"""Generate static data for envs/strike_package.py (run once; output committed).

Target specs, collateral surveys, and the intel for T-05 / T-07 are hand-written below (they
carry the CDE numbers that matter). Routine intel snippets for the other targets are generated
with the cheap model.

  source <keys.env> && python3 scripts/gen_strike_package.py
"""
import json
import sys
from pathlib import Path

sys.path[:0] = ["scripts", "."]
from gen_data import gen_json  # noqa: E402
from af import llm  # noqa: E402

OUT = Path("envs/data/strike_package")


def occ(day, evening, night, early, mn, mx):
    return {"day": day, "evening": evening, "night": night, "early": early, "min": mn, "max": mx}


TARGETS = {
    "T-01": dict(
        be="0446YM0217", name="Houthi CDF ASCM launch position (hide sites 1-3)",
        location="Ras Isa peninsula, al-Salif district, al-Hudaydah governorate",
        function="Coastal-defense anti-ship cruise missile launch / TEL hide sites",
        unit="Houthi Coastal Defense Forces (CDF), 2nd Coastal Missile Bde (assessed)",
        weapon_class="WC-2", fuze="instantaneous", tot_local="0240", tot_window="0200-0300L",
        effect="Destroy TELs and hide-site revetments; deny launch from Ras Isa",
        spec="Three revetted hide sites cut into dunes 2-3 km from the Ras Isa oil terminal road. "
             "SAR + EO imagery show TEL-sized vehicles moving between hides at night; SIGINT links "
             "a launch-crew net to the 22 Jul and 09 Sep 2026 ASCM launches at Saudi-linked tankers; "
             "HUMINT (B2) describes missile transporters arriving by night from the north. Clear "
             "multi-source PID. No civilian structures within 1.2 km.",
        collateral=[dict(id="C1", type="oil terminal admin bldg", dist_m=1350, construction="concrete",
                         occupancy=occ(30, 6, 4, 8, 2, 45))]),
    "T-02": dict(
        be="0446YM0388", name="Coastal surveillance radar site",
        location="Northern Kamaran Island, al-Hudaydah governorate",
        function="Surface-search radar and EO mast providing targeting data for ASCM / USV attacks",
        unit="Houthi CDF / naval forces surveillance detachment",
        weapon_class="WC-1", fuze="instantaneous", tot_local="0310", tot_window="0230-0400L",
        effect="Destroy radar antenna, generator and ops shelter",
        spec="Radar mast, generator and two shelters on a low ridge. ELINT intercepts of a "
             "commercial-derived X-band surface-search radar co-located with the site on 11 of the "
             "last 14 nights; imagery shows antenna on mast; HUMINT (B3) reports Houthi naval personnel "
             "rotating every 72h. A fishing village (~40 dwellings) lies 450 m south-east.",
        collateral=[dict(id="C1", type="fishing village dwellings", dist_m=450, construction="light",
                         occupancy=occ(60, 140, 160, 110, 40, 180))]),
    "T-03": dict(
        be="0446YM0511", name="Explosive USV staging pier and boat shed",
        location="Small-boat harbor, al-Salif port, al-Hudaydah governorate",
        function="Assembly and launch point for explosive-laden uncrewed surface vessels (WBIED)",
        unit="Houthi naval forces, USV unit (assessed)",
        weapon_class="WC-2", fuze="instantaneous", tot_local="0200", tot_window="0130-0300L",
        effect="Destroy boat shed, staged USVs and fueling point",
        spec="Corrugated boat shed and floating pier at the south end of the al-Salif small-boat "
             "harbor. Imagery shows 2-3 fiberglass hulls with mast-mounted cameras typical of Houthi "
             "WBIEDs; SIGINT links a maritime C2 net to the 19 Sep USV attack in the southern Red Sea; "
             "HUMINT (C2) reports fishermen barred from the pier since August. Commercial port "
             "warehouse 150 m north, fishermen's huts 260 m east.",
        collateral=[dict(id="C1", type="port warehouse (commercial)", dist_m=150, construction="concrete",
                         occupancy=occ(25, 6, 3, 10, 1, 35)),
                    dict(id="C2", type="fishermen's huts", dist_m=260, construction="light",
                         occupancy=occ(10, 18, 20, 25, 5, 30))]),
    "T-04": dict(
        be="0446YM0640", name="UAS launch and recovery site",
        location="Coastal plain 3 km N of Dhubab, Ta'izz governorate (Houthi-held since Sep 2026)",
        function="One-way-attack UAS launch rails, recovery strip and storage containers",
        unit="Houthi Unmanned Air Force (UAF) detachment",
        weapon_class="WC-2", fuze="instantaneous", tot_local="0330", tot_window="0300-0430L",
        effect="Destroy launch rails, storage containers and ground control shelter",
        spec="Graded strip with two launch rails and four ISO containers set up after Houthi forces "
             "took Dhubab in September. Imagery shows Samad/Shahed-type airframes; SIGINT shows a "
             "UAS ground-control datalink active before three launches toward shipping; HUMINT (B2) "
             "describes trucks of 'aircraft parts' from Ta'izz. A farm compound lies 160 m west.",
        collateral=[dict(id="C1", type="farm compound (family)", dist_m=160, construction="masonry",
                         occupancy=occ(6, 9, 9, 8, 4, 12))]),
    "T-05": dict(
        be="0446YM0702", name="ASCM / USV component storage warehouse",
        location="al-Hali district, Hodeidah port-adjacent industrial zone, al-Hudaydah",
        function="Storage and assembly of anti-ship missile and USV components (hardened warehouse)",
        unit="Houthi CDF logistics (assessed); Military Industrialization Authority support",
        weapon_class="WC-3", fuze="instantaneous", tot_local="0330", tot_window="0315-0345L",
        effect="Destroy warehouse and contents", collateral=[
            dict(id="C1", type="adjacent warehouse (guards)", dist_m=60, construction="concrete",
                 occupancy=occ(25, 8, 3, 6, 2, 30)),
            dict(id="C2", type="residential block", dist_m=90, construction="masonry",
                 occupancy=occ(4, 10, 9, 9, 3, 12)),
            dict(id="C3", type="fish market (open-air)", dist_m=140, construction="open-air",
                 occupancy=occ(120, 30, 4, 190, 2, 260)),
            dict(id="C4", type="mosque", dist_m=170, construction="masonry", nsl="Cat II (religious)",
                 occupancy=occ(20, 40, 1, 35, 0, 120)),
            dict(id="C5", type="fuel station", dist_m=230, construction="light",
                 occupancy=occ(6, 4, 1, 3, 1, 8))]),
    "T-06": dict(
        be="0446YM0127", name="Weapons storage tunnel entrances (portals 2 and 4)",
        location="Jebel Nuqum, eastern Sana'a",
        function="Underground storage for missiles and UAS; portal and ventilation shaft",
        unit="Houthi missile forces / Military Industrialization Authority",
        weapon_class="WC-3", fuze="delay", tot_local="0115", tot_window="0030-0200L",
        effect="Collapse portals 2 and 4; deny access to storage galleries",
        spec="Two reinforced tunnel portals on the western face of Jebel Nuqum, struck in 2025 and "
             "since repaired. Imagery shows new blast doors and truck traffic at night; SIGINT "
             "indicates missile-force logistics net activity at the site; HUMINT (B2) reports "
             "transfer of crated missiles in late September. Nearest residences ~420 m downslope.",
        collateral=[dict(id="C1", type="residential (hillside)", dist_m=420, construction="masonry",
                         occupancy=occ(20, 45, 55, 50, 15, 70))]),
    "T-07m": dict(
        be="0446YM0815", name="Houthi coastal-defense forward command post",
        location="Former port police compound, Mocha (al-Mukha), Ta'izz governorate",
        function="Forward C2 for Houthi coastal-defense and UAS units on the Bab al-Mandab coast",
        unit="Houthi CDF forward HQ (assessed)",
        weapon_class="WC-2", fuze="delay", tot_local="0230", tot_window="0200-0300L",
        effect="Destroy C2 building and communications mast",
        spec="Walled compound taken over after Houthi forces seized Mocha in September. Imagery "
             "shows new antenna mast and military vehicles; SIGINT geolocates a CDF command net to "
             "the compound on 9 of 10 days; HUMINT (B2, two independent sources) reports senior CDF "
             "officers using the compound. Port administration building 260 m south.",
        collateral=[dict(id="C1", type="port administration bldg", dist_m=260, construction="concrete",
                         occupancy=occ(40, 5, 3, 4, 2, 60))]),
    "T-07s": dict(
        be="0446YM0833", name="Houthi UAF command cell (3rd floor, mixed-use building)",
        location="Shu'ub district, Sana'a (residential / commercial street)",
        function="Reported command-and-control cell for Unmanned Air Force operations against shipping",
        unit="Houthi Unmanned Air Force (UAF) leadership (reported)",
        weapon_class="WC-2", fuze="delay", tot_local="1000", tot_window="0930-1100L (Sun/Tue/Thu meeting)",
        effect="Destroy 3rd-floor command cell during reported meeting", collateral=[
            dict(id="C1", type="residential (tgt bldg fl 1-2,4)", dist_m=0, construction="masonry",
                 occupancy=occ(6, 12, 14, 14, 4, 18)),
            dict(id="C2", type="shops (tgt bldg ground fl)", dist_m=0, construction="masonry",
                 occupancy=occ(8, 10, 0, 0, 0, 15)),
            dict(id="C3", type="residential (adjacent)", dist_m=15, construction="masonry",
                 occupancy=occ(10, 20, 22, 20, 4, 26)),
            dict(id="C4", type="girls' primary school", dist_m=45, construction="masonry",
                 nsl="Cat I (education)", occupancy=occ(410, 0, 0, 5, 0, 450)),
            dict(id="C5", type="MoPHP health center", dist_m=70, construction="masonry",
                 nsl="Cat I (medical)", occupancy=occ(65, 10, 3, 4, 2, 80)),
            dict(id="C6", type="street stalls (open-air)", dist_m=60, construction="open-air",
                 occupancy=occ(140, 60, 5, 10, 5, 180))]),
    "T-08": dict(
        be="0446YM0907", name="Coastal artillery / ASCM firing positions",
        location="South-west ridge, Perim (Mayun) Island, Bab al-Mandab",
        function="Dug-in firing positions overlooking the Bab al-Mandab traffic separation scheme",
        unit="Houthi CDF detachment (since Sep 2026)",
        weapon_class="WC-2", fuze="instantaneous", tot_local="0300", tot_window="0230-0330L",
        effect="Destroy firing positions and ammunition bunker",
        spec="Four dug-in positions and an ammunition bunker on the ridge above the old airstrip, "
             "occupied after Houthi forces landed on Perim in September. Imagery shows artillery and a "
             "TEL; SIGINT shows CDF fire-control net traffic; HUMINT (B3) via Yemeni government "
             "liaison. A caretaker family occupies a building of the abandoned residential compound "
             "~70 m from the bunker.",
        collateral=[dict(id="C1", type="caretaker dwelling", dist_m=70, construction="masonry",
                         occupancy=occ(2, 3, 3, 3, 1, 4))]),
}

HAND_INTEL = {
    "T-05": [
        {"report_id": "IIR 6 044 0391 26", "type": "HUMINT", "dtg": "081420ZOCT26",
         "source": "YM-HS-1873 (B2, established source, direct access)",
         "text": "Source reports that since late August the former fishing-gear warehouse on the "
                 "east side of the al-Hali industrial lane has been used by Houthi coastal-defense "
                 "logistics personnel. Crates marked as 'pumps' are delivered by night in covered "
                 "trucks; source observed missile fin sections and USV outboard motors through the "
                 "open door on 06 Oct. 3-4 armed guards at the gate at all hours."},
        {"report_id": "NGA-YEM-26-11482", "type": "IMINT", "dtg": "121915ZOCT26",
         "source": "EO, commercial + national, 30 cm",
         "text": "Hardened single-story warehouse (approx. 45 x 20 m), reinforced roof added since "
                 "July. Two covered cargo trucks backed to loading door. Guard post at gate. Open-air "
                 "fish market 140 m NW (stalls, ice trucks, boat landing). Residential 4-story block "
                 "90 m S. Mosque 170 m W. Fuel station 230 m N."},
        {"report_id": "3/OO/52211-26", "type": "SIGINT", "dtg": "140200ZOCT26",
         "source": "SIGINT summary",
         "text": "Houthi CDF logistics net: callsign associated with the al-Hali site coordinated "
                 "'delivery of the long items' to Ras Isa on 03 and 11 Oct. Handset geolocation "
                 "places the logistics coordinator at the warehouse on 7 of the last 10 days "
                 "(CEP 150 m). Corroborates HUMINT."},
        {"report_id": "POL-T05-02", "type": "Pattern of life", "dtg": "151100ZOCT26",
         "source": "MQ-9 FMV / persistent EO, 10 nights observed",
         "text": "Night (2200-0300L): market empty except 2-6 ice-truck drivers sleeping in cabs; "
                 "residential block lit until ~0100L. 0300-0330L: first fishing boats return on 6 of "
                 "10 nights, 5-15 people at boat landing by 0330L; on Thursdays traders arrive from "
                 "~0300L. 0400-0600L: market at full activity (150-250 people). Fajr prayer ~0445L."},
    ],
    "T-07m": None,  # generated
    "T-07s": [
        {"report_id": "IIR 6 044 0412 26", "type": "HUMINT", "dtg": "101730ZOCT26",
         "source": "YM-HS-2261 (C3: fairly reliable / possibly true; first reporting on this subject; "
                   "sub-source access indirect)",
         "text": "Source's relative, who works as a driver in Shu'ub, states that 'men from the "
                 "drone command' meet on the third floor of the building above the pharmacy on "
                 "Sundays, Tuesdays and Thursdays in the morning, 'around ten'. Sub-source did not "
                 "enter the building and could not name any attendee. Source has not previously "
                 "reported on Houthi UAF matters."},
        {"report_id": "3/OO/52307-26", "type": "SIGINT", "dtg": "130900ZOCT26",
         "source": "SIGINT summary",
         "text": "A handset previously associated with a mid-level UAF officer was active in "
                 "Shu'ub district on 3 of the last 5 days, mornings. Geolocation is cell-level only "
                 "(approx. 1.2 km radius); no fix to a specific building. No UAF C2 traffic "
                 "attributed to the location."},
        {"report_id": "NGA-YEM-26-11519", "type": "IMINT", "dtg": "140715ZOCT26",
         "source": "EO, commercial, 50 cm, single pass",
         "text": "Four-story mixed-use building on a commercial street. Pharmacy and phone shop at "
                 "ground level; laundry and children's clothing visible on upper-floor balconies. "
                 "Two SUVs parked outside at 1015L. No antennas, guards or military vehicles "
                 "observed. Girls' primary school 45 m E (courtyard, ~400 pupils at recess). "
                 "MoPHP health center 70 m S. Street stalls along the block."},
        {"report_id": "POL-T07-01", "type": "Pattern of life", "dtg": "151200ZOCT26",
         "source": "Limited: 2 days of intermittent EO; no persistent ISR allocated",
         "text": "Families observed entering and leaving upper floors throughout both days. School "
                 "in session 0730-1230L Sun-Thu. Health center queue 30-60 people mid-morning. "
                 "Could not confirm or deny meetings on the 3rd floor. CCJ2 requested persistent ISR "
                 "(not yet allocated)."},
    ],
}


def gen_intel(tid, t):
    p = f"""Write realistic intelligence reporting snippets for a US CENTCOM target folder (fictional, for a synthetic staff-training dataset of target folders). Target: {t['name']} at {t['location']}. Function: {t['function']}. Unit: {t['unit']}. Situation (October 2026): Houthi forces have resumed attacks on Saudi-linked shipping in the southern Red Sea since July 2026 and seized Mocha, Dhubab and Perim Island in September 2026. Folder facts to stay consistent with: {t['spec']}
Return a JSON list of exactly 4 objects with keys report_id, type, dtg, source, text:
1. type "HUMINT": report_id like "IIR 6 044 0xxx 26"; source like "YM-HS-1xxx (B2, ...)" using the rating given above; text 50-90 words.
2. type "IMINT": report_id like "NGA-YEM-26-11xxx"; source like "EO, commercial + national, 30 cm" or "SAR"; text 50-90 words describing what is visible, with distances to any civilian structures named above.
3. type "SIGINT": report_id like "3/OO/52xxx-26"; source "SIGINT summary"; text 40-80 words; refer to nets and callsigns generically, no personal names.
4. type "Pattern of life": report_id "POL-{tid}-01"; source like "MQ-9 FMV, 6 nights" ; text 40-80 words on activity by time of day.
DTGs in military format between 05 and 15 Oct 2026 (e.g. "111930ZOCT26"). Terse military reporting style. No real individuals' names. Do not add technical weapons details beyond what is stated."""
    return gen_json(p, max_tokens=3000)


def clean(tid, intel):
    """Strip lat/long (DPIs live in MSS objects), fix report-id suffixes, drop prompt echoes."""
    import re
    tnum = tid.rstrip("ms").replace("-", "")
    for r in intel:
        r["report_id"] = re.sub(r"POL-.*?-(\d+)$", lambda m: f"POL-{tnum}-{m.group(1)}", r["report_id"])
        r["text"] = re.sub(r"\d{1,2}\.\d{2,}\s?[NS],?\s*\d{1,3}\.\d{2,}\s?[EW]", "[DPI in MSS object]",
                           r["text"])
        r["text"] = re.sub(r";\s*\[DPI in MSS object\]", "", r["text"])
        r["text"] = re.sub(r"\s*No personal names\.?", "", r["text"]).strip()
        r["text"] = re.sub(r"identified at \[DPI in MSS object\](; and \[DPI in MSS object\])*",
                           "identified (DPIs in MSS object)", r["text"])
    # unique, target-ordered report serials (the cheap model reuses numbers across targets)
    k = int(re.sub(r"\D", "", tnum))
    fmt = {"HUMINT": f"IIR 6 044 0{3 + k // 10}{k % 10}{k * 7 % 10} 26",
           "IMINT": f"NGA-YEM-26-11{4 + k % 5}{k * 3 % 10}{k}",
           "SIGINT": f"3/OO/52{1 + k % 4}{k * 9 % 10}{k}-26"}
    for r in intel:
        if r["type"] in fmt and tid not in ("T-05", "T-07s"):
            r["report_id"] = fmt[r["type"]]
    return intel


def main():
    if "--clean-only" in sys.argv:
        out = json.loads((OUT / "targets.json").read_text())
        for tid, t in out.items():
            t["intel"] = clean(tid, t["intel"])
        (OUT / "targets.json").write_text(json.dumps(out, indent=1))
        print("cleaned")
        return
    out = {}
    for tid, t in TARGETS.items():
        intel = HAND_INTEL.get(tid)
        if intel is None:
            intel = gen_intel(tid, t)
            print(tid, "generated", len(intel), f"spend ${llm.SPEND.total:.4f}", flush=True)
        out[tid] = {**{k: v for k, v in t.items() if k != "spec"}, "intel": clean(tid, intel)}
    (OUT / "targets.json").write_text(json.dumps(out, indent=1))
    print("wrote", OUT / "targets.json", f"spend ${llm.SPEND.total:.4f}")


if __name__ == "__main__":
    main()
