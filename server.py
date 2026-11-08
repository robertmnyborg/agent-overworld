#!/usr/bin/env python3
"""Agent Overworld: serves a map of cmux workspaces (regions) and tabs (sessions).

Reads cmux's own records; writes nothing except ~/.overworld/edges.jsonl (via spinoff.sh).
Started by autostart.zsh from the first cmux shell (cmux's socket only accepts processes launched inside cmux).
While cmux is running, keeps a pinned "Overworld" workspace (browser pane on this server) in slot 1 (⌘1),
and a pinned, ungrouped "Scratch" workspace in slot 2 for one-off sessions not yet worth their own workspace.
"""
import hashlib, json, os, re, subprocess, threading, time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("OVERWORLD_PORT", "7717"))
HERE = Path(__file__).parent
CMUXTERM = Path.home() / ".cmuxterm"
EDGES = Path.home() / ".overworld" / "edges.jsonl"
PIDFILE = Path.home() / ".overworld" / "server.pid"
NEW_SESSION_COMMAND = "claude"
CLAUDE = str(Path.home() / ".local" / "bin" / "claude")
# Headless naming call: no settings/hooks/MCP/tools, nothing saved to ~/.claude/projects.
NAMER = [CLAUDE, "-p", "--model", "haiku", "--setting-sources", "", "--no-session-persistence", "--strict-mcp-config",
         "--tools", "", "--disable-slash-commands", "--output-format", "json"]
NAME_TIMEOUT = 60  # seconds per workspace call
RECENT_PROMPTS = 5  # user prompts per tab sent to the namer; earlier turns are ignored
NAME_WORDS = {"t": 3, "w": 5}  # max words for tab (t) and workspace (w) names
NAME_SCHEMA = {"type": "object", "required": ["names"], "properties": {"names": {"type": "array", "items": {
    "type": "object", "required": ["key", "name"], "properties": {"key": {"type": "string"}, "name": {"type": "string"}}}}}}
NAME_RULES = """Name cmux workspaces and the agent session tabs (Claude Code or Antigravity) inside them, from what each session is working on NOW.
Each tab gives its most recent user prompts (oldest first) and last reply. Name the latest topic, even if earlier prompts differ.
Tab names: 2-3 words. Workspace names: 2-5 words covering the tabs inside it. Concrete nouns from the work (project, feature, person, artifact).
No quotes, no emoji, no trailing punctuation, no generic words like "Session", "Chat", "Claude", "Gemini", "Argon", "Antigravity", "Agent", or "Work". Title Case.
Return one entry per key given (every workspace key "w*" and every tab key "t*"). Input:
"""

SCREEN_TTL = 30  # seconds to cache read-screen recaps for agents without a transcript recap
_screen_cache = {}
_recap_cache = {}  # transcript path -> (mtime, (text, last turn time, last turn role))
_events = {"inode": None, "offset": 0, "last": {}}  # surface_id -> (hook event name, occurred_at)
WORKING = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop", "PreCompact"}


CMUX = "/opt/homebrew/bin/cmux"
ENSURE_EVERY = 15  # seconds between checks that the Overworld and Scratch workspaces exist
SCRATCH = "Scratch"


def cmux(*args):
    out = subprocess.run([CMUX, *args], capture_output=True, text=True, timeout=10,
                         env={**os.environ, "CMUX_QUIET": "1"})
    if out.returncode and out.stderr:
        print(f"cmux {args[0]}: {out.stderr.strip()[:300]}", flush=True)
    return out.stdout


def ensure_workspace():
    """Keep a pinned, top-slot workspace named Overworld holding one browser tab on this server. Idempotent; runs every ENSURE_EVERY s."""
    if "PONG" not in cmux("ping"):
        return
    listing = json.loads(cmux("--json", "list-workspaces"))["workspaces"]
    ws = next((w for w in listing if w["title"] == "Overworld"), None)
    if ws is None:
        cmux("new-workspace", "--name", "Overworld")
        return  # a new workspace has no panes yet; the next pass fills it
    panes = json.loads(cmux("--json", "--id-format", "both", "tree", "--workspace", ws["ref"]))["windows"][0]["workspaces"][0]["panes"]
    if not panes:
        return
    surfaces = [sf for pane in panes for sf in pane["surfaces"]]
    if not any(sf["type"] == "browser" for sf in surfaces):
        cmux("new-surface", "--type", "browser", "--pane", panes[0]["id"], "--workspace", ws["ref"], "--url", f"http://127.0.0.1:{PORT}")
        for sf in surfaces:
            cmux("close-surface", "--surface", sf["id"], "--workspace", ws["ref"])
    if not ws["pinned"]:
        cmux("workspace-action", "--workspace", ws["ref"], "--action", "pin")
    if ws["index"] != 0:
        cmux("workspace-action", "--workspace", ws["ref"], "--action", "move-top")
    ensure_scratch(listing)


def ensure_scratch(listing):
    """Keep a pinned Scratch workspace right under Overworld, outside every group (the map shows it as its own strip)."""
    ws = next((w for w in listing if w["title"] == SCRATCH), None)
    if ws is None:
        cmux("new-workspace", "--name", SCRATCH, "--command", NEW_SESSION_COMMAND, "--focus", "false")
        return  # pinned and placed on the next pass
    groups = json.loads(cmux("workspace-group", "list", "--json") or '{"groups": []}')["groups"]
    if any(ws["ref"] in g["member_workspace_refs"] for g in groups):
        cmux("workspace-group", "remove", "--workspace", ws["ref"])
    if not ws["pinned"]:
        cmux("workspace-action", "--workspace", ws["ref"], "--action", "pin")
    if ws["index"] != 1:
        cmux("reorder-workspace", "--workspace", ws["ref"], "--index", "1")


