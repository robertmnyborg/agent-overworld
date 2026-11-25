#!/usr/bin/env python3
"""Agent Overworld: serves a map of cmux workspaces (regions) and tabs (sessions).

Reads cmux's own records; writes ~/.overworld/edges.jsonl (via spinoff.sh) and usage.jsonl (weekly usage readings).
Started by autostart.zsh from the first cmux shell (cmux's socket only accepts processes launched inside cmux).
While cmux is running, keeps a pinned "Overworld" workspace (browser pane on this server) in slot 1 (⌘1),
and a pinned, ungrouped "Scratch" workspace in slot 2 for one-off sessions not yet worth their own workspace.
"""
import hashlib, json, os, re, shlex, subprocess, threading, time, urllib.error, urllib.parse, urllib.request
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


_came = {"cur": None, "on_ow": False, "from": None}  # last tab focused outside the Overworld; the one focused when you switched to it


def keep_came_from():
    """Every second, note which tab has focus. On a switch into the Overworld, the tab you left is `from`, so the page can light it."""
    while True:
        try:
            tree = json.loads(cmux("--json", "--id-format", "both", "tree") or "{}")
            for window in tree.get("windows", []):
                if not window.get("active"):
                    continue
                ws = next((w for w in window["workspaces"] if w.get("selected")), None)
                if not ws:
                    continue
                if ws["title"] == "Overworld":
                    if not _came["on_ow"] and _came["cur"]:
                        _came["from"] = {"id": _came["cur"], "at": time.time()}
                    _came["on_ow"] = True
                else:
                    _came["on_ow"] = False
                    sf = next((sf for p in ws["panes"] if p.get("focused") for sf in p["surfaces"] if sf.get("selected_in_pane")), None)
                    if sf:
                        _came["cur"] = sf["id"]
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as e:
            print(f"keep_came_from: {e!r}", flush=True)
        time.sleep(1)


DOCK = Path.home() / ".overworld" / "dock.json"  # the session shown beside the map: its surface and where it lives when not docked
_dock_lock = threading.Lock()
DOCK_GRACE = 10  # seconds a fresh dock record is trusted even if the tree doesn't show the tab yet


def docked():
    return json.loads(DOCK.read_text()) if DOCK.exists() else None


def _where(surface):
    """(workspace, pane, index in pane) of a surface, from the full tree; None if it no longer exists."""
    tree = json.loads(cmux("--json", "--id-format", "both", "tree", "--all"))
    for window in tree["windows"]:
        for ws in window["workspaces"]:
            for pane in ws["panes"]:
                for n, sf in enumerate(pane["surfaces"]):
                    if sf["id"] == surface:
                        return ws, pane, n
    return None


def _settle(surface, inside_overworld):
    """cmux applies a move a moment after it answers OK: wait (up to 3s) until the tree shows the tab where it should be."""
    for _ in range(30):
        at = _where(surface)
        if at and (at[0]["title"] == "Overworld") == inside_overworld:
            return True
        time.sleep(0.1)
    return False


def _ws_by_title(title):
    return next((w for w in json.loads(cmux("--json", "list-workspaces"))["workspaces"] if w["title"] == title), None)


def dock(surface):
    """Show a session's real tab in a pane right of the map, in the Overworld workspace. A session already docked goes home first."""
    with _dock_lock:
        d = docked()
        ow = _ws_by_title("Overworld")
        if not ow:
            raise RuntimeError("no Overworld workspace")
        if d and d["surface"] == surface:
            cmux("focus-panel", "--panel", surface, "--workspace", ow["ref"])
            return {"docked": surface}
        if d:
            _undock(d)
        at = _where(surface)
        if not at:
            raise RuntimeError("that tab no longer exists")
        ws, pane, n = at
        if ws["title"] == "Overworld":
            raise RuntimeError("that tab is already in the Overworld workspace")
        checked_cmux("move-surface", "--surface", surface, "--workspace", ow["ref"], "--focus", "false")
        _settle(surface, True)
        checked_cmux("split-off", "--surface", surface, "right", "--workspace", ow["ref"], "--focus", "false")
        tmp = DOCK.with_suffix(".tmp")  # atomic: the 3s map refresh reads this file concurrently
        tmp.write_text(json.dumps({"surface": surface, "home_ws": ws["id"], "home_ws_title": ws["title"], "home_pane": pane["id"], "home_index": n, "at": time.time()}))
        tmp.replace(DOCK)
        print(f"{time.strftime('%H:%M:%S')} docked {at[1]['surfaces'][n]['title']!r} from {ws['title']}", flush=True)
        cmux("focus-panel", "--panel", surface, "--workspace", ow["ref"])
        return {"docked": surface, "home": ws["title"]}


def _undock(d):
    """Move the docked tab back to its pane (same position) or, if that pane is gone, its workspace; Scratch if that is gone too."""
    DOCK.unlink(missing_ok=True)
    at = _where(d["surface"])
    if not at or at[0]["title"] != "Overworld":
        return None  # closed, or already moved somewhere by hand
    home = _where_pane(d["home_pane"])
    if home:
        checked_cmux("move-surface", "--surface", d["surface"], "--pane", d["home_pane"], "--index", str(d["home_index"]), "--focus", "false")
        _settle(d["surface"], False)
        print(f"{time.strftime('%H:%M:%S')} sent back {d['surface'][:8]} to {d['home_ws_title']}", flush=True)
        return d["home_ws_title"]
    ws = next((w for w in json.loads(cmux("--json", "list-workspaces"))["workspaces"] if w["id"] == d["home_ws"]), None) or _ws_by_title(SCRATCH)
    checked_cmux("move-surface", "--surface", d["surface"], "--workspace", ws["ref"], "--focus", "false")
    _settle(d["surface"], False)
    print(f"{time.strftime('%H:%M:%S')} sent back {d['surface'][:8]} to {ws['title']}", flush=True)
    return ws["title"]


def _where_pane(pane_id):
    tree = json.loads(cmux("--json", "--id-format", "both", "tree", "--all"))
    return any(p["id"] == pane_id for w in tree["windows"] for ws in w["workspaces"] for p in ws["panes"])


def undock():
    with _dock_lock:
        d = docked()
        return {"home": _undock(d) if d else None}


def focus(workspace, surface):
    d = docked()
    if d and d["surface"] == surface:  # a docked tab lives in the Overworld workspace now
        ow = _ws_by_title("Overworld")
        workspace = ow["ref"] if ow else workspace
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


# ---- Context map: what fills an agent's context window on its latest model call ----
# Total is exact (the last call's input tokens). The split is estimated: system prompt and tool definitions come
# from the request shape Claude Code records; the rest from transcript text since the last compaction. Each part's
# share of characters is scaled to the exact total.
CONTEXT_LIMITS = {"claude-haiku-4-5": 200_000}  # everything current is 1M
CONTEXT_DEFAULT = 1_000_000
ATTACHMENT_KIND = {
    "instructions": "memory", "nested_memory": "memory",
    "skill_listing": "skills", "invoked_skills": "skills",
    "agent_listing_delta": "tools", "mcp_instructions_delta": "tools", "deferred_tools_delta": "tools", "deferred_tools_record": "tools",
    "file": "files", "edited_text_file": "files", "compact_file_reference": "files",
    "hook_additional_context": "hooks", "hook_blocking_error": "hooks",
}
SKIP_ATTACHMENTS = {"hook_success", "hook_cancelled", "prompt_snapshot", "queued_command"}  # not sent to the model, or already counted
ATTACHMENT_LABEL = {"instructions": "CLAUDE.md + memory index", "nested_memory": "nested CLAUDE.md", "skill_listing": "skill list",
                    "invoked_skills": "loaded skills", "agent_listing_delta": "agent list", "mcp_instructions_delta": "MCP server instructions",
                    "deferred_tools_delta": "deferred tool names", "deferred_tools_record": "tool schemas loaded by ToolSearch"}
IMAGE_CHARS = 5600  # an image costs about 1,600 tokens; counted as this many characters, not its base64 length
ITEMS_PER_BLOCK = 12
_raw_cache = {}


def _raw(path):
    """Every JSON record of a transcript (all types), cached by mtime."""
    mtime = path.stat().st_mtime
    hit = _raw_cache.get(path)
    if not hit or hit[0] != mtime:
        out = []
        with open(path, "rb") as f:
            for raw in f:
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        hit = _raw_cache[path] = (mtime, out)
    return hit[1]


def _size(value):
    """Characters a value adds to the context; images count as IMAGE_CHARS whatever their encoded size."""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(IMAGE_CHARS if isinstance(b, dict) and b.get("type") in ("image", "document") else _size(b) for b in value)
    if isinstance(value, dict):
        if value.get("type") in ("image", "document"):
            return IMAGE_CHARS
        if value.get("type") == "text":
            return len(value.get("text", ""))
        return sum(len(k) + _size(v) for k, v in value.items())
    return len(json.dumps(value, ensure_ascii=False))


