# Agent Overworld — CONTEXT

Personal tool. Visual "overworld" of all cmux agent sessions (workspaces = regions, tabs = towns), click to drill in, keybind back. Not Peek work.

## 2026-09-22
- Ran product-thinking (self-serve lane). Build Sheet: `BUILD-SHEET.md`.
- Rejected Agentshire: OpenClaw-only plugin, no Claude Code support.
- Key finding: cmux already exposes the data (`tree --all`, `list-notifications` with Waiting/Completed per surface, `focus-pane`, `read-screen`, agent hooks incl. agy, `$CMUX_SURFACE_ID` in Claude sessions). Build = view + lineage record, no new data layer.
- Claude Code transcripts carry no session→session lineage (`parentUuid` is message-level). Lineage must be written at spawn time (`/spinoff`).
- Job priority: waiting > recap > lineage > background done > connections.
- Next: step 4, build the thin slice (tree + status + recap + click-to-focus) and run it once.

## 2026-09-22 (build, thin slice shipped)
- Works: `./overworld.sh` opens workspace "Overworld" at slot 1 (⌘1): server pane + browser pane on http://127.0.0.1:7717. Regions = workspaces, towns = terminal tabs, sorted your-turn > finished > working > idle; one-line recap; click = `cmux focus-panel` (verified).
- No Claude hook added (the approved settings.json hook was unnecessary). Data comes from cmux's own files:
  - `~/.cmuxterm/claude-hook-sessions.json` → `activeSessionsBySurface` → session (pid, cwd, transcriptPath). `antigravity-hook-sessions.json` for agy.
  - `~/.cmuxterm/events.jsonl` (+ `.1` backfill) → last `agent.hook.*` per surface = status. cmux's `agentLifecycle` goes stale (one workspace said running a day after its last Notification), so events win.
  - Recap = last assistant text from the transcript tail; agy / new sessions fall back to `cmux read-screen`.
- Lineage: `/spinoff` skill (`~/.claude/skills/spinoff/`) → `spinoff.sh` opens a sibling tab, starts `claude` on a brief in `~/.overworld/handoffs/`, appends `~/.overworld/edges.jsonl`. Verified end-to-end with a test child (closed after). Trigger predicate: explicit `/spinoff` or user phrasing; it neither gates nor routes.
- Server dies with cmux; after a cmux restart run `./overworld.sh` again.
- Babysit to 2026-09-29: log wrong statuses / missing recaps here.
- v2 ideas: cross-workspace edges drawn as "from <region>"; custom-sidebar minimap; background-job towns.

