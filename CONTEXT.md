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
