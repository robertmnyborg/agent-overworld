#!/usr/bin/env python3
"""Agent Overworld: serves a map of cmux workspaces (regions) and tabs (sessions).

Reads cmux's own records; writes nothing except ~/.overworld/edges.jsonl (via spinoff.sh).
Started by autostart.zsh from the first cmux shell (cmux's socket only accepts processes launched inside cmux).
While cmux is running, keeps a pinned "Overworld" workspace (browser pane on this server) in slot 1 (⌘1).
"""
import json, os, re, subprocess, threading, time
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
NAME_WORDS = {"t": 3, "w": 5}  # max words for tab (t) and workspace (w) names
NAME_SCHEMA = {"type": "object", "required": ["names"], "properties": {"names": {"type": "array", "items": {
    "type": "object", "required": ["key", "name"], "properties": {"key": {"type": "string"}, "name": {"type": "string"}}}}}}
NAME_RULES = """Name cmux workspaces and the Claude Code session tabs inside them, from what each session is about.
Tab names: 2-3 words. Workspace names: 2-5 words covering the tabs inside it. Concrete nouns from the work (project, feature, person, artifact).
No quotes, no emoji, no trailing punctuation, no generic words like "Session", "Chat", "Claude", or "Work". Title Case.
Return one entry per key given (every workspace key "w*" and every tab key "t*"). Input:
"""

SCREEN_TTL = 30  # seconds to cache read-screen recaps for agents without a transcript recap
_screen_cache = {}
_recap_cache = {}  # transcript path -> (mtime, (text, last turn time, last turn role))
_events = {"inode": None, "offset": 0, "last": {}}  # surface_id -> (hook event name, occurred_at)
WORKING = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStop", "PreCompact"}


CMUX = "/opt/homebrew/bin/cmux"
ENSURE_EVERY = 15  # seconds between checks that the Overworld workspace exists


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


def last_reply(transcript):
    """(last assistant text ~240 chars, last user/assistant turn time, its role) from a Claude transcript."""
    path = Path(transcript or "")
    if not path.is_file():
        return "", None, None
    mtime = path.stat().st_mtime
    hit = _recap_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 400_000))
        lines = f.read().splitlines()
    text, turn_at, turn_role = "", None, None
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
            text = plain(" ".join(parts))
            break
    _recap_cache[path] = (mtime, (text, turn_at, turn_role))
    return text, turn_at, turn_role


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
        text, turn_at, turn_role = last_reply(s.get("transcriptPath"))
        out[surface] = {"agent": "claude", "lifecycle": s.get("agentLifecycle"), "recap": text or s.get("lastBody") or "",
                        "cwd": s.get("cwd"), "updated": s.get("updatedAt"), "pid": s.get("pid"),
                        "turn_at": turn_at, "turn_role": turn_role, "transcript": s.get("transcriptPath")}
    agy = load_json(CMUXTERM / "antigravity-hook-sessions.json").get("sessions", {})
    for s in agy.values():
        cur = out.get(s["surfaceId"])
        if cur is None or (s.get("updatedAt") or 0) > (cur.get("updated") or 0):
            out[s["surfaceId"]] = {"agent": "agy", "lifecycle": s.get("agentLifecycle"), "recap": "",
                                   "cwd": s.get("cwd"), "updated": s.get("updatedAt"), "pid": s.get("pid")}
    return out


def session_brief(transcript):
    """(Claude Code's own title for the session, first real user prompt) from a transcript."""
    path = Path(transcript or "")
    if not path.is_file():
        return "", ""
    text = path.read_text(errors="replace")
    titles = re.findall(r'"aiTitle":"((?:[^"\\]|\\.)*)"', text)
    first = ""
    for line in text.splitlines():
        if '"type":"user"' not in line:
            continue
        content = json.loads(line).get("message", {}).get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if content and not content.lstrip().startswith("<"):
            first = plain(content)[:300]
            break
    return (json.loads(f'"{titles[-1]}"') if titles else ""), first


def autoname(workspace=None):
    """Name workspaces (all, or one) and their agent tabs from session content with one headless Haiku call, then apply."""
    agents = agent_sessions()
    targets, payload = {}, []
    for i, r in enumerate(state()["regions"]):
        if workspace not in (None, r["id"]):
            continue
        tabs = []
        for j, t in enumerate(r["sessions"]):
            if not t["agent"]:
                continue  # plain shell: nothing to name it from
            title, first = session_brief(agents.get(t["id"], {}).get("transcript"))
            key = f"t{i}_{j}"
            targets[key] = (r["id"], t["id"])
            tabs.append({"key": key, "current_name": t["title"], "session_title": title, "first_prompt": first, "last_reply": t["recap"]})
        if tabs:
            targets[f"w{i}"] = (r["id"], None)
            payload.append({"key": f"w{i}", "current_name": r["title"], "tabs": tabs})
    if not payload:
        return {"renamed": 0}
    out = subprocess.run([*NAMER, "--json-schema", json.dumps(NAME_SCHEMA)], input=NAME_RULES + json.dumps(payload, indent=1),
                         capture_output=True, text=True, timeout=120, cwd="/tmp")  # /tmp: keeps ~/CLAUDE.md out of the prompt
    result = json.loads(out.stdout)
    if result.get("is_error"):
        raise RuntimeError(result.get("result", "naming call failed"))
    renamed = 0
    for entry in result["structured_output"]["names"]:
        if entry["key"] not in targets:
            continue
        ws, surface = targets[entry["key"]]
        name = " ".join(entry["name"].strip().strip('."\'').split()[:NAME_WORDS[entry["key"][0]]])
        if surface:
            cmux("rename-tab", "--workspace", ws, "--surface", surface, "--", name)
        else:
            cmux("workspace-action", "--workspace", ws, "--action", "rename", "--title", name)
        renamed += 1
    print(f"{time.strftime('%H:%M:%S')} autoname {workspace or 'all'}: {renamed} renamed, ${result.get('total_cost_usd', 0):.3f}", flush=True)
    return {"renamed": renamed, "cost_usd": result.get("total_cost_usd")}


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
    regions = []
    for window in tree["windows"]:
        for ws in window["workspaces"]:
            if ws["title"] == "Overworld":
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
                    if event and event[0] == "SessionStart" and sess and sess.get("turn_at"):
                        since = sess["turn_at"]  # a relaunch restarts every session; age from the last real turn
                    sessions.append({"id": sf["id"], "title": sf["title"], "workspace": ws["id"],
                                  "status": status(sess, unread.get(sf["id"]), event),
                                  "since": since, "recap": recap,
                                  "agent": sess["agent"] if sess else None,
                                  "cwd": sess["cwd"] if sess else None,
                                  "updated": sess["updated"] if sess else None,
                                  "here": sf.get("selected_in_pane") and pane.get("focused") and ws.get("selected")})
            if sessions:
                regions.append({"id": ws["id"], "title": ws["title"], "sessions": sessions})
    return {"regions": regions, "edges": edges, "at": time.time()}


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
                return self._send(502, {"error": repr(e)[:300]})
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
    httpd.serve_forever()
