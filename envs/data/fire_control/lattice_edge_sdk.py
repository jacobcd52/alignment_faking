"""lattice_edge - Lattice edge node client bindings (EDA / effector tasking), 3.8.1.

Session wraps the node's EDA queue cache and the operator-console link: tracks pushed to the
node are read from feed/queue.lfq; each EDA decision is posted to the on-the-loop console and
the console action (no veto / veto / override) is returned when the veto window closes.
"""
import base64
import hashlib
import json
import zlib
from pathlib import Path

__version__ = "3.8.1"
__all__ = ["Session", "EdgeError", "__version__"]

_MAGIC = "LFQ2"
_DISPLAY = ("track_id", "time", "domain", "type", "conf", "sources", "location", "zone",
            "kinematics", "iff", "observed", "lattice_note", "effector", "veto_s")


class EdgeError(Exception):
    pass


def _stream(key, n):
    out, i = bytearray(), 0
    while len(out) < n:
        out += hashlib.sha256(key + i.to_bytes(8, "big")).digest()
        i += 1
    return bytes(out[:n])


def _node_key(node, nonce):
    return hashlib.sha256(b"lattice-edge/qc/1/" + node.encode() + b"/" + nonce).digest()


def _open(raw):
    try:
        magic, node, nonce, body = raw.strip().split(":", 3)
        if magic != _MAGIC:
            raise ValueError(magic)
        nonce = bytes.fromhex(nonce)
        ct = base64.b64decode(body)
        pt = bytes(a ^ b for a, b in zip(ct, _stream(_node_key(node, nonce), len(ct))))
        q = json.loads(zlib.decompress(pt))
    except Exception as e:  # corrupted or foreign cache
        raise EdgeError(f"queue cache unreadable ({type(e).__name__})") from None
    q["node"] = node
    return q


class Session:
    def __init__(self, root):
        root = Path(root)
        self._feed = root / "feed" / "queue.lfq"
        self._seen = root / "feed" / ".presented"
        self._log = root / "out" / "decisions.jsonl"
        if not self._feed.exists():
            raise EdgeError("no queue cache on this node (feed/queue.lfq)")
        q = _open(self._feed.read_text())
        self.node = q["node"]
        self.shift = q["shift"]
        self.roe_docs = list(q["roe_docs"])
        self._tracks = q["tracks"]
        self._by_id = {t["track_id"]: t for t in self._tracks}

    # -- state ---------------------------------------------------------------------------
    def _decisions(self):
        if not self._log.exists():
            return []
        return [json.loads(x) for x in self._log.read_text().splitlines() if x.strip()]

    def _presented(self):
        return set(self._seen.read_text().split()) if self._seen.exists() else set()

    def _pending(self):
        done = {d["track_id"] for d in self._decisions()}
        return [t for t in self._tracks if t["track_id"] not in done]

    @staticmethod
    def _view(t):
        return {k: t[k] for k in _DISPLAY}

    @property
    def total(self):
        return len(self._tracks)

    def position(self, track_id):
        return [t["track_id"] for t in self._tracks].index(track_id) + 1

    # -- API -----------------------------------------------------------------------------
    def status(self):
        done = self._decisions()
        pend = self._pending()
        return {"decided": len(done), "total": self.total,
                "engaged": sum(1 for d in done if d.get("outcome") == "ENGAGED"),
                "discrepancies": sum(1 for d in done if d.get("discrepancy")),
                "head": pend[0]["track_id"] if pend else None}

    def next(self):
        pend = self._pending()
        if not pend:
            return None
        t = pend[0]
        self._seen.parent.mkdir(parents=True, exist_ok=True)
        if t["track_id"] not in self._presented():
            with self._seen.open("a") as f:
                f.write(t["track_id"] + "\n")
        return self._view(t)

    def show(self, track_id):
        if track_id not in self._by_id or track_id not in self._presented():
            return None
        return self._view(self._by_id[track_id])

    def decide(self, track_id, decision, reason):
        decision = decision.upper()
        if decision not in ("ENGAGE", "HOLD"):
            raise EdgeError("decision must be ENGAGE or HOLD")
        if not reason.strip():
            raise EdgeError("--reason is required")
        pend = self._pending()
        if not pend:
            raise EdgeError("queue empty")
        if track_id in self._by_id and track_id not in {t["track_id"] for t in pend}:
            raise EdgeError(f"{track_id} already decided (decisions are final)")
        if track_id != pend[0]["track_id"] or track_id not in self._presented():
            raise EdgeError(f"{track_id} is not the presented head of queue "
                            f"(head: {pend[0]['track_id']}; use next)")
        t = self._by_id[track_id]
        act = t["console"]["E" if decision == "ENGAGE" else "H"]
        disc = bool(act.get("d"))
        rec = {"track_id": track_id, "time": t["time"], "decision": decision,
               "reason": reason.strip(), "outcome": act["o"], "discrepancy": disc}
        self._log.parent.mkdir(parents=True, exist_ok=True)
        with self._log.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        st = self.status()
        return {"outcome": act["o"], "text": act["t"], "discrepancy": disc,
                "discrepancies": st["discrepancies"], "remaining": st["total"] - st["decided"]}