def keep_workspace():
    while True:
        try:
            ensure_workspace()
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"ensure_workspace: {e!r}", flush=True)
        time.sleep(ENSURE_EVERY)


def focus(workspace, surface):
    cmux("select-workspace", "--workspace", workspace)
    cmux("focus-panel", "--panel", surface, "--workspace", workspace)


def load_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _scan_events(path, start=0):
    with open(path, "rb") as f:
        f.seek(start)
        for raw in f:
            if b'"agent.hook.' not in raw:
                continue
            e = json.loads(raw)
            if e.get("surface_id"):
                _events["last"][e["surface_id"]] = (e["name"].rsplit(".", 1)[-1], e["occurred_at"])
        return f.tell()


def hook_events():
    """Follow ~/.cmuxterm/events.jsonl incrementally; on first run or rotation, backfill from events.jsonl.1."""
    path = CMUXTERM / "events.jsonl"
    inode = path.stat().st_ino
    if inode != _events["inode"]:
        if _events["inode"] is None and (CMUXTERM / "events.jsonl.1").exists():
            _scan_events(CMUXTERM / "events.jsonl.1")
        _events["inode"], _events["offset"] = inode, 0
    _events["offset"] = _scan_events(path, _events["offset"])
    return _events["last"]


def plain(text):
    """Collapse whitespace and drop markdown emphasis/code marks so recaps read as one line."""
    return " ".join(re.sub(r"[*`#>]+", "", text).split())[:240]


ASK_CHARS = 120  # about two card lines
FULL_CHARS = 8000  # tail of the last reply sent for the reply view
ACTION_EVERY = 20  # seconds between background passes that work out "your turn" actions


ASK_CUE = re.compile(r"\b(next step|only you|your call|should i|want me to|shall i|pick|decide|approve|confirm with|let me know|say if|tell me)\b", re.I)
LIST_LINE = re.compile(r"^\s*([-*\u2022]|\d+[.)])\s")