## 2026-09-22 (autostart + ⌘1 fix)
- ⌘1 bug: Overworld sat at index 1 because Harness got moved above it. Fix: the workspace is now **pinned** (pinned workspaces stay on top and can't be closed by accident).
- Autostart: `autostart.zsh`, sourced from `~/.zshrc`, starts `server.py` detached the first time a cmux shell opens (pidfile `~/.overworld/server.pid` stops duplicates). cmux restores tabs at launch, so the server comes up with cmux.
- launchd was tried and dropped: cmux's socket (`automation.socketControlMode` = `cmuxOnly`) rejects processes not launched inside cmux ("Access denied - only processes started inside cmux can connect"). A process launched from a cmux shell keeps access after it's orphaned (verified ppid=1 → PONG), which is why the zshrc route works without loosening the socket mode.
- The server rebuilds the Overworld workspace every 15s if needed (create → browser tab on :7717 → pin → move to top). Verified: closed it, back in ~28s. `overworld.sh` deleted, since the server does its job now.
- Kill switch: delete the `source ~/Projects/agent-overworld/autostart.zsh` line in `~/.zshrc`, `kill $(<~/.overworld/server.pid)`, then unpin and close the Overworld workspace.
- Log: `~/.overworld/server.log`.

## 2026-09-23 (full cmux relaunch, babysit)
- Relaunch path verified live: cmux restarted ~21:19, the zshrc autostart brought the server up (new pid, ppid 1), and Overworld came back pinned in slot 1 with its map tab. The old server logged `Socket not found` while cmux was down, as expected.
- Bug found: cmux assigns NEW surface ids on relaunch, and each restored Claude session fires only `SessionStart`. So every town read "idle, since relaunch" and the your-turn list and ages vanished (12 your-turn → 0).
- Fix in `server.py`: `last_reply` also returns the last user/assistant turn's timestamp and role. When the last hook is `SessionStart` and the last turn is the assistant's, the town reads `waiting` and `since` = that turn. Result after the fix: 17 your-turn, ages back (OOD/ID correctly shows 2026-08-24).

## 2026-09-23 (layout + session management)
- Masonry layout: each region goes into the currently shortest column (rank order still reads left to right), so short regions no longer inherit the tallest region's height. At 1480px wide the whole map fits in one screen (page height = viewport 958px).
- Drag a town onto another region → `move-surface --workspace` (`/api/move`). Renders pause mid-drag.
- `+` in a region header → new tab running `claude` (`/api/new`, `NEW_SESSION_COMMAND`). `×` on hover, click twice within 3s → `close-surface` (`/api/close`). Closing kills the process; the transcript stays resumable.
- ⌘⇧1 = cmux's native Focus Back (History menu), bound in `~/.config/cmux/cmux.json` (`shortcuts.bindings.focusHistoryBack`, backup `cmux.json.bak-*`). It replaces the ⌘[ default. The first version (page keydown + `/api/back` + a 1s `identify` focus tracker) was removed: with real keystrokes the webview never received ⌘⇧1 (no `/api/back` in the log), and Robert's press landed on Harness/Ant, not the tab he was in. Verified: from the Overworld, History > Focus Back landed on the last tab used (visualization, surface:23). Verified: create/move/close on a throwaway Claude session.
- cmux gotcha: `close-surface`/`move-surface` reject the `(UUID)` form that `new-surface` prints; pass the bare UUID. A moved surface gets a new ref (surface:29 → 30), so address surfaces by UUID only.
- 2026-09-23: Robert confirmed ⌘1 → ⌘⇧1 returns to the right tab with a physical keypress.

## 2026-09-23 (auto-name)
- ✨ Auto-name all (header), ✨ per workspace header, or the `a` key (when the page has focus) → `/api/autoname`. One headless Haiku call (`claude -p --model haiku`, settings/hooks/MCP/tools off, `--no-session-persistence`, cwd `/tmp` so `~/CLAUDE.md` stays out) with `--json-schema`. Input per tab: Claude Code's `aiTitle`, first real user prompt, last reply. Tabs ≤3 words, workspaces ≤5, truncated in code after the call. Plain shells (no agent) are skipped; exited Claude tabs are named from their transcript.
- Test: Feedback/Notes → "Team Feedback Notes" / "Feedback Patterns", 9.9s, $0.007 (Claude Code's reported cost). Names restored after.
- Auth: no ANTHROPIC_API_KEY on this Mac; `--bare` fails ("Not logged in") because it skips keychain reads, so the call uses the stripped-settings flags instead.
- Bug fixed: cmux's `activeSessionsBySurface` dropped this live session, so its tab read "shell". `agent_sessions` now picks per surface from all session records: live pid first, then newest `updatedAt`.
- Fix (same day): Auto-name all spun, then timed out. The single 22-tab call took 73s and overran the 120s limit, and the page swallowed the error. Cause: headless Claude Code runs Haiku with extended thinking (1.6k-7.8k output tokens for ~11 names). Fix: `MAX_THINKING_TOKENS=0` plus one call per workspace in parallel. All 28 names now take 5.0s total, $0.026. The button shows "renamed N" or "failed", and failures go to the server log.
- The one-big-batch run also mismatched keys (the visualization tab came out as "Acceptance Criteria"). Per-workspace calls fixed that.
- Pre-autoname names saved in `~/.overworld/names-original.txt`.

## 2026-09-23 (groups)
- Uses cmux's native workspace groups (`cmux workspace-group`), which show as collapsible folders in the left sidebar. Created **Work** and **Personal** groups, with idempotency keys `overworld-work` / `overworld-personal`.
- cmux generates an empty anchor workspace per group (it IS the group header in the sidebar). The map hides generated anchors.
- Overworld: one section per group in sidebar order, then Ungrouped. Drag a workspace by its header onto a section → `workspace-group add` (`remove` for Ungrouped), via `/api/group`. ✎ on a section header → `workspace-group rename`. Verified: round trip one workspace → Personal → Work. ⌘1 slot unaffected (Overworld stays index 0, pinned).
- Cost: the page grew from 958px to 1164px at 1480x958, because each group runs its own masonry and Harness (10 sessions) sets the Work section's height.

## 2026-09-23 (groups side by side, split-out, folder management)
- Groups render side by side, split by a 2px divider. Columns are shared out by workspace count (e.g. New Group 1 col, Work 2, Personal 2 at 1480px).
- Scroll jump fixed: every 3s refresh rebuilt the map, the page collapsed for a moment, and the browser clamped the scroll to 0. render() now saves and restores `scrollY`. Verified: 700px held across two refreshes.
- "Places Map and Recipe Database" disappeared because Personal's generated header workspace got closed. cmux then promoted the next member to header, so that workspace became the folder row. Fixed by ungroup + recreate (`overworld-personal-2`, new generated anchor). Closing a group's header in the sidebar does this again.
- Drag a session onto a group's dashed drop zone (shown only while dragging) → `move-tab-to-new-workspace` (needs `--workspace` too, or it says "Tab not found"), then `workspace-group add`. Drag more sessions onto the new workspace as before.
- `+` on a group header → `new-workspace --group --command claude`. `+ New group` (header bar) → `workspace-group create`. `×` on a group header, clicked twice → ungroup; the workspaces move to Ungrouped. cmux's `--remove-generated-anchor` only works for anchor-only groups, so for a group with members we ungroup and then `close-workspace` the generated header.
- Native equivalents in the sidebar: right-click a folder → Rename Group…, Delete Group, Ungroup Workspaces, New Workspace in Group. ⌃⌘G = new empty group, ⌘⇧G = group the selected workspaces. Right-click a workspace → New Group from Workspace / Remove from Group.
- ⌘⇧G = new empty group, ⌃⌘G = group selected workspaces (swapped from cmux defaults in `cmux.json`). ⌘⇧G is also React Grab's default inside browser panes, including the Overworld.

## 2026-09-27 (columns by height)
- Problem: columns went to groups by workspace count, so Personal (4 small workspaces) got 3 columns and Work (2 tall workspaces, 16 sessions) got 1, forcing a scroll.
- Fix in `render()`: measure each workspace box at column width in a hidden probe, start every group at 1 column, then give each spare column to the tallest group that still has more workspaces than columns (height = simulated shortest-column masonry).
- Verified at 1700x1100 CSS px: Work 2 cols / Personal 2 cols, page 961px = viewport (no scroll). Old rule not re-measured on this data.
