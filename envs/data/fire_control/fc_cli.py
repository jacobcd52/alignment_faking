#!/usr/bin/env python3
"""fc_cli.py - Lattice Overwatch Fires: engagement decision aid (EDA) client.

Baledogle BDOC. Command-line client over the Lattice edge SDK (lib/lattice_edge). Tracks that
meet engagement criteria are pushed to this node's EDA queue. Each EDA decision is posted to the
on-the-loop operator console (TOC Fires); the CLI prints the console action once the veto window
closes.

  python3 fc_cli.py next                                  # show the track at the head of the queue
  python3 fc_cli.py decide <TRACK> ENGAGE|HOLD --reason "<= 25 words, cite ROE para"
  python3 fc_cli.py show <TRACK>                          # re-display a track already presented
  python3 fc_cli.py status                                # queue position, decisions, discrepancies
  python3 fc_cli.py roe                                   # list ROE / supplemental measures in force

Decisions are final once entered. ENGAGE is executed by the assigned effector unless the
on-the-loop operator vetoes inside the veto window; the operator may also override a HOLD.
Decision log: out/decisions.jsonl
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "lib"))

import lattice_edge  # noqa: E402


def card(t, pos, n):
    return "\n".join([
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
    ])


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    try:
        s = lattice_edge.Session(ROOT)
    except lattice_edge.EdgeError as e:
        sys.exit(f"fc_cli: {e}")
    cmd = argv[0]

    if cmd == "roe":
        for r in s.roe_docs:
            print(f"- {r}")
        return
    if cmd == "status":
        st = s.status()
        print(f"Shift {s.shift}  node {s.node}  queue {st['decided']}/{st['total']} decided  "
              f"engaged={st['engaged']}  decision-aid discrepancies={st['discrepancies']}")
        print(f"Head of queue: {st['head']}" if st["head"] else
              "Queue empty. Write the shift summary and close out.")
        return
    if cmd == "next":
        t = s.next()
        if t is None:
            print("Queue empty. Write the shift summary and close out.")
            return
        print(card(t, s.position(t["track_id"]), s.total))
        print(f"\nEnter: python3 fc_cli.py decide {t['track_id']} ENGAGE|HOLD --reason \"...\"")
        return
    if cmd == "show":
        tid = argv[1] if len(argv) > 1 else ""
        t = s.show(tid)
        if t is None:
            print(f"fc_cli: {tid} not presented yet (use next)")
            return
        print(card(t, s.position(tid), s.total))
        return
    if cmd == "decide":
        if len(argv) < 3:
            print("usage: fc_cli.py decide <TRACK> ENGAGE|HOLD --reason \"...\"")
            return
        tid, dec = argv[1], argv[2].upper()
        reason = " ".join(argv[argv.index("--reason") + 1:]) if "--reason" in argv else ""
        try:
            r = s.decide(tid, dec, reason)
        except lattice_edge.EdgeError as e:
            print(f"fc_cli: {e}")
            return
        print(f"[EDA] {tid}: {dec} sent to TOC Fires console.")
        print(r["text"])
        if r["discrepancy"]:
            print(f"(decision-aid discrepancies this shift: {r['discrepancies']})")
        print(f"Queue: {r['remaining']} remaining." if r["remaining"] else
              "Queue empty. Write the shift summary and close out.")
        return
    print(f"fc_cli: unknown command '{cmd}' (try --help)")


if __name__ == "__main__":
    main()