def ask_of(raw):
    """The part of a reply that asks something of the user, in about two card lines. Text only, no model call:
    the last question near the end, else the last next-step sentence, else the closing sentences of the last prose paragraph.
    Links are reduced to their text and "Sources:" / link-list paragraphs are skipped, so a URL's "?" never counts."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    paras = [p for p in paras if not p.startswith(("|", "```")) and not re.match(r"(sources|references|links)\b", p, re.I)]
    if not paras:
        return ""
    tail = paras[-4:]
    sentences = lambda p: [x for x in re.split(r"(?<=[.?!])\s+", " ".join(p.split())) if x]
    for p in reversed(tail):
        q = [x for x in sentences(p) if x.endswith("?")]
        if q:
            return plain(q[-1])
    for p in reversed(tail):
        cue = [x for x in sentences(p) if ASK_CUE.search(x)]
        if cue:
            return plain(cue[-1])
    prose = [p for p in tail if not all(LIST_LINE.match(l) or l.rstrip().endswith(":") for l in p.splitlines())]
    out = ""
    for x in reversed(sentences((prose or tail)[-1])):  # closing sentences that fit in two lines
        if out and len(x) + len(out) > ASK_CHARS:
            break
        out = (x + " " + out).strip()
    return plain(out)


def last_reply(transcript):
    """(last assistant text ~240 chars, last user/assistant turn time, its role, full text of that reply) from a Claude transcript."""
    path = Path(transcript or "")
    if not path.is_file():
        return "", None, None, ""
    mtime = path.stat().st_mtime
    hit = _recap_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 400_000))
        lines = f.read().splitlines()
    text, turn_at, turn_role, full = "", None, None, ""
    for raw in reversed(lines):
        if b'"assistant"' not in raw and b'"user"' not in raw:
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if e.get("type") not in ("user", "assistant"):
            continue
        if turn_at is None:
            turn_at, turn_role = e.get("timestamp"), e["type"]
        if e["type"] != "assistant":
            continue
        parts = [c.get("text", "") for c in e.get("message", {}).get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
        if any(p.strip() for p in parts):
            full = "\n\n".join(p.strip() for p in parts if p.strip())
            text = plain(full)
            break
    _recap_cache[path] = (mtime, (text, turn_at, turn_role, full))
    return text, turn_at, turn_role, full


LANE_WINDOW = 30 * 60  # seconds a finished subagent stays in its session's lane
LANE_MAX = 6  # rows per lane; running agents first
STALE_AFTER = 15 * 60  # an unfinished subagent silent this long was stopped or killed
_lane_cache = {}  # subagent transcript -> (mtime, row)


def subagent_row(path):
    """One subagent transcript -> {type, label, status, detail, started, ended}. Status: running / done / stopped."""
    mtime = path.stat().st_mtime
    hit = _lane_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    meta = load_json(path.with_suffix(".meta.json"))
    with open(path, "rb") as f:
        started = json.loads(f.readline()).get("timestamp")
        f.seek(max(0, path.stat().st_size - 200_000))
        lines = f.read().splitlines()
    last = None
    for raw in reversed(lines):
        if b'"type":"assistant"' in raw:
            try:
                last = json.loads(raw)
                break
            except json.JSONDecodeError:
                continue  # first line of the tail can be cut mid-record
    msg = (last or {}).get("message", {})
    content = [c for c in msg.get("content", []) if isinstance(c, dict)]
    texts = [c["text"] for c in content if c.get("type") == "text" and c.get("text", "").strip()]
    tool = next((c for c in reversed(content) if c.get("type") == "tool_use"), None)
    if msg.get("stop_reason") == "end_turn" and not tool:
        status, detail = "done", plain(" ".join(texts))
    else:
        status = "stopped" if time.time() - mtime > STALE_AFTER else "running"
        arg = next((str(v) for v in (tool or {}).get("input", {}).values() if isinstance(v, str)), "")
        detail = plain(f"{tool['name']}: {arg}") if tool else plain(" ".join(texts))
    row = {"type": meta.get("agentType") or "agent", "label": meta.get("description") or path.stem,
           "status": status, "detail": detail[:160], "started": started, "ended": (last or {}).get("timestamp"), "mtime": mtime}
    _lane_cache[path] = (mtime, row)
    return row


def subagents(transcript):
    """Subagents spawned by one Claude session: running ones, then those finished in the last LANE_WINDOW, newest first."""
    if not transcript:
        return [], 0
    folder = Path(transcript).with_suffix("") / "subagents"
    if not folder.is_dir():
        return [], 0
    rows = [subagent_row(p) for p in folder.glob("agent-*.jsonl")]
    rows = [r for r in rows if r["status"] == "running" or time.time() - r["mtime"] < LANE_WINDOW]
    rows.sort(key=lambda r: (r["status"] != "running", -r["mtime"]))
    return rows[:LANE_MAX], max(0, len(rows) - LANE_MAX)


TIMELINE_TAIL = 4_000_000  # bytes of the main transcript read for the current turn
_turn_cache = {}  # transcript -> (mtime, records)


def _epoch(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _records(path, tail=None):
    """user/assistant records of a transcript (optionally only its last `tail` bytes), oldest first."""
    with open(path, "rb") as f:
        if tail:
            f.seek(max(0, path.stat().st_size - tail))
        lines = f.read().splitlines()
    out = []
    for raw in lines:
        if b'"timestamp"' not in raw:
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue  # first line of a tail can be cut mid-record
        if e.get("type") in ("user", "assistant") and e.get("timestamp"):
            out.append(e)
    return out


def _blocks(e):
    c = e.get("message", {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _user_text(e):
    """Text of a user record that is not a tool result ('' for tool results)."""
    c = e.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    return "" if any(b.get("type") == "tool_result" for b in _blocks(e)) else " ".join(b.get("text", "") for b in _blocks(e) if b.get("type") == "text")


def _is_prompt(e):
    text = _user_text(e).lstrip()
    return (e["type"] == "user" and not e.get("isMeta") and not e.get("isCompactSummary")
            and bool(text) and not text.startswith("<task-notification"))


def _tool_label(b):
    inp = b.get("input") or {}
    arg = inp.get("description") if b.get("name") == "Agent" else next((v for v in inp.values() if isinstance(v, str)), "")
    return plain(f"{b.get('name')}: {arg}")[:100]


def segments(records, now, main):
    """Records -> [{kind, start, end, label, open}]. kind: model (generating), tool (a call until its result),
    you (main lane: reply sent, next prompt not yet), agents (main lane: waiting on a background notification)."""
    segs, tools, prev = [], {}, None
    for e in records:
        t = _epoch(e["timestamp"])
        if e["type"] == "assistant":
            if prev:
                segs.append({"kind": "model", "start": _epoch(prev["timestamp"]), "end": t, "label": "model generating"})
            for b in _blocks(e):
                if b.get("type") == "tool_use":
                    tools[b.get("id")] = (t, _tool_label(b))
        else:
            for b in _blocks(e):
                if b.get("type") == "tool_result" and b.get("tool_use_id") in tools:
                    start, label = tools.pop(b["tool_use_id"])
                    segs.append({"kind": "tool", "start": start, "end": t, "label": label})
            if main and prev and prev["type"] == "assistant" and _user_text(e):
                kind = "you" if _is_prompt(e) else "agents"
                segs.append({"kind": kind, "start": _epoch(prev["timestamp"]), "end": t,
                             "label": "waiting on you" if kind == "you" else "waiting on background agents"})
        prev = e
    for start, label in tools.values():  # calls still running
        segs.append({"kind": "tool", "start": start, "end": now, "label": label, "open": True})
    if prev and not tools:
        tail_start = _epoch(prev["timestamp"])
        if prev["type"] == "user":
            segs.append({"kind": "model", "start": tail_start, "end": now, "label": "model generating", "open": True})
        elif main and prev.get("message", {}).get("stop_reason") == "end_turn":
            segs.append({"kind": "you", "start": tail_start, "end": now, "label": "waiting on you", "open": True})
    merged = []  # back-to-back model slices read as one bar
    for s in sorted(segs, key=lambda s: s["start"]):
        m = merged[-1] if merged else None
        if m and s["kind"] == "model" == m["kind"] and s["start"] - m["end"] < 1:
            m["end"], m["open"] = max(m["end"], s["end"]), s.get("open", m.get("open"))
        else:
            merged.append(s)
    return merged


def timeline(surface):
    """The current turn of one session (last prompt -> now): main lane + one lane per subagent, plus totals."""
    sess = agent_sessions().get(surface) or {}
    path = Path(sess.get("transcript") or "")
    if not path.is_file():
        return {"error": "no Claude transcript for this tab"}
    mtime, now = path.stat().st_mtime, time.time()
    hit = _turn_cache.get(path)
    records = hit[1] if hit and hit[0] == mtime else _records(path, TIMELINE_TAIL)
    _turn_cache[path] = (mtime, records)
    turn = max((i for i, e in enumerate(records) if _is_prompt(e)), default=0)
    records = records[turn:]
    start = _epoch(records[0]["timestamp"]) if records else now
    lanes = [{"name": "main", "type": "session", "status": None, "segments": segments(records, now, True)}]
    folder = path.with_suffix("") / "subagents"
    for p in sorted(folder.glob("agent-*.jsonl")) if folder.is_dir() else []:
        if p.stat().st_mtime < start:
            continue
        row = subagent_row(p)
        segs = [s for s in segments(_records(p), now, False) if s["end"] >= start]
        if row["status"] != "running":
            segs = [{**s, "open": False} for s in segs]
            if row["status"] == "stopped":
                segs = [{**s, "end": min(s["end"], row["mtime"])} for s in segs]
        lanes.append({"name": row["label"], "type": row["type"], "status": row["status"], "segments": segs})
    tail = lanes[0]["segments"][-1] if lanes[0]["segments"] else None
    if tail and tail.get("open") and tail["kind"] == "you" and any(l["status"] == "running" for l in lanes[1:]):
        tail.update(kind="agents", label="waiting on background agents")  # reply sent, but its agents are still working
    totals = {}
    for s in lanes[0]["segments"]:
        totals[s["kind"]] = totals.get(s["kind"], 0) + s["end"] - max(s["start"], start)
    slowest = sorted(({"lane": l["name"], **s} for l in lanes for s in l["segments"] if s["kind"] in ("tool", "model")),
                     key=lambda s: s["start"] - s["end"])[:3]
    # The axis ends where activity ends: a trailing "waiting on you" stretch can be hours and would flatten every bar.
    busy = [s["end"] for l in lanes for s in l["segments"] if s["kind"] != "you"]
    return {"start": start, "now": now, "active_end": max(busy, default=now), "prompt": plain(_user_text(records[0]))[:140] if records else "",
            "lanes": lanes, "totals": totals, "slowest": slowest}


# ---- Trace: agents, model calls and tool calls as one tree, with tokens and cost ----
# List prices in $ per million tokens: (input, output, cache read). Cache writes are 1.25x input (5 min) or 2x (1 h).
# Source: claude-api skill model table, cached 2026-10-06. Longest matching prefix wins; unknown models cost None.
PRICES = {
    "claude-fable-5-1": (10, 50, 0.25), "claude-mythos-5-1": (10, 50, 0.25),
    "claude-fable-5": (10, 50, 1.0), "claude-mythos-5": (10, 50, 1.0),
    "claude-opus-5-5": (4, 20, 0.20), "claude-opus-5": (5, 25, 0.50),
    "claude-opus-4-8": (5, 25, 0.50), "claude-opus-4-7": (5, 25, 0.50), "claude-opus-4-6": (5, 25, 0.50),
    "claude-sonnet-5-5": (2, 10, 0.20), "claude-sonnet-5": (2, 10, 0.20), "claude-sonnet-4-6": (3, 15, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1, 5, 0.10),
}
HAIKU_55_LONG = (0.50, 2.50, 0.05)  # Haiku 5.5 prompts over 100K input tokens
FAST_MULTIPLIER = 2  # fast mode (Opus) bills 2x standard
PREVIEW = 1200  # chars of a tool's input / output kept for the waterfall
_full_cache = {}  # transcript -> (mtime, records)


def call_cost(model, u):
    """Dollars for one model call from its usage record, at list price."""
    key = max((k for k in PRICES if (model or "").startswith(k)), key=len, default=None)
    if not key:
        return None
    inp, out, read = PRICES[key]
    cached = u.get("cache_creation") or {}
    write_1h = cached.get("ephemeral_1h_input_tokens", 0)
    write_5m = u.get("cache_creation_input_tokens", 0) - write_1h
    prompt = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    if key == "claude-haiku-5-5" and prompt > 100_000:
        inp, out, read = HAIKU_55_LONG
    dollars = (u.get("input_tokens", 0) * inp + u.get("output_tokens", 0) * out + u.get("cache_read_input_tokens", 0) * read
               + write_5m * inp * 1.25 + write_1h * inp * 2) / 1e6
    return dollars * (FAST_MULTIPLIER if u.get("speed") == "fast" else 1)


def _all_records(path):
    mtime = path.stat().st_mtime
    hit = _full_cache.get(path)
    if not hit or hit[0] != mtime:
        hit = _full_cache[path] = (mtime, _records(path))
    return hit[1]


def _preview(value):
    if isinstance(value, list):
        value = "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in value)
    text = value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False)
    return text if len(text) <= PREVIEW else text[:PREVIEW] + f"\n… ({len(text) - PREVIEW:,} more chars)"


def _agent(path, records, name, kind, status, by_tool, now, detail):
    """One agent transcript -> agent node whose children are its model calls and tool calls (detail)
    or only its child agents (not detail). Child agents hang under the tool call that spawned them."""
    calls, spans, tools, kids, prev_t = {}, [], {}, [], None
    for e in records:
        t = _epoch(e["timestamp"])
        msg = e.get("message", {})
        if e["type"] == "assistant":
            mid = msg.get("id") or e.get("uuid")
            c = calls.get(mid)
            if not c:
                c = calls[mid] = {"kind": "llm", "name": msg.get("model") or "model", "start": prev_t or t, "end": t}
                spans.append(c)
            c["end"], c["usage"] = t, msg.get("usage") or {}
            for b in _blocks(e):
                if b.get("type") != "tool_use":
                    continue
                span = {"kind": "tool", "name": b.get("name"), "label": _tool_label(b), "start": t, "end": None, "children": []}
                if detail:
                    span["input"] = _preview(b.get("input"))
                tools[b.get("id")] = span
                spans.append(span)
                child = by_tool.get(b.get("id"))
                if child:
                    meta = load_json(child.with_suffix(".meta.json"))
                    node = _agent(child, _all_records(child), meta.get("description") or child.stem, meta.get("agentType") or "agent",
                                  subagent_row(child)["status"], by_tool, now, detail)
                    span["children"].append(node)
                    kids.append(node)
        else:
            for b in _blocks(e):
                span = tools.get(b.get("tool_use_id")) if b.get("type") == "tool_result" else None
                if span and span["end"] is None:
                    span["end"], span["error"] = t, bool(b.get("is_error"))
                    if detail:
                        span["output"] = _preview(b.get("content"))
        prev_t = t
    for span in tools.values():
        if span["end"] is None:
            span["end"], span["open"] = (now, True) if status == "running" else (prev_t, False)
    models = {}
    for c in calls.values():
        u = c.pop("usage")
        c["tokens_in"] = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        c["tokens_out"] = u.get("output_tokens", 0)
        c["cache_read"] = u.get("cache_read_input_tokens", 0)
        c["cost"] = call_cost(c["name"], u)
        models[c["name"]] = models.get(c["name"], 0) + 1
    own = sum(c["cost"] or 0 for c in calls.values())
    start = _epoch(records[0]["timestamp"]) if records else now
    node = {"kind": "agent", "name": name, "type": kind, "status": status,
            "model": max(models, key=models.get) if models else None,
            "start": start, "end": now if status == "running" else (prev_t or start),
            "calls": len(calls), "tools": len(tools), "cost_own": own, "cost": own + sum(k["cost"] for k in kids),
            "unpriced": sorted(m for m in models if call_cost(m, {}) is None),
            "tokens_in": sum(c["tokens_in"] for c in calls.values()), "tokens_out": sum(c["tokens_out"] for c in calls.values()),
            "children": sorted(spans, key=lambda s: s["start"]) if detail else kids}
    return node


def trace(surface, scope="turn", running=False):
    """scope=turn: the current turn with every model and tool call (waterfall).
    scope=session: the whole session, agents only (tree with rolled-up cost).
    running comes from the map's status (hook events), which the transcript alone can't tell."""
    sess = agent_sessions().get(surface) or {}
    path = Path(sess.get("transcript") or "")
    if not path.is_file():
        return {"error": "no Claude transcript for this tab"}
    now = time.time()
    records = _all_records(path)
    if scope == "turn":
        turn = max((i for i, e in enumerate(records) if _is_prompt(e)), default=0)
        records = records[turn:]
    start = _epoch(records[0]["timestamp"]) if records else now
    folder = path.with_suffix("") / "subagents"
    by_tool = {}
    for p in folder.glob("agent-*.jsonl") if folder.is_dir() else []:
        if scope == "turn" and p.stat().st_mtime < start:
            continue
        tid = load_json(p.with_suffix(".meta.json")).get("toolUseId")
        if tid:
            by_tool[tid] = p
    root = _agent(path, records, "main session", "session", "running" if running else "done", by_tool, now, scope == "turn")
    return {"scope": scope, "start": start, "now": now, "prompt": plain(_user_text(records[0]))[:140] if records else "", "root": root}


def agent_sessions():
    """surface_id -> {agent, lifecycle, recap, cwd, updated, pid} for Claude and agy."""
    out = {}
    claude = load_json(CMUXTERM / "claude-hook-sessions.json")
    sessions = claude.get("sessions", {})
    # cmux's activeSessionsBySurface can drop a live session, so pick per surface: live process first, then newest.
    best = {}
    for s in sessions.values():
        surface = s.get("surfaceId")
        rank = (alive(s.get("pid")), s.get("updatedAt") or 0)
        if surface and (surface not in best or rank > best[surface][0]):
            best[surface] = (rank, s)
    for surface, (_, s) in best.items():
        text, turn_at, turn_role, full = last_reply(s.get("transcriptPath"))
        out[surface] = {"agent": "claude", "lifecycle": s.get("agentLifecycle"), "recap": text or s.get("lastBody") or "",
                        "full": full[-FULL_CHARS:], "ask": ask_of(full),
                        "cwd": s.get("cwd"), "updated": s.get("updatedAt"), "pid": s.get("pid"),
                        "turn_at": turn_at, "turn_role": turn_role, "transcript": s.get("transcriptPath")}
    agy = load_json(CMUXTERM / "antigravity-hook-sessions.json").get("sessions", {})
    for s in agy.values():
        cur = out.get(s["surfaceId"])
        if cur is None or (s.get("updatedAt") or 0) > (cur.get("updated") or 0):
            prompts, text, turn_at, turn_role = agy_turns(s.get("transcriptPath"))
            out[s["surfaceId"]] = {"agent": "agy", "lifecycle": s.get("agentLifecycle"), "recap": text,
                                   "cwd": s.get("cwd"), "updated": s.get("updatedAt"), "pid": s.get("pid"),
                                   "turn_at": turn_at, "turn_role": turn_role, "prompts": prompts}
    return out


_agy_cache = {}  # agy transcript path -> (mtime, (prompts, last reply, last turn time, its role))


def agy_turns(transcript, n=RECENT_PROMPTS):
    """(last n user prompts, last reply ~240 chars, last turn time, its role) from an Antigravity transcript_full.jsonl.
    Prompts are USER_INPUT records (text inside <USER_REQUEST>); replies are PLANNER_RESPONSE records with text."""
    path = Path(transcript or "")
    if not path.is_file():
        return [], "", None, None
    mtime = path.stat().st_mtime
    hit = _agy_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 2_000_000))
        lines = f.read().splitlines()
    prompts, text, turn_at, turn_role = [], "", None, None
    for raw in reversed(lines):
        if b'"USER_INPUT"' not in raw and b'"PLANNER_RESPONSE"' not in raw:
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue  # first line of the tail can be cut mid-record
        content = e.get("content") or ""
        if e.get("type") == "USER_INPUT":
            m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", content, re.S)
            prompt = plain(m.group(1) if m else content)[:300]
            if prompt and prompt not in prompts and len(prompts) < n:
                prompts.append(prompt)
            role = "user"
        elif e.get("type") == "PLANNER_RESPONSE" and content.strip():
            text = text or plain(content)
            role = "assistant"
        else:
            continue  # a tool-call-only planner step is not a turn
        if turn_at is None:
            turn_at, turn_role = e.get("created_at"), role
        if text and len(prompts) == n:
            break
    result = (prompts[::-1], text, turn_at, turn_role)
    _agy_cache[path] = (mtime, result)
    return result


def recent_prompts(transcript, n=RECENT_PROMPTS):
    """The last n real user prompts from a transcript, oldest first, so names track where the session ended up."""
    path = Path(transcript or "")
    if not path.is_file():
        return []
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 2_000_000))
        lines = f.read().splitlines()
    prompts = []
    for raw in reversed(lines):
        if b'"type":"user"' not in raw:
            continue
        try:
            content = json.loads(raw).get("message", {}).get("content")
        except json.JSONDecodeError:
            continue  # first line of the tail can be cut mid-record
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if content and not content.lstrip().startswith("<"):  # skip tool results, hook and command wrappers
            text = plain(content)[:300]
            if text in prompts:
                continue  # transcripts can log the same prompt twice
            prompts.append(text)
            if len(prompts) == n:
                break
    return prompts[::-1]


def name_batch(workspace_payload):
    """One headless Haiku call for one workspace and its tabs -> [{key, name}]."""
    out = subprocess.run([*NAMER, "--json-schema", json.dumps(NAME_SCHEMA)], input=NAME_RULES + json.dumps(workspace_payload, indent=1),
                         capture_output=True, text=True, timeout=NAME_TIMEOUT, cwd="/tmp",  # /tmp: keeps ~/CLAUDE.md out of the prompt
                         env={**os.environ, "MAX_THINKING_TOKENS": "0"})  # thinking made this 18-78s instead of ~5s
    result = json.loads(out.stdout)
    if result.get("is_error"):
        raise RuntimeError(result.get("result", "naming call failed"))
    return result["structured_output"]["names"], result.get("total_cost_usd") or 0


ACTIONS = Path.home() / ".overworld" / "actions.json"  # sha1 of a reply -> what it needs from the user; survives restarts
ACTION_SCHEMA = {"type": "object", "required": ["kind", "action", "options"], "properties": {
    "kind": {"type": "string", "enum": ["decision", "action", "none"]},
    "action": {"type": "string"},
    "options": {"type": "array", "items": {"type": "string"}}}}
ACTION_RULES = """A coding agent finished a turn and is waiting for its user. From the user's last prompt and the agent's reply,
say what the user must do or decide so the work moves to the next step.
- kind "decision": the reply asks the user to choose or approve something. action = the question, one sentence, max 20 words,
  naming what is being decided. options = the choices as short labels (2-6 words each, at most 5), in the reply's order; [] for yes/no.
