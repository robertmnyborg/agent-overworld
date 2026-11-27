#!/usr/bin/env python3
"""Regression checks for #45 and #46 on synthetic transcripts: no live state, no model calls.

Usage: python3 evals/test_last_reply.py   (exit 0 when all pass)
"""
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import server  # noqa: E402

REPLY = "Not quite bare, but close. Checking your harness now."


def rec(kind, content, **extra):
    return {"type": kind, "timestamp": "2026-11-26T00:00:00Z", "message": {"role": kind, "content": content}, **extra}


def role_and_reply(records):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("".join(json.dumps(r) + "\n" for r in records))
    _, _, role, full = server.last_reply(f.name)
    Path(f.name).unlink()
    return role, full


def main():
    prompt = rec("user", "can we confirm the grades?", origin={"kind": "human"})
    text = rec("assistant", [{"type": "text", "text": REPLY}])
    tool = rec("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}])
    result = rec("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}])
    cases = {
        "task notification after a reply is not Robert's turn":
            ([prompt, text, rec("user", "<task-notification>stopped</task-notification>", origin={"kind": "task-notification"})], "assistant"),
        "interrupt after a tool call leaves the reply waiting on Robert":
            ([prompt, text, tool, result, rec("user", [{"type": "text", "text": "[Request interrupted by user]"}])], "assistant"),
        "a real prompt after a reply is Robert's turn":
            ([prompt, text, rec("user", "thanks, go on", origin={"kind": "human"})], "user"),
        "a prompt with no origin (older transcripts) is Robert's turn":
            ([prompt, text, rec("user", "go on")], "user"),
        "a tool result means the turn is still going":
            ([prompt, text, tool, result], "user"),
    }
    failed = 0
    for name, (records, want) in cases.items():
        role, full = role_and_reply(records)
        ok = role == want and full == REPLY
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name} (role {role})")
    old = server.action_key(REPLY)
    server.ACTION_RULES_SHA = "0" * 12
    ok = server.action_key(REPLY) != old
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} a rule change gives every reply a new action-cache key")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