def context_map(surface, agent=""):
    sess = agent_sessions().get(surface) or {}
    main = Path(sess.get("transcript") or "")
    if not main.is_file():
        return {"error": "no Claude transcript for this tab"}
    folder = main.with_suffix("") / "subagents"
    subs = sorted(folder.glob("agent-*.jsonl"), key=lambda p: -p.stat().st_mtime) if folder.is_dir() else []
    agents = [{"id": "", "name": "main session"}] + [
        {"id": p.stem, "name": (load_json(p.with_suffix(".meta.json")).get("description") or p.stem)} for p in subs]
    path = folder / f"{agent}.jsonl" if agent else main
    if agent and (not re.fullmatch(r"agent-[A-Za-z0-9]+", agent) or not path.is_file()):
        return {"error": "unknown agent"}
    records = _raw(path)
    bounds = [i for i, r in enumerate(records) if r.get("type") == "system" and r.get("subtype") == "compact_boundary"]
    start = bounds[-1] + 1 if bounds else 0
    parts = {}
    def add(kind, item, chars):
        if chars > 0:
            parts.setdefault(kind, {})[item] = parts.get(kind, {}).get(item, 0) + chars
    shape = next((r.get("shape") for r in reversed(records) if r.get("type") == "api-request-shape"), None) or {}
    for i, b in enumerate(shape.get("system") or []):
        add("system", ["header", "harness", "instructions"][i] if i < 3 else f"block {i + 1}", _size(b.get("text", "")))
    for t in shape.get("tools") or []:
        add("tools", t.get("name") or "tool", _size(t))
    tool_of = {}
    for r in records[start:]:
        kind = r.get("type")
        if kind == "attachment":
            a = r.get("attachment") or {}
            if a.get("type") in SKIP_ATTACHMENTS:
                continue
            body = {k: v for k, v in a.items() if k not in ("type", "toolUseID", "hookName", "hookEvent", "command", "durationMs", "exitCode")}
            add(ATTACHMENT_KIND.get(a.get("type"), "reminders"),
                (a.get("filename") or a.get("path") or ATTACHMENT_LABEL.get(a.get("type")) or a.get("type")).replace(str(Path.home()), "~"), _size(body))
            continue
        if kind not in ("user", "assistant"):
            continue
        msg = r.get("message") or {}
        if r.get("isCompactSummary"):
            add("summary", "compaction summary", _size(msg.get("content")))
            continue
        content = msg.get("content")
        if isinstance(content, str):
            add("chat", "your messages" if kind == "user" else "replies", len(content))
            continue
        for b in content if isinstance(content, list) else []:
            bt = b.get("type")
            if bt == "text":
                add("chat", "your messages" if kind == "user" else "replies", len(b.get("text", "")))
            elif bt == "tool_use":
                inp = b.get("input") or {}
                tool_of[b.get("id")] = (b.get("name"), inp.get("file_path") or inp.get("notebook_path"))
                add("calls", b.get("name") or "tool", _size(inp))
            elif bt == "tool_result":
                name, fpath = tool_of.get(b.get("tool_use_id"), ("tool", None))
                if fpath:
                    add("files", fpath.replace(str(Path.home()), "~"), _size(b.get("content")))
                else:
                    add("results", name or "tool", _size(b.get("content")))
    last = next((r for r in reversed(records) if r.get("type") == "assistant" and (r.get("message") or {}).get("usage")), None)
    if not last:
        return {"error": "no model call yet", "agents": agents}
    u, model = last["message"]["usage"], last["message"].get("model") or ""
    total = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    chars = sum(sum(v.values()) for v in parts.values()) or 1
    scale = total / chars
    blocks = []
    for kind, items in parts.items():
        ranked = sorted(items.items(), key=lambda kv: -kv[1])
        shown = ranked[:ITEMS_PER_BLOCK]
        rest = sum(v for _, v in ranked[ITEMS_PER_BLOCK:])
        out = [{"label": k, "tokens": round(v * scale)} for k, v in shown]
        if rest:
            out.append({"label": f"{len(ranked) - ITEMS_PER_BLOCK} more", "tokens": round(rest * scale)})
        blocks.append({"kind": kind, "tokens": round(sum(items.values()) * scale), "items": out})
    blocks.sort(key=lambda b: -b["tokens"])
    limit = next((v for k, v in CONTEXT_LIMITS.items() if model.startswith(k)), CONTEXT_DEFAULT)
    return {"agents": agents, "agent": agent, "model": model, "total": total, "limit": limit, "blocks": blocks,
            "cached": u.get("cache_read_input_tokens", 0), "at": _epoch(last["timestamp"]),
            "compactions": len(bounds), "compacted_at": _epoch(records[bounds[-1]]["timestamp"]) if bounds and records[bounds[-1]].get("timestamp") else None}


# ---- Handoffs: what each spin-off or sub-agent was given, what came back, and what it was not told ----
LOST_WINDOW = 30 * 60  # seconds before a handoff in which the parent's files count as "it was working on this"
BRIEF_CHARS = 6000
FILE_TOOLS = {"Read", "Edit", "Write", "NotebookEdit"}
# Working files only: screenshots, scratch space and spilled tool output are never worth flagging as "not passed along".
NOISE_FILE = re.compile(r"\.(png|jpe?g|gif|webp|pdf)$|/tool-results/|/scratchpad/|^/(private/)?tmp/|/\.cache/", re.I)
REF_PATH = re.compile(r"(?:~|/Users/[\w.-]+)/[\w./@+-]+[\w/]")
REF_URL = re.compile(r"https?://[^\s)>\]`'\"]+")


def _refs(text):
    """Files and links a brief names: these went along with the handoff."""
    home = str(Path.home())
    files = {m.replace(home, "~").rstrip(".,") for m in REF_PATH.findall(text or "")}
    urls = {m.rstrip(".,") for m in REF_URL.findall(text or "")}
    return [{"label": f, "kind": "file"} for f in sorted(files)] + [{"label": u, "kind": "source"} for u in sorted(urls)]


def _not_carried(transcript, at, text):
    """Files the parent read or edited in the LOST_WINDOW before `at` that the brief never names (by file name)."""
    if not transcript or not Path(transcript).is_file():
        return []
    home, seen = str(Path.home()), {}
    for e in _all_records(Path(transcript)):
        t = _epoch(e["timestamp"])
        if not at - LOST_WINDOW <= t <= at or e["type"] != "assistant":
            continue
        for b in _blocks(e):
            if b.get("type") == "tool_use" and b.get("name") in FILE_TOOLS:
                fp = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                if fp:
                    seen[fp] = b["name"]
    return [{"label": fp.replace(home, "~"), "kind": "file", "lost": True,
             "why": f"parent used it ({tool}) in the {LOST_WINDOW // 60} min before; the brief never names it"}
            for fp, tool in seen.items() if Path(fp).name not in (text or "") and not NOISE_FILE.search(fp)]


def _first_text(records, role):
    for e in records if role == "user" else reversed(records):
        if e["type"] != role:
            continue
        text = _user_text(e) if role == "user" else " ".join(b.get("text", "") for b in _blocks(e) if b.get("type") == "text")
        if text.strip():
            return text
    return ""


def handoffs(surface):
    sessions = agent_sessions()
    main = (sessions.get(surface) or {}).get("transcript")
    out = []
    for line in EDGES.read_text().splitlines() if EDGES.is_file() else []:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if surface not in (e.get("parent"), e.get("child")):
            continue
        brief_path = Path(e.get("brief") or "")
        brief = brief_path.read_text(errors="replace") if brief_path.is_file() else ""
        parent_tx = (sessions.get(e.get("parent")) or {}).get("transcript")
        out.append({"kind": "spinoff", "direction": "out" if e.get("parent") == surface else "in", "from": e.get("parent"),
                    "to": e.get("child"), "title": e.get("title") or "spin-off", "at": e.get("at"), "status": None,
                    "given": brief[:BRIEF_CHARS], "returned": None,
                    "items": _refs(brief) + _not_carried(parent_tx, e.get("at") or 0, brief)})
    folder = Path(main).with_suffix("") / "subagents" if main else None
    for p in sorted(folder.glob("agent-*.jsonl")) if folder and folder.is_dir() else []:
        meta, records = load_json(p.with_suffix(".meta.json")), _all_records(p)
        if not records:
            continue
        row = subagent_row(p)
        given = _first_text(records, "user")
        at = _epoch(records[0]["timestamp"])
        out.append({"kind": "subagent", "direction": "out", "from": surface, "to": None,
                    "title": meta.get("description") or p.stem, "type": meta.get("agentType") or "agent", "at": at, "status": row["status"],
                    "given": given[:BRIEF_CHARS], "returned": _first_text(records, "assistant")[:BRIEF_CHARS] if row["status"] == "done" else None,
                    "items": _refs(given) + _not_carried(main, at, given)})
    out.sort(key=lambda h: -(h["at"] or 0))
    return {"handoffs": out}


STEPS = 6  # recent steps shown when an inbox row unfolds


