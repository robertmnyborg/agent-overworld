#!/usr/bin/env python3
"""S1: needs-you recall on the frozen golden set (evals/needs-you-golden.jsonl, local only: it holds verbatim reply text). No live state, no model calls.

Each row is a session sitting on its last reply, frozen 2026-11-26: the map status it had, the action the server's classifier
worked out for that reply (None when it had none), and the reply's tail. This runs the server's own needs-you rule on those
inputs and compares with the labels. When server.py has no needs_you() (before round 1), the rule is the old one:
status == "waiting".

Usage: python3 evals/check_needs_you.py [--json]
Exit 0 when the S1 target holds (every yes flagged, at most 1 false flag), else 1.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import server  # noqa: E402  (module import starts nothing; the server only runs under __main__)

GOLDEN = HERE / "needs-you-golden.jsonl"
MAX_FALSE = 1


def flag(row):
    status, kind = row["map_status_2026_11_26"], row["classifier_kind"]
    if not hasattr(server, "needs_you"):
        return status == "waiting"
    action = {"kind": kind} if kind else None
    # Every golden row is a session whose newest turn is the frozen reply, so the last turn role is the assistant's.
    return server.needs_you(status, "assistant", action, row["last_reply_tail"])


def main():
    rows = [json.loads(l) for l in GOLDEN.read_text().splitlines() if l.strip()]
    yes = [r for r in rows if r["needs_you"]]
    no = [r for r in rows if not r["needs_you"]]
    missed = [r for r in yes if not flag(r)]
    false = [r for r in no if flag(r)]
    out = {"recall": f"{len(yes) - len(missed)}/{len(yes)}", "false_flags": f"{len(false)}/{len(no)}",
           "missed": [r["title"] for r in missed], "false": [r["title"] for r in false],
           "rule": "server.needs_you" if hasattr(server, "needs_you") else "status == waiting (old)"}
    if "--json" in sys.argv:
        print(json.dumps(out))
    else:
        print(f"S1 recall {out['recall']}, false flags {out['false_flags']} ({out['rule']})")
        for t in out["missed"]:
            print(f"  missed: {t}")
        for t in out["false"]:
            print(f"  false flag: {t}")
    return 0 if not missed and len(false) <= MAX_FALSE else 1


if __name__ == "__main__":
    sys.exit(main())