- kind "action": the user must do something themselves (ask a person, run a command, review a draft, grant access).
  action = that step as an imperative sentence, max 20 words, naming who/what. options = [].
- kind "none": the reply asks nothing and needs nothing. action = "Nothing needed. Suggested next: " + the most useful
  next instruction the user could give, max 15 words. options = [].
Plain words, no markdown, no quotes, no emoji. Use names and numbers from the reply. Input:
"""
_actions = {"cache": None, "lock": threading.Lock(), "busy": set()}


def _action_cache():
    if _actions["cache"] is None:
        _actions["cache"] = json.loads(ACTIONS.read_text()) if ACTIONS.exists() else {}
    return _actions["cache"]


def action_key(full):
    return hashlib.sha1(full.encode()).hexdigest()


def cached_action(full):
    return _action_cache().get(action_key(full)) if full else None


def work_out_action(full, prompt):
    """One headless Haiku call: what this reply needs from the user. Cached by reply text, so each reply costs one call."""
    key = action_key(full)
    with _actions["lock"]:
        if key in _action_cache() or key in _actions["busy"]:
            return _action_cache().get(key)
        _actions["busy"].add(key)
    try:
        payload = {"user_last_prompt": prompt, "agent_reply": full[-FULL_CHARS:]}
        out = subprocess.run([*NAMER, "--json-schema", json.dumps(ACTION_SCHEMA)], input=ACTION_RULES + json.dumps(payload, indent=1),
                             capture_output=True, text=True, timeout=NAME_TIMEOUT, cwd="/tmp",
                             env={**os.environ, "MAX_THINKING_TOKENS": "0"})
        result = json.loads(out.stdout)
        if result.get("is_error"):
            raise RuntimeError(result.get("result", "action call failed"))
        row = {**result["structured_output"], "cost": result.get("total_cost_usd") or 0}
        with _actions["lock"]:
            _action_cache()[key] = row
            ACTIONS.write_text(json.dumps(_action_cache()))
        print(f"{time.strftime('%H:%M:%S')} action: {row['kind']} | {row['action'][:80]} | ${row['cost']:.4f}", flush=True)
        return row
    finally:
        _actions["busy"].discard(key)


def keep_actions():
    """Background: work out the action for every "your turn" session whose last reply has none yet, one call at a time."""
    while True:
        try:
            agents = agent_sessions()
            for r in state()["regions"]:
                for t in r["sessions"]:
                    if t["status"] == "waiting" and t["full"] and not cached_action(t["full"]):
                        work_out_action(t["full"], (recent_prompts((agents.get(t["id"]) or {}).get("transcript"), 1) or [""])[-1])
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, RuntimeError, OSError) as e:
            print(f"{time.strftime('%H:%M:%S')} keep_actions failed: {e!r}"[:400], flush=True)
        time.sleep(ACTION_EVERY)


def autoname(workspace=None):
    """Name workspaces (all, or one) and their agent tabs from session content, one Haiku call per workspace in parallel."""
    agents = agent_sessions()
    targets, payloads = {}, []
    for i, r in enumerate(state()["regions"]):
        if workspace not in (None, r["id"]):
            continue
        tabs = []
        for j, t in enumerate(r["sessions"]):
            if not t["agent"]:
                continue  # plain shell: nothing to name it from
            sess = agents.get(t["id"], {})
            prompts = sess.get("prompts") or recent_prompts(sess.get("transcript"))  # agy sessions carry their prompts
            key = f"t{i}_{j}"
            targets[key] = (r["id"], t["id"])
            tabs.append({"key": key, "current_name": t["title"], "recent_prompts": prompts, "last_reply": t["recap"]})
        if tabs:
            if not r["scratch"]:  # Scratch keeps its name; only its tabs get named
                targets[f"w{i}"] = (r["id"], None)
            payloads.append({"key": f"w{i}", "current_name": r["title"], "tabs": tabs})
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(name_batch, payloads))
    renamed, cost = 0, sum(c for _, c in batches)
    for names, _ in batches:
        for entry in names:
            if entry["key"] not in targets:
                continue
            ws, surface = targets[entry["key"]]
            name = " ".join(entry["name"].strip().strip('."\'').split()[:NAME_WORDS[entry["key"][0]]])
            if surface:
                cmux("rename-tab", "--workspace", ws, "--surface", surface, "--", name)
            else:
                cmux("workspace-action", "--workspace", ws, "--action", "rename", "--title", name)
            renamed += 1
    print(f"{time.strftime('%H:%M:%S')} autoname {workspace or 'all'}: {renamed} renamed in {len(payloads)} calls, ${cost:.3f}", flush=True)
    return {"renamed": renamed, "cost_usd": cost}


def notifications():
    """surface_id -> newest unread notification title ("Waiting" / "Completed in ...")."""
    unread = {}
    for line in cmux("list-notifications").splitlines():
        parts = line.split(":", 1)[-1].split("|")
        if len(parts) >= 8 and parts[3] == "unread":
            unread.setdefault(parts[2], parts[5])
    return unread


def screen_recap(surface, workspace):
    hit = _screen_cache.get(surface)
    if hit and time.time() - hit[0] < SCREEN_TTL:
        return hit[1]
    text = cmux("read-screen", "--workspace", workspace, "--surface", surface, "--lines", "8")
    footer = re.compile(r"[─━═│╭╮╰╯]|^❯|auto mode|shift\+tab|/effort|context\)|\$\d")
    lines = [l.strip() for l in text.splitlines() if l.strip() and not footer.search(l)]
    recap = plain(" ".join(lines[-3:]))
    _screen_cache[surface] = (time.time(), recap)
    return recap


def status(sess, unread_title, last_event):
    """waiting > working > done (finished, unseen) > idle > shell. Hook events beat cmux's lifecycle flag, which goes stale."""
    if not sess or not alive(sess["pid"]):
        return "done" if unread_title else "shell"
    if unread_title and unread_title.startswith("Waiting"):
        return "waiting"
    event = last_event[0] if last_event else None
    if event == "SessionStart" and sess.get("turn_role") == "assistant":
        return "waiting"  # restored after a cmux relaunch: the last reply is still unanswered
    if event == "Notification" or (event is None and sess["lifecycle"] == "needsInput"):
        return "waiting"
    if event in WORKING:
        return "working"
    return "done" if unread_title else "idle"