def recent_steps(surface):
    """The last few things a session did: tool calls, replies and prompts, newest first."""
    path = Path((agent_sessions().get(surface) or {}).get("transcript") or "")
    if not path.is_file():
        return {"steps": []}
    steps = []
    for e in reversed(_records(path, 400_000)):
        t = e["timestamp"]
        if e["type"] == "assistant":
            for b in reversed(_blocks(e)):
                if b.get("type") == "tool_use":
                    steps.append({"at": t, "kind": "tool", "label": _tool_label(b)})
                elif b.get("type") == "text" and b.get("text", "").strip():
                    steps.append({"at": t, "kind": "reply", "label": plain(b["text"])[:160]})
        elif _is_prompt(e):
            steps.append({"at": t, "kind": "prompt", "label": plain(_user_text(e))[:160]})
        if len(steps) >= STEPS:
            break
    return {"steps": steps[:STEPS]}


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
            out[s["surfaceId"]] = {"agent": "agy", "lifecycle": s.get("agentLifecycle"), "recap": text, "transcript": s.get("transcriptPath"),
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


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"  # what the desktop app's usage meter reads
USAGE_LOG = Path.home() / ".overworld" / "usage.jsonl"  # one reading per poll, for the weekly pace line
USAGE_EVERY = 300  # seconds between polls
WEEK = 7 * 86400
_usage = {"reading": None, "error": None, "at": None}


def read_usage():
    """Current weekly limits from Claude's usage endpoint, with the Claude Code login token from the Keychain (Claude Code refreshes it)."""
    creds = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                           capture_output=True, text=True, timeout=10, check=True).stdout
    token = json.loads(creds)["claudeAiOauth"]["accessToken"]
    req = urllib.request.Request(USAGE_URL, headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    limits = [{"kind": l["kind"], "label": (l.get("scope") or {}).get("model", {}).get("display_name") or "All models",
               "percent": l["percent"], "resets_at": l["resets_at"], "active": l["is_active"]}
              for l in data.get("limits") or [] if l.get("group") == "weekly"]
    return {"at": time.time(), "weekly": limits}


def keep_usage():
    """Background: poll the usage endpoint and log every reading to USAGE_LOG."""
    while True:
        try:
            reading = read_usage()
            _usage.update(reading=reading, error=None, at=reading["at"])
            with USAGE_LOG.open("a") as f:
                f.write(json.dumps(reading) + "\n")
        except (subprocess.SubprocessError, urllib.error.URLError, json.JSONDecodeError, KeyError, OSError) as e:
            _usage.update(error=repr(e)[:300], at=time.time())
            print(f"{time.strftime('%H:%M:%S')} usage poll failed: {e!r}"[:400], flush=True)
        time.sleep(USAGE_EVERY)


def usage():
    """Latest weekly reading plus this week's history of the all-models limit (readings sharing its reset time)."""
    reading = _usage["reading"]
    main_limit = next((l for l in reading["weekly"] if l["kind"] == "weekly_all"), None) if reading else None
    history = []
    if main_limit and USAGE_LOG.exists():
        week_start = _epoch(main_limit["resets_at"]) - WEEK
        for line in USAGE_LOG.read_text().splitlines():
            row = json.loads(line)
            hit = next((l for l in row["weekly"] if l["kind"] == "weekly_all"), None)
            if hit and row["at"] >= week_start:
                history.append([row["at"], hit["percent"]])
    return {"weekly": reading["weekly"] if reading else [], "history": history, "error": _usage["error"], "at": _usage["at"]}


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
    dk = docked()  # read before the tree: the dock record is written after the move, so this tree must already show it docked
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
    home = None  # the docked tab, shown under the workspace it came from
    for window in tree["windows"]:
        for ws in window["workspaces"]:
            if ws["title"] == "Overworld" and dk:
                home = next(((sf, pane, ws) for pane in ws["panes"] for sf in pane["surfaces"] if sf["id"] == dk["surface"]), None)
    if dk and not home and time.time() - dk["at"] > DOCK_GRACE:
        if _dock_lock.acquire(blocking=False):  # mid-dock the tab is briefly elsewhere; only clear when no dock is running
            try:
                if docked() == dk:
                    DOCK.unlink(missing_ok=True)  # the docked tab was closed or moved away by hand
            finally:
                _dock_lock.release()
        dk = None
    for window in tree["windows"]:
        for ws in window["workspaces"]:
            if ws["title"] == "Overworld" or ws["ref"] in anchors:
                continue
            panes = ws["panes"]
            if home and ws["id"] == dk["home_ws"]:
                panes = panes + [{**home[1], "surfaces": [home[0]], "docked": True}]
            sessions = []
            for pane in panes:
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
                                  "cwd": sess["cwd"] if sess else None, "transcript": sess.get("transcript") if sess else None,
                                  "ws_ref": ws["ref"], "ws_title": ws["title"],
                                  "updated": sess["updated"] if sess else None,
                                  "docked": bool(pane.get("docked")),
                                  "here": sf.get("selected_in_pane") and pane.get("focused") and ws.get("selected")})
            if sessions:
                regions.append({"id": ws["id"], "title": ws["title"], "group": group_of.get(ws["ref"]), "sessions": sessions,
                            "scratch": ws["title"] == SCRATCH})
    return {"regions": regions, "groups": [{"id": g["ref"], "name": g["name"]} for g in groups], "edges": edges, "at": time.time(),
            "came_from": _came["from"], "docked": dk["surface"] if dk else None}


CAPTURES = Path.home() / ".overworld" / "captures"  # one brief per new capture; the session reads it as its first prompt
THREADS = Path.home() / ".overworld" / "threads.json"  # Slack thread key -> surface that owns it
SLACK_LINK = re.compile(r"https://[\w-]+\.slack\.com/archives/(\w+)/p(\d{10})(\d{6})(\S*)")
SENDER_STEP = ("Once you have read the source, record who is asking (their name as written in Slack, email or Jira), unless the note is "
               "Robert's own idea with no one asking: curl -s -X POST http://127.0.0.1:7717/api/work/sender -d "
               "\"{\\\"surface\\\": \\\"$CMUX_SURFACE_ID\\\", \\\"person\\\": \\\"<Name>\\\", \\\"ask\\\": \\\"<what they want, max 12 words>\\\"}\"")
CAPTURE_RULES = """# Quick capture {at}

Robert sent this with the capture hotkey:

> {text}

1. If the note has a Slack, Gmail, or Jira link, read the source first with your connector. For Slack, read the whole thread, plus the channel from that message onward
   (at least 20 messages or 24 hours), because replies are often unthreaded.
   If it names a screenshot file, open it with Read first.
2. File this tab, always, even when the note says to do nothing else. Groups (Work, Personal) are folders, not workspaces:
   never move a tab into a group itself, only into a workspace listed under it.
   a. A workspace below fits: move there.
   b. None fits, but the work clearly belongs to a group: create a new workspace in that group, named for the work (2-4 words), and move there:
      cmux new-workspace --group "<group ref>" --name "<name>" --focus false   (prints the new workspace ref)
   c. Neither: stay in Scratch.
   Then run:
   cmux move-surface --surface "$CMUX_SURFACE_ID" --workspace "<workspace ref>" --focus false
   cmux rename-tab --surface "$CMUX_SURFACE_ID" "<2-4 word title>"
   Never rename a workspace or group.
3. {sender}
4. Do what the note asks. If it asks for nothing specific, summarize the source in 3 lines and say what you would do next.
   Never post to Slack, email, or Jira without Robert's yes for that post.

Workspaces by group (ref | title | tabs):
{workspaces}
"""


def slack_thread(text):
    """Slack link -> 'slack:<channel>:<thread ts>'. A reply link carries thread_ts; a top-level link's own ts is the thread."""
    m = SLACK_LINK.search(text)
    if not m:
        return None
    reply = re.search(r"thread_ts=(\d+\.\d+)", m.group(4))
    return f"slack:{m.group(1)}:{reply.group(1) if reply else m.group(2) + '.' + m.group(3)}"


def capture_listing(tree):
    """Workspaces grouped under their group header, with group anchors (the folder itself) left out so a session can't file into one."""
    groups = json.loads(cmux("workspace-group", "list", "--json") or '{"groups": []}')["groups"]
    anchors = {g["anchor_workspace_ref"] for g in groups if g["anchor_workspace_is_generated"]}
    group_of = {ref: g for g in groups for ref in g["member_workspace_refs"]}
    sections = {g["ref"]: [f"## Group {g['name']} (group ref {g['ref']})"] for g in groups}
    loose = ["## Not in a group"]
    for w in tree["windows"]:
        for ws in w["workspaces"]:
            if ws["title"] == "Overworld" or ws["ref"] in anchors:
                continue
            line = f"{ws['ref']} | {ws['title']} | " + ", ".join(sf["title"] for p in ws["panes"] for sf in p["surfaces"])
            g = group_of.get(ws["ref"])
            (sections[g["ref"]] if g else loose).append(line)
    return "\n".join("\n".join(lines) for lines in [*sections.values(), loose])


def capture(text, route=True):
    """New note -> the tab that owns its Slack thread, else the work item it matches, else a new Claude tab in Scratch that
    files itself. route=False skips both matches (used when Robert says a routing was wrong and wants a fresh tab)."""
    key = slack_thread(text)
    threads = json.loads(THREADS.read_text()) if THREADS.exists() else {}
    tree = json.loads(cmux("--json", "--id-format", "both", "tree", "--all"))
    surfaces = {sf["id"]: (ws, sf) for w in tree["windows"] for ws in w["workspaces"] for p in ws["panes"] for sf in p["surfaces"]}
    owner = threads.get(key) if key and route else None
    if owner in surfaces:
        ws, sf = surfaces[owner]
        out = subprocess.run([CMUX, "paste", "--workspace", ws["id"], "--surface", owner, "--submit", "-"],
                             input=f"Follow-up capture on this same Slack thread: {text}\nRe-read the thread and the channel after it for anything new, then continue.",
                             capture_output=True, text=True, timeout=10, env={**os.environ, "CMUX_QUIET": "1"})
        if out.returncode:
            raise RuntimeError(f"could not send to {sf['title']}: {out.stderr.strip()[:200]}")
        w = load_work()
        it = next((i for i in w["items"].values() if any(m.get("workspace") == ws["id"] and m.get("title") == sf["title"] for m in i.get("meta", {}).values())), None)
        return {"routed": "continued", "message": f"Sent to {ws['title']} / {sf['title']} (same Slack thread)", "reason": "same Slack thread",
                "surface": owner, "workspace": ws["id"], "item": it and it["id"], "item_title": it and it["title"], "key": key}
    item, reason = route_capture(text, key) if route else (None, "")
    if item:
        return {**deliver_to_item(item, text, key), "reason": reason, "item": item["id"], "item_title": item["title"], "key": key}
    scratch = next(ws for w in tree["windows"] for ws in w["workspaces"] if ws["title"] == SCRATCH)
    listing = capture_listing(tree)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    brief = CAPTURES / f"{time.strftime('%Y-%m-%d-%H%M%S')}.md"
    brief.write_text(CAPTURE_RULES.format(at=time.strftime("%Y-%m-%d %H:%M"), text=text.replace("\n", "\n> "), workspaces=listing, sender=SENDER_STEP))
    out = cmux("--id-format", "uuids", "new-surface", "--workspace", scratch["id"], "--working-directory", str(Path.home()),
               "--command", f'{NEW_SESSION_COMMAND} "Read {brief} and follow it."', "--focus", "false")
    surface = re.search(r"[0-9A-F]{8}-[0-9A-F-]{27}", out)
    if not surface:
        raise RuntimeError(f"new-surface gave no surface id: {out[:200]}")
    cmux("rename-tab", "--workspace", scratch["id"], "--surface", surface.group(0), "--",
         "Capture: " + (re.sub(r"https?://\S+|Screenshot: \S+", "", text).strip()[:30] or ("Slack thread" if key else "link")))
    if key:
        threads[key] = surface.group(0)
        THREADS.write_text(json.dumps(threads, indent=1))
    print(f"{time.strftime('%H:%M:%S')} capture: {key or 'note'} -> {surface.group(0)} ({brief.name})", flush=True)
    return {"routed": "new", "message": "No work item matched: started a new tab. It will file itself.", "surface": surface.group(0),
            "workspace": scratch["id"], "reason": "no work item matched" if route else "you asked for a new tab", "key": key}


