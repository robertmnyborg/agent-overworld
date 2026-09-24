# Agent Overworld — Build Sheet

Lane: self-serve (Robert builds, runs, and owns it; local only; failure = fall back to tab scanning).
Outcome: one glance shows which town needs me and what it belongs to; one click goes there and back.
Scale ceiling: 1 user, ~30 towns, ~8 regions, one Mac. Build for that, nothing more.

## Current state (the pain)
- 29 cmux tabs across 8 workspaces (2026-09-22 `cmux tree --all`).
- Tab titles show no status. "Waiting" / "Completed" notifications exist (cmux Claude wrapper) but sit in a list I have to scan.
- Spin-off sessions (opened to avoid context bloat) keep no link to the session they came from.
- Result: constant tab scanning, clicking in to remember what a tab was doing.

## Ideal state (v1)
1. Overworld = a dedicated cmux workspace with one browser pane.
2. Each workspace draws as a region; each tab draws as a town.
3. Town color = waiting (needs me) / working / idle / done.
4. Waiting towns sort first inside each region; unread count on region.
5. Each town shows a one-line recap of its last reply.
6. Spin-off towns draw an edge to their parent town.
7. Click a town → cmux focuses that tab.
8. One keybind returns to the Overworld workspace.

Priority order (Robert, 2026-09-22): 1 waiting → 4 recap → 5 lineage → 2 background done → 3 connections.

## How each piece gets its data
| Job | Source | Status |
|---|---|---|
| Regions + towns | `cmux tree --all` | verified works |
| Waiting / done | `cmux list-notifications` (Waiting/Completed per surface) + Claude hooks (UserPromptSubmit = working, Stop = idle) keyed by `$CMUX_SURFACE_ID` | notifications verified; hook env var verified present |
| Recap line | Stop hook `last_assistant_message` (fallback: `transcript_path`), same pattern as `~/.claude/hooks/handoff-guard.py` | pattern verified |
| agy / local-model towns | `cmux hooks agy install` for status; `cmux read-screen --lines 5` for recap | agy listed as supported; not yet installed |
| Lineage | `/spinoff` skill: `cmux new-surface` in same workspace, writes parent→child edge, seeds child with a handoff summary | to build |
| Jump | `cmux focus-pane` / `select-workspace` | verified in `--help` |
| Background jobs (v2) | Completed notifications; launchd jobs later | v2 |
| Connections (v3) | Claude SessionStart hook: cwd, git branch, MCP list | v3 |

State store: one JSON file per surface in `~/.overworld/state/`. Edges in `~/.overworld/edges.jsonl`.
Server: stdlib Python on localhost, serves the page, polls cmux every 2s, POST /focus runs the cmux command.

## Irreversible-step gate
None. The map reads state and moves focus. It never closes tabs, sends input to a session, or deletes transcripts. Closing sessions stays manual.

## Access checklist
| System | Credential | Grantor | Verified |
|---|---|---|---|
| cmux socket | local socket (`$CMUX_SOCKET_PATH`) | self | yes |
| cmux session + event files | `~/.cmuxterm/*` (read-only) | self | yes |
| agy hooks | `cmux hooks agy install` | self | no |

## To-confirm
- RESOLVED 2026-09-22: "back to overworld" = pin Overworld as workspace 1 and use the built-in ⌘1 (`selectWorkspaceByNumber`). Built-in ⌘⇧U (`jumpToUnread`) already jumps to the latest waiting tab today.
- RESOLVED: events come from `~/.cmuxterm/events.jsonl`, followed incrementally; page polls the server every 3s.
- RESOLVED: headless `claude -p` runs do not replace a tab's active session in `activeSessionsBySurface` (verified on this tab).

## Run / monitor
- Step 4: build, open once, check every current tab appears with the right status.
- Babysit 1 week (to 2026-09-29): note any tab with the wrong status or a missing recap.
- Kill switch: remove the autostart line from `~/.zshrc`, `kill $(<~/.overworld/server.pid)`, unpin + close the Overworld workspace. No Claude config was changed.

## Later
- v2: cmux custom sidebar as an always-visible minimap (sidebar DSL is beta).
- v2: background-job towns. v3: connections panel.