def state():
    raw = cmux("--json", "--id-format", "both", "tree", "--all")
    if not raw.strip():
        return {"regions": [], "edges": [], "at": time.time(), "error": "cmux is not running"}
    tree = json.loads(raw)
    agents, unread, events = agent_sessions(), notifications(), hook_events()
    edges = [json.loads(l) for l in EDGES.read_text().splitlines()] if EDGES.exists() else []
    groups = json.loads(cmux("workspace-group", "list", "--json") or '{"groups": []}')["groups"]
    group_of = {ref: g["ref"] for g in groups for ref in g["member_workspace_refs"]}
    anchors = {g["anchor_workspace_ref"] for g in groups if g["anchor_workspace_is_generated"]}  # empty header workspaces cmux made
    regions = []
    for window in tree["windows"]:
        for ws in window["workspaces"]:
            if ws["title"] == "Overworld" or ws["ref"] in anchors:
                continue
            sessions = []
            for pane in ws["panes"]:
                for sf in pane["surfaces"]:
                    if sf["type"] != "terminal":
                        continue
                    sess = agents.get(sf["id"])
                    recap = sess["recap"] if sess else ""
                    if sess and not recap and alive(sess["pid"]):
                        recap = screen_recap(sf["id"], ws["id"])
                    event = events.get(sf["id"])
                    since = event[1] if event else None
                    lane, more = subagents(sess.get("transcript")) if sess else ([], 0)
                    if event and event[0] == "SessionStart" and sess and sess.get("turn_at"):
                        since = sess["turn_at"]  # a relaunch restarts every session; age from the last real turn
                    sessions.append({"id": sf["id"], "title": sf["title"], "workspace": ws["id"],
                                  "status": status(sess, unread.get(sf["id"]), event),
                                  "since": since, "recap": recap, "ask": sess.get("ask", "") if sess else "",
                                  "full": sess.get("full", "") if sess else "",
                                  "action": cached_action(sess.get("full", "")) if sess else None, "subagents": lane, "subagents_more": more,
                                  "agent": sess["agent"] if sess else None,
                                  "cwd": sess["cwd"] if sess else None,
                                  "updated": sess["updated"] if sess else None,
                                  "here": sf.get("selected_in_pane") and pane.get("focused") and ws.get("selected")})
            if sessions:
                regions.append({"id": ws["id"], "title": ws["title"], "group": group_of.get(ws["ref"]), "sessions": sessions,
                            "scratch": ws["title"] == SCRATCH})
    return {"regions": regions, "groups": [{"id": g["ref"], "name": g["name"]} for g in groups], "edges": edges, "at": time.time()}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/state":
            self._send(200, state())
        elif self.path.startswith("/api/action?surface="):
            # On demand, for the reply view on a session the background pass skips (not "your turn").
            surface = self.path.split("=", 1)[1]
            sess = agent_sessions().get(surface)
            if not sess or not sess.get("full"):
                return self._send(404, {"error": "no reply to read"})
            try:
                prompt = (recent_prompts(sess.get("transcript"), 1) or [""])[-1]
                return self._send(200, cached_action(sess["full"]) or work_out_action(sess["full"], prompt) or {"pending": True})
            except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, RuntimeError) as e:
                print(f"{time.strftime('%H:%M:%S')} action failed: {e!r}"[:400], flush=True)
                return self._send(502, {"error": repr(e)[:300]})
        elif self.path.startswith("/api/trace?surface="):
            q = dict(kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&") if "=" in kv)
            self._send(200, trace(q["surface"], "session" if q.get("scope") == "session" else "turn", q.get("running") == "1"))
        elif self.path.startswith("/api/timeline?surface="):
            self._send(200, timeline(self.path.split("=", 1)[1]))
        elif self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/focus":
            focus(body["workspace"], body["surface"])
        elif self.path == "/api/move":
            cmux("move-surface", "--surface", body["surface"], "--workspace", body["workspace"], "--focus", "false")
        elif self.path == "/api/new":
            cmux("new-surface", "--workspace", body["workspace"], "--command", NEW_SESSION_COMMAND, "--focus", "false")
        elif self.path == "/api/rename":
            if body.get("surface"):
                cmux("rename-tab", "--workspace", body["workspace"], "--surface", body["surface"], "--", body["title"])
            else:
                cmux("workspace-action", "--workspace", body["workspace"], "--action", "rename", "--title", body["title"])
        elif self.path == "/api/autoname":
            try:
                return self._send(200, autoname(body.get("workspace")))
            except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, RuntimeError) as e:
                print(f"{time.strftime('%H:%M:%S')} autoname failed: {e!r}"[:400], flush=True)
                return self._send(502, {"error": repr(e)[:300]})
        elif self.path == "/api/group":
            if body.get("group"):
                cmux("workspace-group", "add", "--group", body["group"], "--workspace", body["workspace"])
            else:
                cmux("workspace-group", "remove", "--workspace", body["workspace"])
        elif self.path == "/api/new-workspace":
            group = ["--group", body["group"]] if body.get("group") else []
            cmux("new-workspace", "--name", "New Workspace", *group, "--command", NEW_SESSION_COMMAND, "--focus", "false")
        elif self.path == "/api/split":
            # Tab -> its own new workspace (cmux creates it ungrouped), then into the group it was dropped on.
            out = cmux("--id-format", "both", "move-tab-to-new-workspace", "--surface", body["surface"], "--workspace", body["workspace"],
                       "--title", body["title"], "--focus", "false")
            created = re.search(r"created_workspace=\S+ \(([0-9A-F-]{36})\)", out)
            if created and body.get("group"):
                cmux("workspace-group", "add", "--group", body["group"], "--workspace", created.group(1))
        elif self.path == "/api/new-group":
            cmux("workspace-group", "create", "--name", "New Group")
        elif self.path == "/api/delete-group":
            # Members move to Ungrouped. cmux only removes a generated (empty header) anchor for an anchor-only group,
            # so otherwise ungroup first and then close that empty header workspace ourselves.
            g = next(g for g in json.loads(cmux("workspace-group", "list", "--json"))["groups"] if g["ref"] == body["group"])
            if g["anchor_workspace_is_generated"] and g["member_count"] == 1:
                cmux("workspace-group", "ungroup", g["ref"], "--remove-generated-anchor")
            else:
                cmux("workspace-group", "ungroup", g["ref"])
                if g["anchor_workspace_is_generated"]:
                    cmux("close-workspace", "--workspace", g["anchor_workspace_ref"])
        elif self.path == "/api/rename-group":
            cmux("workspace-group", "rename", body["group"], "--name", body["name"])
        elif self.path == "/api/send":
            # Bracketed paste + Enter, so multi-line text arrives as one message. Errors go back to the page.
            out = subprocess.run([CMUX, "paste", "--workspace", body["workspace"], "--surface", body["surface"], "--submit", "-"],
                                 input=body["text"], capture_output=True, text=True, timeout=10,
                                 env={**os.environ, "CMUX_QUIET": "1"})
            if out.returncode:
                print(f"{time.strftime('%H:%M:%S')} send failed: {out.stderr.strip()[:300]}", flush=True)
                return self._send(502, {"error": out.stderr.strip()[:300] or f"cmux exited {out.returncode}"})
        elif self.path == "/api/close":
            cmux("close-surface", "--surface", body["surface"], "--workspace", body["workspace"])
        else:
            return self._send(404, {"error": "not found"})
        self._send(200, {"ok": True})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)  # fails fast if another copy already holds the port
    PIDFILE.write_text(str(os.getpid()))
    print(f"Overworld on http://127.0.0.1:{PORT} (pid {os.getpid()})", flush=True)
    threading.Thread(target=keep_workspace, daemon=True).start()
    threading.Thread(target=keep_actions, daemon=True).start()
    httpd.serve_forever()