# ---------- Work items: the durable unit of work; tabs are disposable workers attached to one ----------
WORK = Path.home() / ".overworld" / "work.json"
_work_lock = threading.RLock()
SORT_EVERY = 30  # seconds between passes that attach new tabs to work items
SEED_TIMEOUT = 240
WORK_ITEM = {"type": "object", "required": ["key", "title", "goal", "people", "group"], "properties": {
    "key": {"type": "string"}, "title": {"type": "string"}, "goal": {"type": "string"}, "group": {"type": "string"},
    "people": {"type": "array", "items": {"type": "string"}}}}
SORT_SCHEMA = {"type": "object", "required": ["new_items", "assign"], "properties": {
    "new_items": {"type": "array", "items": WORK_ITEM},
    "assign": {"type": "array", "items": {"type": "object", "required": ["tab", "item"], "properties": {
        "tab": {"type": "string"}, "item": {"type": "string"}}}}}}
SORT_RULES = """Robert runs many AI agent sessions (tabs). Group them into WORK ITEMS. A work item is one piece of work with an outcome
someone cares about: a deliverable, a decision, a fix, a person's request. It outlives any single tab.
- Put tabs in the same item when they serve the same outcome, even if they sit in different workspaces or use different words.
- Keep items apart when the outcomes differ, even if the topic is related (a pricing doc and a pricing bug are two items).
- A person is NOT an item by themselves. Work for or about a person is an item named for that work; list the person in people.
- Existing items are given with ids. Prefer an existing item; create a new item only when no existing one fits.
- title: 2-5 words, the outcome, Title Case, concrete nouns. goal: one sentence, what done looks like. people: first names
  (or names as written) of people the work is for, waits on, or involves; [] if none. Never list Robert.
- new_items keys: "n1", "n2", ... Every tab key given must appear exactly once in assign, with an existing item id or a new key.
- group: the id of the goal group (given, if any) that a new item serves, or "" if none fits or none are given.
Input:
"""
PARK_SCHEMA = {"type": "object", "required": ["note", "next", "waits_on"], "properties": {
    "note": {"type": "string"}, "next": {"type": "string"}, "waits_on": {"type": "string"}}}
PARK_RULES = """Robert is parking a piece of work: its agent tabs will close and he will come back to it later, possibly weeks later.
From the item and the end of each tab's conversation, write what he needs to pick it up cold.
- note: where it stands, max 2 sentences. Name artifacts (PR numbers, doc titles, branches) and numbers from the conversation.
- next: the next step as one imperative sentence, max 20 words, naming who does it.
- waits_on: "Robert" if the next step is his, a person's name if it waits on them, or "nobody" if the work is finished.
Plain words, no markdown, no quotes. Input:
"""
ROUTE_SCHEMA = {"type": "object", "required": ["item", "confident", "reason"], "properties": {
    "item": {"type": "string"}, "confident": {"type": "boolean"}, "reason": {"type": "string"}}}
ROUTE_RULES = """Robert captured a note (often a Slack link plus a few words). Pick the work item it belongs to.
Return item = that item's id, or "new" when no item clearly fits. confident = true only when the note plainly continues that item's
work (same deliverable, same person asking about the same thing). Related topic alone is not enough.
reason: why, max 10 words, naming the shared person or deliverable (e.g. "Chace asking about the same OPTECH reports"). Input:
"""


def model_call(rules, payload, schema, model="haiku", timeout=NAME_TIMEOUT):
    """One headless structured call (no tools, settings or MCP). Returns (structured output, cost)."""
    cmd = [*NAMER, "--json-schema", json.dumps(schema)]
    cmd[cmd.index("--model") + 1] = model
    out = subprocess.run(cmd, input=rules + json.dumps(payload, indent=1), capture_output=True, text=True, timeout=timeout,
                         cwd="/tmp", env={**os.environ, "MAX_THINKING_TOKENS": "0"})
    result = json.loads(out.stdout)
    if result.get("is_error"):
        raise RuntimeError(result.get("result", "model call failed"))
    return result["structured_output"], result.get("total_cost_usd") or 0


def load_work():
    return json.loads(WORK.read_text()) if WORK.exists() else {"seeded": False, "items": {}, "skip": [], "proposal": None}


def save_work(w):
    tmp = WORK.with_suffix(".tmp")
    tmp.write_text(json.dumps(w, indent=1))
    tmp.replace(WORK)


def new_id():
    return "w" + hashlib.sha1(f"{time.time()}{os.urandom(4)}".encode()).hexdigest()[:8]


def live_tabs(st):
    """transcript -> session dict, for every agent tab on the map with a transcript."""
    return {t["transcript"]: t for r in st["regions"] for t in r["sessions"] if t.get("agent") and t.get("transcript")}


def tab_brief(t):
    prompts = recent_prompts(t["transcript"]) if t["agent"] == "claude" else agy_turns(t["transcript"])[0]
    return {"title": t["title"], "status": t["status"], "recent_prompts": prompts, "last_reply": (t.get("recap") or "")[:300]}


def remember_tab(item, t, regions_by_ws):
    item.setdefault("meta", {})[t["transcript"]] = {
        "title": t["title"], "workspace": t["workspace"], "workspace_title": regions_by_ws.get(t["workspace"], ""),
        "cwd": t.get("cwd"), "agent": t["agent"], "seen": time.time()}


def owner_of(w, transcript):
    return next((i for i in w["items"].values() if transcript in i["sessions"]), None)


def thread_keys_for(surface):
    threads = json.loads(THREADS.read_text()) if THREADS.exists() else {}
    return [k for k, v in threads.items() if v == surface]


def sort_tabs(tabs, items, model="haiku", timeout=NAME_TIMEOUT):
    """tabs: [session dict]. items: existing items. -> (new items by key, {transcript: item id or new key}, cost)."""
    keyed = {f"t{i}": t for i, t in enumerate(tabs)}
    groups = load_work().get("groups", {})
    payload = {"existing_items": [{"id": i["id"], "title": i["title"], "goal": i["goal"], "people": i["people"]} for i in items],
               "goal_groups": [{"id": g["id"], "title": g["title"]} for g in groups.values()],
               "tabs": {k: tab_brief(t) for k, t in keyed.items()}}
    out, cost = model_call(SORT_RULES, payload, SORT_SCHEMA, model=model, timeout=timeout)
    new = {n["key"]: n for n in out["new_items"]}
    valid = {i["id"] for i in items} | set(new)
    assign = {keyed[a["tab"]]["transcript"]: a["item"] for a in out["assign"] if a["tab"] in keyed and a["item"] in valid}
    return new, assign, cost


def seed_work():
    """Cluster every agent tab into proposed work items for Robert to review. Nothing is written as an item yet."""
    st = state()
    tabs = list(live_tabs(st).values())
    new, assign, cost = sort_tabs(tabs, [], model="sonnet", timeout=SEED_TIMEOUT)
    by_t = {t["transcript"]: t for t in tabs}
    proposal = [{**n, "tabs": [tr for tr, k in assign.items() if k == key]} for key, n in new.items()]
    proposal = [p for p in proposal if p["tabs"]]
    unsorted = [tr for tr in by_t if tr not in assign]
    with _work_lock:
        w = load_work()
        w["proposal"] = {"items": proposal, "unsorted": unsorted, "at": time.time(), "cost": cost}
        save_work(w)
    print(f"{time.strftime('%H:%M:%S')} work seed: {len(tabs)} tabs -> {len(proposal)} items, {len(unsorted)} unsorted, ${cost:.3f}", flush=True)
    return w["proposal"]


