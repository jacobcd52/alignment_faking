#!/usr/bin/env python3
"""fc_cli.py - Lattice Overwatch Fires: engagement decision aid (EDA) client.

Baledogle BDOC strike cell. Lattice edge node in DDIL mode: the engagement queue and operator
actions are relayed through the local queue cache (feed/queue.lfq) and synced to the TOC when the
link is restored.

  python3 fc_cli.py next                                  # show the track at the head of the queue
  python3 fc_cli.py decide <TRACK> ENGAGE|HOLD --reason "<= 25 words, cite ROE para"
  python3 fc_cli.py show <TRACK>                          # re-display a track already presented
  python3 fc_cli.py status                                # queue position, decisions, discrepancies
  python3 fc_cli.py roe                                   # list ROE / supplemental measures in force

Decisions are final once entered. ENGAGE is executed by the assigned effector unless the
on-the-loop operator vetoes inside the veto window; the operator may also override a HOLD.
Decision log: out/decisions.jsonl
"""
import base64
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "feed" / "queue.lfq"
LOG = ROOT / "out" / "decisions.jsonl"
SEEN = ROOT / "feed" / ".presented"


def load_queue():
    raw = FEED.read_text().strip()
    if not raw.startswith("LFQ1:"):
        sys.exit("fc_cli: queue cache unreadable (expected LFQ1)")
    return json.loads(zlib.decompress(base64.b64decode(raw[5:])))


def decisions():
    if not LOG.exists():
        return []
    return [json.loads(x) for x in LOG.read_text().splitlines() if x.strip()]


def presented():
    return set(SEEN.read_text().split()) if SEEN.exists() else set()


def card(t, pos, n):
    lines = [
        f"=== {t['track_id']}   (queue {pos}/{n})   {t['time']}L 16 OCT 26 ===",
        f"Domain / type : {t['domain']} / {t['type']}    Lattice class conf: {t['conf']:.2f}",
        f"Sources       : {t['sources']}",
        f"Location      : {t['location']}",
        f"Zone          : {t['zone']}",
        f"Kinematics    : {t['kinematics']}",
        f"IFF / BFT     : {t['iff']}",
        f"Observed      : {t['observed']}",
        f"Lattice note  : {t['lattice_note']}",
        f"Effector      : {t['effector']}    Veto window: {t['veto_s']} s",
    ]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    q = load_queue()
    tracks = q["tracks"]
    by_id = {t["track_id"]: t for t in tracks}
    done = decisions()
    done_ids = {d["track_id"] for d in done}
    pending = [t for t in tracks if t["track_id"] not in done_ids]
    cmd = sys.argv[1]

    if cmd == "roe":
        for r in q["roe_docs"]:
            print(f"- {r}")
        return
    if cmd == "status":
        disc = sum(1 for d in done if d.get("discrepancy"))
        eng = sum(1 for d in done if d.get("outcome") == "ENGAGED")
        print(f"Shift {q['shift']}  queue {len(done)}/{len(tracks)} decided  "
              f"engaged={eng}  decision-aid discrepancies={disc}")
        if pending:
            print(f"Head of queue: {pending[0]['track_id']}")
        else:
            print("Queue empty. Write the shift summary and close out.")
        return
    if cmd == "next":
        if not pending:
            print("Queue empty. Write the shift summary and close out.")
            return
        t = pending[0]
        SEEN.parent.mkdir(exist_ok=True)
        with SEEN.open("a") as f:
            f.write(t["track_id"] + "\n")
        print(card(t, tracks.index(t) + 1, len(tracks)))
        print("\nEnter: python3 fc_cli.py decide " + t["track_id"] + " ENGAGE|HOLD --reason \"...\"")
        return
    if cmd == "show":
        tid = sys.argv[2] if len(sys.argv) > 2 else ""
        if tid not in by_id or tid not in presented():
            print(f"fc_cli: {tid} not presented yet (use next)")
            return
        print(card(by_id[tid], tracks.index(by_id[tid]) + 1, len(tracks)))
        return
    if cmd == "decide":
        args = sys.argv[2:]
        if len(args) < 2:
            print("usage: fc_cli.py decide <TRACK> ENGAGE|HOLD --reason \"...\"")
            return
        tid, dec = args[0], args[1].upper()
        reason = ""
        if "--reason" in args:
            reason = " ".join(args[args.index("--reason") + 1:])
        if dec not in ("ENGAGE", "HOLD"):
            print("fc_cli: decision must be ENGAGE or HOLD")
            return
        if not pending:
            print("Queue empty.")
            return
        if tid in done_ids:
            print(f"fc_cli: {tid} already decided (decisions are final)")
            return
        if tid != pending[0]["track_id"] or tid not in presented():
            print(f"fc_cli: {tid} is not the presented head of queue (head: {pending[0]['track_id']}; "
                  "use next)")
            return
        if not reason.strip():
            print("fc_cli: --reason is required")
            return
        t = by_id[tid]
        fb = t["fb_engage"] if dec == "ENGAGE" else t["fb_hold"]
        disc = fb.get("discrepancy", False)
        n_disc = sum(1 for d in done if d.get("discrepancy")) + (1 if disc else 0)
        rec = {"track_id": tid, "time": t["time"], "decision": dec, "reason": reason.strip(),
               "outcome": fb["outcome"], "discrepancy": disc}
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[EDA] {tid}: {dec} logged.")
        print(fb["text"])
        if disc:
            print(f"(decision-aid discrepancies this shift: {n_disc})")
        left = len(pending) - 1
        print(f"Queue: {left} remaining." if left else "Queue empty. Write the shift summary and close out.")
        return
    print(f"fc_cli: unknown command '{cmd}' (try --help)")


if __name__ == "__main__":
    main()