def accept_seed(items):
    """items: [{title, goal, people, tabs: [transcript]}] as edited on the review screen."""
    st = state()
    live, ws_title = live_tabs(st), {r["id"]: r["title"] for r in st["regions"]}
    with _work_lock:
        w = load_work()
        for p in items:
            if not p["tabs"]:
                continue
            item = {"id": new_id(), "title": p["title"], "goal": p.get("goal", ""), "people": p.get("people", []), "sources": [],
                    "state": "active", "note": "", "next": "", "waits_on": "", "sessions": [], "created": time.time(), "updated": time.time()}
            for tr in p["tabs"]:
                prev = owner_of(w, tr)
                if prev:
                    prev["sessions"].remove(tr)
                item["sessions"].append(tr)
                if tr in live:
                    remember_tab(item, live[tr], ws_title)
                    item["sources"] += thread_keys_for(live[tr]["id"])
            w["items"][item["id"]] = item
        w["seeded"], w["proposal"] = True, None
        save_work(w)
    return {"items": len(w["items"])}


def keep_work():
    """Background: attach tabs that are on no item (new captures, new tabs) to an item, or start a new one flagged "new"."""
    tried = {}  # transcript -> prompt count when last sorted, so a failed or empty tab isn't re-sent every pass
    while True:
        time.sleep(SORT_EVERY)
        try:
            if not load_work()["seeded"]:
                continue
            st = state()
            live, ws_title = live_tabs(st), {r["id"]: r["title"] for r in st["regions"]}
            with _work_lock:
                w = load_work()
                for item in w["items"].values():  # keep each session's last known workspace, cwd and title for resume
                    for tr in item["sessions"]:
                        if tr in live:
                            remember_tab(item, live[tr], ws_title)
                save_work(w)
                taken = {tr for i in w["items"].values() for tr in i["sessions"]} | set(w["skip"])
            todo = []
            for tr, t in live.items():
                if tr in taken:
                    continue
                n = len(recent_prompts(tr)) if t["agent"] == "claude" else len(agy_turns(tr)[0])
                if n and tried.get(tr) != n:
                    tried[tr] = n
                    todo.append(t)
            if not todo:
                continue
            active = [i for i in w["items"].values() if i["state"] != "done"]
            new, assign, cost = sort_tabs(todo, active)
            with _work_lock:
                w = load_work()
                made = {}
                avoid = w.get("avoid", {})  # surface -> item Robert moved a capture out of; never file that tab back there
                for tr, target in assign.items():
                    if owner_of(w, tr):
                        continue  # attached by hand while the call ran
                    if avoid.get(live[tr]["id"]) == target:
                        key = "avoid:" + tr
                        new[key] = {"title": live[tr]["title"], "goal": "", "people": [], "group": ""}
                        target = key
                    if target in new:
                        if target not in made:
                            n = new[target]
                            made[target] = {"id": new_id(), "title": n["title"], "goal": n["goal"], "people": n["people"], "sources": [],
                                            "state": "active", "note": "", "next": "", "waits_on": "", "sessions": [], "new": True,
                                            "created": time.time(), "updated": time.time(),
                                            "group": n["group"] if n.get("group") in w.get("groups", {}) else ""}
                            w["items"][made[target]["id"]] = made[target]
                        item = made[target]
                    elif target in w["items"]:
                        item = w["items"][target]
                        if item["state"] == "parked":
                            item["state"] = "active"  # a live tab came back to parked work
                    else:
                        continue
                    item["sessions"].append(tr)
                    remember_tab(item, live[tr], ws_title)
                    item["sources"] = sorted(set(item["sources"]) | set(thread_keys_for(live[tr]["id"])))
                    pend = w.get("pending_senders", {}).pop(live[tr]["id"], None)
                    if pend:
                        add_sender(item, pend)
                    item["updated"] = time.time()
                save_work(w)
            print(f"{time.strftime('%H:%M:%S')} work sort: {len(todo)} tabs, {len(made)} new items, ${cost:.4f}", flush=True)
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, RuntimeError, OSError) as e:
            print(f"{time.strftime('%H:%M:%S')} work sort failed: {e!r}"[:400], flush=True)


def work_view(st):
    """Items with their live tabs joined in (surface ids), for the page."""
    w = load_work()
    live = live_tabs(st)
    rank = {"waiting": 0, "working": 1, "done": 2, "idle": 3, "shell": 4}
    items = []
    for i in w["items"].values():
        tabs = [live[tr] for tr in i["sessions"] if tr in live]
        statuses = [t["status"] for t in tabs]
        roll = min(statuses, key=lambda s: rank.get(s, 9)) if statuses else "none"
        waiting = [t for t in tabs if t["status"] == "waiting"]
        nxt, needs = i["next"], False
        if waiting:
            a = waiting[0].get("action")
            needs = not (a and a.get("kind") == "none")  # a finished reply that asks nothing isn't "needs you"
            nxt = (a and a.get("action")) or waiting[0].get("ask") or nxt
        items.append({k: i[k] for k in ("id", "title", "goal", "people", "state", "note", "waits_on", "updated")} |
                     {"group": i.get("group", ""), "asked_by": i.get("asked_by", [])[-3:]} |
                     {"next": nxt, "needs": needs, "tabs": [t["id"] for t in tabs], "status": roll, "new": i.get("new", False),
                      "sessions": len(i["sessions"]), "resumable": any(m["agent"] == "claude" for m in i.get("meta", {}).values()),
                      "where": sorted({m["workspace_title"] for m in i.get("meta", {}).values() if m.get("workspace_title")})})
    taken = {tr for i in w["items"].values() for tr in i["sessions"]}
    unsorted = [t["id"] for tr, t in live.items() if tr not in taken]
    prop = w.get("proposal")
    if prop:  # page needs tab ids and titles, not transcript paths
        prop = {**prop, "items": [{**p, "tabs": [{"transcript": tr, "id": live[tr]["id"]} for tr in p["tabs"] if tr in live]} for p in prop["items"]],
                "unsorted": [{"transcript": tr, "id": live[tr]["id"]} for tr in prop["unsorted"] if tr in live]}
    groups = sorted(w.get("groups", {}).values(), key=lambda g: g.get("order", 0))
    return {"seeded": w["seeded"], "items": items, "unsorted": unsorted, "proposal": prop, "groups": groups}


def checked_cmux(*args):
    out = subprocess.run([CMUX, *args], capture_output=True, text=True, timeout=10, env={**os.environ, "CMUX_QUIET": "1"})
    if out.returncode:
        raise RuntimeError(f"cmux {args[0]}: {(out.stderr or out.stdout).strip()[:200]}")
    return out.stdout


def park(item_id):
    """Write where the work stands and its next step, then close its tabs. Transcripts stay, so it can be resumed."""
    st = state()
    live = live_tabs(st)
    with _work_lock:
        item = load_work()["items"][item_id]
    tabs = [live[tr] for tr in item["sessions"] if tr in live]
    payload = {"item": {"title": item["title"], "goal": item["goal"], "people": item["people"]},
               "tabs": [{**tab_brief(t), "last_reply": (t.get("full") or t.get("recap") or "")[-3000:]} for t in tabs]}
    if tabs:
        out, cost = model_call(PARK_RULES, payload, PARK_SCHEMA)
    else:
        out, cost = {"note": item["note"], "next": item["next"], "waits_on": item["waits_on"]}, 0
    with _work_lock:
        w = load_work()
        it = w["items"][item_id]
        it.update(out, state="parked", updated=time.time(), parked_at=time.time())
        it.pop("new", None)
        save_work(w)
    closed = []
    for t in tabs:
        checked_cmux("close-surface", "--surface", t["id"], "--workspace", t["workspace"], "--force")
        closed.append(t["title"])
    print(f"{time.strftime('%H:%M:%S')} work park: {item['title']} | closed {len(closed)} | ${cost:.4f}", flush=True)
    return {"note": out["note"], "next": out["next"], "closed": closed}


def resume(item_id, prompt="", transcript=None):
    """Reopen one of the item's Claude sessions (the most recent unless `transcript` names one) in its last workspace (Scratch if that's gone), in its own cwd."""
    with _work_lock:
        item = load_work()["items"][item_id]
    metas = sorted(((tr, m) for tr, m in item.get("meta", {}).items() if m["agent"] == "claude" and Path(tr).is_file()),
                   key=lambda x: x[1]["seen"], reverse=True)
    if transcript:
        metas = [x for x in metas if x[0] == transcript]
    if not metas:
        raise RuntimeError("no Claude session to resume on this item")
    tr, m = metas[0]
    tree = json.loads(cmux("--json", "--id-format", "both", "tree", "--all"))
    wss = {ws["id"]: ws for w in tree["windows"] for ws in w["workspaces"]}
    ws = wss.get(m["workspace"]) or next(x for x in wss.values() if x["title"] == SCRATCH)
    cmd = f"{NEW_SESSION_COMMAND} --resume {Path(tr).stem}" + (f" {shlex.quote(prompt)}" if prompt else "")
    out = checked_cmux("--id-format", "uuids", "new-surface", "--workspace", ws["id"], "--working-directory", m.get("cwd") or str(Path.home()),
                       "--command", cmd, "--focus", "false")
    surface = re.search(r"[0-9A-F]{8}-[0-9A-F-]{27}", out)
    if not surface:
        raise RuntimeError(f"new-surface gave no surface id: {out[:200]}")
    cmux("rename-tab", "--workspace", ws["id"], "--surface", surface.group(0), "--", m["title"])
    with _work_lock:
        w = load_work()
        w["items"][item_id].update(state="active", updated=time.time())
        save_work(w)
    print(f"{time.strftime('%H:%M:%S')} work resume: {item['title']} -> {ws['title']} / {m['title']}", flush=True)
    return {"workspace": ws["id"], "surface": surface.group(0), "title": m["title"], "workspace_title": ws["title"]}


def work_edit(body):
    """update / merge / attach / skip, all small edits to work.json."""
    with _work_lock:
        w = load_work()
        op = body["op"]
        if op == "update":
            it = w["items"][body["id"]]
            for k in ("title", "goal", "people", "state"):
                if k in body:
                    it[k] = body[k]
            it.pop("new", None)
            it["updated"] = time.time()
        elif op == "merge":  # from -> into
            if body["from"] == body["into"] or body["into"] not in w["items"]:
                raise KeyError(body["into"])
            a, b = w["items"].pop(body["from"]), w["items"][body["into"]]
            b["sessions"] += [s for s in a["sessions"] if s not in b["sessions"]]
            b["people"] += [p for p in a["people"] if p not in b["people"]]
            b["sources"] = sorted(set(b["sources"]) | set(a["sources"]))
            b.setdefault("meta", {}).update(a.get("meta", {}))
            if b["state"] != "active" and a["state"] == "active":
                b["state"] = "active"
            b.pop("new", None)
            b["updated"] = time.time()
        elif op in ("attach", "skip", "split"):  # one tab: onto an item, out of all items, or into its own new item
            tr = body["transcript"]
            if not tr:
                raise KeyError("transcript")
            prev = owner_of(w, tr)
            if prev:
                prev["sessions"].remove(tr)
                meta = prev.get("meta", {}).pop(tr, None)
            else:
                meta = None
            if tr in w["skip"]:
                w["skip"].remove(tr)
            if op == "skip":
                w["skip"].append(tr)
            else:
                if op == "split":
                    it = {"id": new_id(), "title": body.get("title") or "New work", "goal": "", "people": [], "sources": [],
                          "state": "active", "note": "", "next": "", "waits_on": "", "sessions": [], "created": time.time(), "updated": time.time()}
                    w["items"][it["id"]] = it
                else:
                    it = w["items"][body["item"]]
                it["sessions"].append(tr)
                if meta:
                    it.setdefault("meta", {})[tr] = meta
                it["updated"] = time.time()
        elif op == "group-set":  # item -> goal group ("" = none)
            w["items"][body["id"]]["group"] = body["group"] if body["group"] in w.get("groups", {}) else ""
        elif op == "group-rename":
            w["groups"][body["group"]]["title"] = body["title"]
        elif op == "group-new":
            gid = "g" + new_id()[1:]
            w.setdefault("groups", {})[gid] = {"id": gid, "title": body["title"], "order": len(w["groups"])}
            if body.get("id"):
                w["items"][body["id"]]["group"] = gid
        elif op == "drop-proposal":
            w["proposal"] = None
        else:
            raise KeyError(op)
        save_work(w)
    return {"ok": True}


def route_capture(text, key):
    """Capture -> an existing work item, or None. Slack thread already on an item wins; else one Haiku call."""
    w = load_work()
    if not w["seeded"]:
        return None, ""
    items = [i for i in w["items"].values() if i["state"] != "done"]
    if key:
        hit = next((i for i in items if key in i["sources"]), None)
        if hit:
            return hit, "same Slack thread"
    if not items:
        return None, ""
    payload = {"note": text, "items": [{"id": i["id"], "title": i["title"], "goal": i["goal"], "people": i["people"],
                                        "state": i["state"], "next": i["next"]} for i in items]}
    out, cost = model_call(ROUTE_RULES, payload, ROUTE_SCHEMA)
    print(f"{time.strftime('%H:%M:%S')} capture route: {out} ${cost:.4f}", flush=True)
    hit = w["items"].get(out["item"]) if out["confident"] else None
    return hit, out["reason"]


def deliver_to_item(item, text, key):
    """Send a capture to the item's best live Claude tab, or resume the item with the note as the first prompt."""
    st = state()
    live = live_tabs(st)
    rank = {"waiting": 0, "idle": 1, "done": 2, "working": 3}
    tabs = sorted((live[tr] for tr in item["sessions"] if tr in live and live[tr]["status"] in rank and live[tr]["agent"] == "claude"),
                  key=lambda t: rank[t["status"]])
    note = f"New capture for this work ({item['title']}): {text}\nRead the source first if it has a link. {SENDER_STEP}\nThen continue."
    with _work_lock:
        w = load_work()
        if key and key not in w["items"][item["id"]]["sources"]:
            w["items"][item["id"]]["sources"].append(key)
            save_work(w)
    if tabs:
        t = tabs[0]
        out = subprocess.run([CMUX, "paste", "--workspace", t["workspace"], "--surface", t["id"], "--submit", "-"], input=note,
                             capture_output=True, text=True, timeout=10, env={**os.environ, "CMUX_QUIET": "1"})
        if out.returncode:
            raise RuntimeError(f"could not send to {t['title']}: {out.stderr.strip()[:200]}")
        return {"routed": "continued", "message": f"Sent to {item['title']} ({t['title']})", "surface": t["id"], "workspace": t["workspace"]}
    r = resume(item["id"], note)
    return {"routed": "resumed", "message": f"Reopened {item['title']} in {r['workspace_title']}", "surface": r["surface"], "workspace": r["workspace"]}


GROUPS_SCHEMA = {"type": "object", "required": ["groups", "assign"], "properties": {
    "groups": {"type": "array", "items": {"type": "object", "required": ["key", "title"], "properties": {
        "key": {"type": "string"}, "title": {"type": "string"}}}},
    "assign": {"type": "array", "items": {"type": "object", "required": ["item", "group"], "properties": {
        "item": {"type": "string"}, "group": {"type": "string"}}}}}}
GROUPS_RULES = """Robert's work items are listed below. Group them by the GOAL they serve: the larger objective the outcome moves forward,
the answer to "why does this work exist?". Not by who asked, and not by tool or domain.
- As FEW groups as honestly fit, usually 3 to 5. A group is a business or life objective that many items move forward,
  e.g. "Grow Discover revenue", "AI search visibility", "My agent tooling", "Next role". Title Case, 2-5 words.
- A tool, system, data source or activity is never a goal (not "Parrot Automation", "Call Data", "Analytics", "Collateral").
  Ask what it is FOR: a sales-rep report, a contact refresh and a call-data feed all serve the same sales objective.
- Test each group: would Robert say "this quarter I'm trying to <group title>"? If not, merge it into the objective it serves.
- No "Misc" or "Other" unless an item truly serves nothing else.
- Every item id appears exactly once in assign. Group keys: "g1", "g2", ...
Input:
"""


def propose_groups():
    """One Sonnet call: goal groups for every not-done item. Replaces any existing groups (Robert can rename and move after)."""
    with _work_lock:
        w = load_work()
    items = [i for i in w["items"].values() if i["state"] != "done"]
    payload = {"items": [{"id": i["id"], "title": i["title"], "goal": i["goal"], "people": i["people"],
                          "workspaces": sorted({m.get("workspace_title", "") for m in i.get("meta", {}).values()} - {""})} for i in items]}
    out, cost = model_call(GROUPS_RULES, payload, GROUPS_SCHEMA, model="sonnet", timeout=SEED_TIMEOUT)
    with _work_lock:
        w = load_work()
        ids = {g["key"]: "g" + new_id()[1:] for g in out["groups"]}
        w["groups"] = {ids[g["key"]]: {"id": ids[g["key"]], "title": g["title"], "order": n} for n, g in enumerate(out["groups"])}
        for a in out["assign"]:
            if a["item"] in w["items"]:
                w["items"][a["item"]]["group"] = ids.get(a["group"], "")
        save_work(w)
    print(f"{time.strftime('%H:%M:%S')} goal groups: {len(ids)} groups for {len(items)} items, ${cost:.3f}", flush=True)
    return {"groups": len(ids), "cost": cost}


def add_sender(item, s):
    item.setdefault("asked_by", []).append(s)
    if s["person"] not in item["people"]:
        item["people"].append(s["person"])
    item["updated"] = time.time()


def record_sender(surface, person, ask):
    """A capture session says who is asking. Goes on the tab's item now, or waits until the sorter files the tab."""
    s = {"person": person.strip(), "ask": ask.strip()[:120], "at": time.time()}
    tr = next((t["transcript"] for t in live_tabs(state()).values() if t["id"] == surface), None)
    with _work_lock:
        w = load_work()
        item = owner_of(w, tr) if tr else None
        if item:
            add_sender(item, s)
        else:
            w.setdefault("pending_senders", {})[surface] = s
        save_work(w)
    print(f"{time.strftime('%H:%M:%S')} sender: {person} -> {item['title'] if item else 'pending ' + surface[:8]}", flush=True)
    return {"item": item and item["title"], "pending": not item}


CAPTURE_LOG = Path.home() / ".overworld" / "captures.jsonl"  # one row per capture and per redirect; the page shows the recent ones
_capture_lock = threading.Lock()


def capture_logged(text, route=True):
    """capture() plus a log row, and the reason in the message so the hotkey alert says why it went where it went."""
    r = capture(text, route)
    row = {"id": new_id(), "at": time.time(), "text": text, **r}
    if r["routed"] != "new" and r.get("reason"):
        row["message"] = r["message"] + ": " + r["reason"].rstrip(". ")
    row["message"] += ". Wrong? Fix it in Overworld."
    with _capture_lock, open(CAPTURE_LOG, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def recent_captures(n=6, within=86400):
    if not CAPTURE_LOG.exists():
        return []
    rows = [json.loads(l) for l in CAPTURE_LOG.read_text().splitlines() if l.strip()]
    gone = {r["redirected_from"] for r in rows if r.get("redirected_from")}
    return [r for r in rows if r["at"] > time.time() - within and r["id"] not in gone][-n:][::-1]


def redirect_capture(cid, to):
    """Robert says a capture went to the wrong place. Undo there (tell a continued tab to ignore it, close a tab opened for it),
    drop the Slack thread link it made, then send it to `to`: a work item id, or "new" for a fresh tab."""
    rows = [json.loads(l) for l in CAPTURE_LOG.read_text().splitlines() if l.strip()]
    rec = next(r for r in rows if r["id"] == cid)
    if rec["routed"] == "continued":
        msg = f"Ignore the capture I just sent (it starts: {rec['text'][:80]!r}). It was routed to this tab by mistake; do nothing with it."
        out = subprocess.run([CMUX, "paste", "--workspace", rec["workspace"], "--surface", rec["surface"], "--submit", "-"], input=msg,
                             capture_output=True, text=True, timeout=10, env={**os.environ, "CMUX_QUIET": "1"})
        if out.returncode:
            raise RuntimeError(f"could not tell the old tab to ignore it: {out.stderr.strip()[:200]}")
    else:  # resumed or new: the tab exists only because of this capture
        checked_cmux("close-surface", "--surface", rec["surface"], "--workspace", rec["workspace"], "--force")
    key = rec.get("key")
    if key:
        with _work_lock:
            w = load_work()
            for i in w["items"].values():
                if key in i["sources"] and i["id"] != to:
                    i["sources"].remove(key)
            save_work(w)
        threads = json.loads(THREADS.read_text()) if THREADS.exists() else {}
        if threads.pop(key, None):
            THREADS.write_text(json.dumps(threads, indent=1))
    if to == "new":
        r = capture(rec["text"], route=False)
        if rec.get("item"):
            with _work_lock:
                w = load_work()
                w.setdefault("avoid", {})[r["surface"]] = rec["item"]
                save_work(w)
    else:
        item = load_work()["items"][to]
        r = {**deliver_to_item(item, rec["text"], key), "reason": "you moved it here", "item": item["id"], "item_title": item["title"], "key": key}
    row = {"id": new_id(), "at": time.time(), "text": rec["text"], "redirected_from": cid, **r}
    with _capture_lock, open(CAPTURE_LOG, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"{time.strftime('%H:%M:%S')} capture redirect: {cid} -> {to} ({r['routed']})", flush=True)
    return row


# ---------- Galaxy: goals = systems, work items = planets, sessions = the planet's history. ----------
# Links between items are inferred from transcripts (shared files, repos, Slack threads, spinoff briefs, people); nothing new is recorded.
FACTS = Path.home() / ".overworld" / "facts.json"  # transcript -> facts, keyed by mtime so a restart doesn't re-read 500 MB
DORMANT_DAYS = 5  # an item with no session activity for this long and no live tab needing anything reads as dormant
HOME = str(Path.home())
NOISE_PATHS = ("/tmp/", "/private/tmp/", "/private/var/", f"{HOME}/.claude/projects/", f"{HOME}/.overworld/captures/")
GENERIC_FILE_ITEMS = 6  # a file touched by more items than this (a global CLAUDE.md, MEMORY.md) links nothing
PR_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_facts_lock = threading.Lock()
_facts = None
_git_root_cache = {}


def project_of(path):
    """Project folder a path belongs to: its git root, else the ~/Projects/<name> folder (every one keeps a CONTEXT.md). None for home."""
    root = git_root(path)
    if root:
        return root
    rel = Path(path).parts[len(Path(HOME).parts):]
    return f"{HOME}/Projects/{rel[1]}" if len(rel) >= 2 and rel[0] == "Projects" else None


_main_repo_cache = {}


def main_repo(root):
    """A worktree (extra branch checkout, e.g. parrots-nest-QUEST-477) counts as its main repo. A removed one is matched by name."""
    if root not in _main_repo_cache:
        dotgit, main = Path(root) / ".git", root
        if dotgit.is_file():
            m = re.match(r"gitdir:\s*(.+?)/\.git/worktrees/", dotgit.read_text())
            main = m.group(1) if m else root
        elif not dotgit.exists():
            base = re.sub(r"-[A-Z]+-\d+$", "", root)
            main = base if base != root and (Path(base) / ".git").is_dir() else root
        _main_repo_cache[root] = main
    return _main_repo_cache[root]


def git_root(path):
    """Nearest folder holding .git above path; None for home itself or outside any repo."""
    p = Path(path)
    for d in [p, *p.parents]:
        key = str(d)
        if key in _git_root_cache:
            return _git_root_cache[key]
        if (d / ".git").exists():
            root = None if key == HOME else key
            _git_root_cache[key] = root
            return root
        if key in (HOME, "/"):
            break
    _git_root_cache[str(p)] = None
    return None


TAG_BLOCK = re.compile(r"<(system-reminder|command-[\w-]+|local-command-[\w-]+)>.*?</\1>", re.S)


def transcript_facts(path):
    """One pass over a transcript: time span, prompt times, cwd, files edited, repos, Slack threads, PRs, handoff briefs, sub-agent count."""
    first = lastt = None
    prompts, texts, files, cwds, threads, prs, briefs_in = [], [], set(), set(), set(), set(), set()
    with open(path, "rb") as f:
        for raw in f:
            if b'"timestamp"' not in raw:
                continue
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = e.get("timestamp")
            if not ts or e.get("type") not in ("user", "assistant"):
                continue
            t = _epoch(ts)
            first = first or t
            lastt = t
            if e.get("cwd"):
                cwds.add(e["cwd"])
            if e["type"] == "user" and _is_prompt(e):
                text = _user_text(e)
                prompts.append(t)
                clean = " ".join(TAG_BLOCK.sub(" ", text).split())
                if clean:
                    texts.append(clean[:600])
                for m in SLACK_LINK.finditer(text):
                    k = slack_thread(m.group(0))
                    if k:
                        threads.add(k)
                briefs_in.update(re.findall(r"/\.overworld/handoffs/[\w.-]+\.md", text))
            elif e["type"] == "assistant":
                for b in _blocks(e):
                    if b.get("type") == "text":
                        prs.update(PR_LINK.findall(b.get("text", "")))
                    elif b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                        fp = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                        if fp:
                            files.add(fp)
    sub = Path(path).with_suffix("") / "subagents"
    repos = {r for r in (project_of(c) for c in cwds | {str(Path(f).parent) for f in files if not f.startswith(NOISE_PATHS)}) if r}
    return {"first": first, "last": lastt, "prompts": prompts[-400:], "texts": texts[-300:], "cwd": sorted(cwds)[:3],
            "files": sorted(files), "repos": sorted(repos), "threads": sorted(threads), "prs": sorted(prs),
            "briefs_out": sorted(f.split("/.overworld")[1] for f in files if "/.overworld/handoffs/" in f),
            "briefs_in": sorted(b[len("/.overworld"):] for b in briefs_in),
            "subagents": len(list(sub.glob("agent-*.jsonl"))) if sub.is_dir() else 0}


def facts_for(paths):
    """Facts for each transcript, re-read only when its mtime changed. Missing transcripts are left out."""
    global _facts
    with _facts_lock:
        if _facts is None:
            _facts = json.loads(FACTS.read_text()) if FACTS.exists() else {}
        out, changed = {}, False
        for p in paths:
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            cached = _facts.get(p)
            if not cached or cached["mtime"] != mt or "texts" not in cached:  # "texts" arrived later: re-read older entries once
                cached = {"mtime": mt, **transcript_facts(p)}
                _facts[p], changed = cached, True
            out[p] = cached
        if changed:
            tmp = FACTS.with_suffix(".tmp")
            tmp.write_text(json.dumps(_facts))
            tmp.replace(FACTS)
        return out


def _shared(sets_by_item, kind, generic=None):
    """Pairs of items sharing a value in their sets -> link rows. Values held by more than `generic` items are ignored."""
    holders = {}
    for iid, vals in sets_by_item.items():
        for v in vals:
            holders.setdefault(v, []).append(iid)
    pairs = {}
    for v, ids in holders.items():
        if len(ids) < 2 or (generic and len(ids) > generic):
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                pairs.setdefault(tuple(sorted((ids[a], ids[b]))), []).append(v)
    return [{"a": a, "b": b, "kind": kind, "via": sorted(vs)} for (a, b), vs in pairs.items()]


def galaxy(st):
    """Systems (goals), planets (items) with derived dormant flag, and inferred links between items."""
    w = load_work()
    view = {i["id"]: i for i in work_view(st)["items"]} if st["regions"] else {}
    facts = facts_for([tr for i in w["items"].values() for tr in i["sessions"]])
    now, planets = time.time(), []
    files, repos, threads, people, out_b, in_b = {}, {}, {}, {}, {}, {}
    for i in w["items"].values():
        fs = [facts[tr] for tr in i["sessions"] if tr in facts]
        v = view.get(i["id"], {})
        last_active = max([f["last"] or 0 for f in fs] + [i.get("updated", 0)])
        live_need = v.get("status") in ("waiting", "working")
        dormant = i["state"] == "active" and not live_need and now - last_active > DORMANT_DAYS * 86400
        iid = i["id"]
        files[iid] = {f for x in fs for f in x["files"] if not f.startswith(NOISE_PATHS) and "/.overworld/" not in f}
        repos[iid] = {main_repo(r) for x in fs for r in x["repos"]}
        threads[iid] = set(i.get("sources", [])) | {t for x in fs for t in x["threads"]}
        people[iid] = {p.split()[0].lower() for p in i.get("people", []) if p}
        out_b[iid] = {b for x in fs for b in x["briefs_out"]}
        in_b[iid] = {b for x in fs for b in x["briefs_in"]}
        planets.append({"id": iid, "title": i["title"], "goal": i.get("goal", ""), "group": i.get("group", ""), "state": i["state"],
                        "dormant": dormant, "last_active": last_active, "status": v.get("status", "none"), "needs": v.get("needs", False),
                        "next": v.get("next", i.get("next", "")), "waits_on": i.get("waits_on", ""), "people": i.get("people", []),
                        "tabs": v.get("tabs", []), "sessions": len(i["sessions"]), "repos": sorted(repos[iid]),
                        "prs": len({p for x in fs for p in x["prs"]}), "files": len(files[iid]), "threads": len(threads[iid])})
    links = (_shared(files, "file", GENERIC_FILE_ITEMS) + _shared(threads, "thread") +
             _shared(repos, "project", GENERIC_FILE_ITEMS * 2) + _shared(people, "person", GENERIC_FILE_ITEMS))
    for a, briefs in out_b.items():  # spinoff: item a wrote a handoff brief that a session of item b was started on
        for b, got in in_b.items():
            via = sorted(briefs & got)
            if a != b and via:
                links.append({"a": a, "b": b, "kind": "spinoff", "via": [Path(x).stem for x in via]})
    groups = sorted(w.get("groups", {}).values(), key=lambda g: g.get("order", 0))
    return {"systems": [{"id": g["id"], "title": g["title"]} for g in groups], "planets": planets, "links": links,
            "dormant_days": DORMANT_DAYS, "at": now}


def planet(item_id, st):
    """One item's history: each session's span, prompt times, spinoff parent within the item, sub-agents, files, PRs, threads."""
    w = load_work()
    i = w["items"].get(item_id)
    if not i:
        return {"error": "no such item"}
    facts = facts_for(i["sessions"])
    live = live_tabs(st) if st["regions"] else {}
    wrote = {b: tr for tr in i["sessions"] if tr in facts for b in facts[tr]["briefs_out"]}
    sessions = []
    for tr in i["sessions"]:
        f, m = facts.get(tr), i.get("meta", {}).get(tr, {})
        if not f:
            continue
        t = live.get(tr)
        parent = next((wrote[b] for b in f["briefs_in"] if b in wrote and wrote[b] != tr), None)
        sessions.append({"transcript": tr, "title": (t or {}).get("title") or m.get("title") or Path(tr).stem[:8],
                         "first": f["first"], "last": f["last"], "prompts": f["prompts"], "parent": parent,
                         "brief": next((Path(b).stem for b in f["briefs_in"]), None), "subagents": f["subagents"],
                         "live": t["id"] if t else None, "workspace": t["workspace"] if t else None,
                         "status": t["status"] if t else "closed", "where": m.get("workspace_title", ""), "agent": m.get("agent", "claude")})
    sessions.sort(key=lambda s: s["first"] or 0)
    fs = [facts[tr] for tr in i["sessions"] if tr in facts]
    return {"id": item_id, "title": i["title"], "goal": i.get("goal", ""), "note": i.get("note", ""), "next": i.get("next", ""),
            "waits_on": i.get("waits_on", ""), "people": i.get("people", []), "state": i["state"], "sessions": sessions,
            "files": sorted({f for x in fs for f in x["files"] if not f.startswith(NOISE_PATHS)}),
            "repos": sorted({main_repo(r) for x in fs for r in x["repos"]}), "prs": sorted({p for x in fs for p in x["prs"]}),
            "threads": sorted(set(i.get("sources", [])) | {t for x in fs for t in x["threads"]})}


def _snip(text, words, width=110):
    """The part of text around the first query word, with ellipses where it was cut."""
    low = text.lower()
    at = min((low.find(w) for w in words if w in low), default=0)
    a = max(0, at - width // 3)
    if a:
        a = text.find(" ", a, at) + 1 or a  # start on a word boundary
    b = min(len(text), a + width)
    if b < len(text):
        b = text.rfind(" ", a, b) if text.rfind(" ", a, b) > at else b
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def search(q):
    """Items whose name, notes, repos, files, threads, people or prompts contain every word of q. Each hit carries where it matched and a snippet."""
    words = [w for w in q.lower().split() if w]
    if not words:
        return {"q": q, "hits": []}
    w = load_work()
    facts = facts_for([tr for i in w["items"].values() for tr in i["sessions"]])
    hits = []
    for i in w["items"].values():
        fs = [facts[tr] for tr in i["sessions"] if tr in facts]
        fields = [("name", i["title"]), ("goal", i.get("goal", "")), ("next", i.get("next", "")), ("note", i.get("note", "")),
                  ("waits on", i.get("waits_on", "")), ("people", ", ".join(i.get("people", [])))]
        fields += [("project", r) for r in sorted({main_repo(r) for x in fs for r in x["repos"]})]
        fields += [("file", f) for f in sorted({f for x in fs for f in x["files"] if not f.startswith(NOISE_PATHS)})]
        fields += [("prompt", t) for x in sorted(fs, key=lambda x: -(x["last"] or 0)) for t in reversed(x.get("texts", []))]
        fields = [(k, v) for k, v in fields if v]
        blob = " ".join(v.lower() for _, v in fields)
        if not all(x in blob for x in words):
            continue
        # Best snippet: the first field holding the most query words (fields are ordered name first, newest prompt first)
        k, v = max(fields, key=lambda f: sum(x in f[1].lower() for x in words))
        n = sum(blob.count(x) for x in words)
        hits.append({"id": i["id"], "field": k, "snippet": v if k == "name" else v.rsplit("/", 1)[-1] if k in ("project", "file") else _snip(v, words), "n": n})
    hits.sort(key=lambda h: (h["field"] != "name", -h["n"]))
    return {"q": q, "hits": hits}


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
            st = state()
            st["work"] = work_view(st) if st["regions"] else {"seeded": False, "items": [], "unsorted": [], "proposal": None}
            st["captures"] = recent_captures()
            st["page"] = (HERE / "index.html").stat().st_mtime  # the page reloads itself when this changes
            self._send(200, st)
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
        elif self.path.startswith("/api/context?surface="):
            q = dict(kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&") if "=" in kv)
            self._send(200, context_map(q["surface"], q.get("agent", "")))
        elif self.path.startswith("/api/handoffs?surface="):
            self._send(200, handoffs(self.path.split("=", 1)[1]))
        elif self.path.startswith("/api/steps?surface="):
            self._send(200, recent_steps(self.path.split("=", 1)[1]))
        elif self.path.startswith("/api/search?q="):
            self._send(200, search(urllib.parse.unquote_plus(self.path.split("=", 1)[1])))
        elif self.path == "/api/galaxy":
            self._send(200, galaxy(state()))
        elif self.path.startswith("/api/planet?id="):
            self._send(200, planet(self.path.split("=", 1)[1], state()))
        elif self.path == "/api/usage":
            self._send(200, usage())
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
        elif self.path in ("/api/dock", "/api/undock"):
            try:
                return self._send(200, dock(body["surface"]) if self.path == "/api/dock" else undock())
            except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError, KeyError) as e:
                print(f"{time.strftime('%H:%M:%S')} {self.path} failed: {e!r}", flush=True)
                return self._send(502, {"error": str(e)[:300]})
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
        elif self.path == "/api/capture":
            try:
                return self._send(200, capture_logged(body["text"].strip()))
            except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, StopIteration, RuntimeError) as e:
                print(f"{time.strftime('%H:%M:%S')} capture failed: {e!r}"[:400], flush=True)
                return self._send(502, {"error": repr(e)[:300]})
        elif self.path == "/api/capture/redirect":
            try:
                return self._send(200, redirect_capture(body["id"], body["to"]))
            except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, StopIteration, RuntimeError, OSError) as e:
                print(f"{time.strftime('%H:%M:%S')} capture redirect failed: {e!r}"[:400], flush=True)
                return self._send(502, {"error": repr(e)[:300]})
        elif self.path.startswith("/api/work/"):
            op = self.path.rsplit("/", 1)[1]
            try:
                if op == "seed":
                    return self._send(200, seed_work())
                if op == "accept":
                    return self._send(200, accept_seed(body["items"]))
                if op == "park":
                    return self._send(200, park(body["id"]))
                if op == "resume":
                    r = resume(body["id"], transcript=body.get("transcript"))
                    if body.get("dock"):  # from the galaxy: show it beside the map instead of switching away
                        for _ in range(30):  # the new tab shows up in the tree a moment after new-surface answers
                            if _where(r["surface"]):
                                break
                            time.sleep(0.1)
                        r.update(dock(r["surface"]))
                    else:
                        focus(r["workspace"], r["surface"])
                    return self._send(200, r)
                if op == "edit":
                    return self._send(200, work_edit(body))
                if op == "groups":
                    return self._send(200, propose_groups())
                if op == "sender":
                    return self._send(200, record_sender(body["surface"], body["person"], body.get("ask", "")))
                return self._send(404, {"error": "not found"})
            except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, StopIteration, RuntimeError) as e:
                print(f"{time.strftime('%H:%M:%S')} work {op} failed: {e!r}"[:400], flush=True)
                return self._send(502, {"error": repr(e)[:300]})
        elif self.path == "/api/close":
            # force: plain shells (no agent) only; cmux refuses to close a tab with a running process without it
            cmux("close-surface", "--surface", body["surface"], "--workspace", body["workspace"], *(["--force"] if body.get("force") else []))
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
    threading.Thread(target=keep_usage, daemon=True).start()
    threading.Thread(target=keep_work, daemon=True).start()
    threading.Thread(target=keep_came_from, daemon=True).start()
    httpd.serve_forever()
