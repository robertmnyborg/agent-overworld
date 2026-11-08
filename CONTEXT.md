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
- ✨ Auto-name all (header), ✨ per workspace header, or the `a` key (when the page has focus) → `/api/autoname`. One headless Haiku call (`claude -p --model haiku`, settings/hooks/MCP/tools off, `--no-session-persistence`, cwd `/tmp` so `~/CLAUDE.md` stays out) with `--json-schema`. Input per tab: last 5 user prompts + last reply (changed 2026-09-29, see below). Tabs ≤3 words, workspaces ≤5, truncated in code after the call. Plain shells (no agent) are skipped; exited Claude tabs are named from their transcript.
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

## 2026-09-29 (trial decision)
- Decision: KEEP. Robert: "worked". Babysit window closed.
- herdr cut same day (`brew uninstall herdr`): gutter status duplicated Overworld at single-workspace scale.
- Kept from the herdr/engineer layout: for dev-server work (Discover :4000/:3001, Studio), use a cmux split with Claude on the right, server logs bottom-left, shell top-left.
- Kavor uninstalled 2026-09-29 (app + data + prefs). Overworld is the only agent-map tool left.

## 2026-09-29 (Scratch workspace)
- Purpose: one home for one-off sessions that don't justify their own workspace yet. Once one grows into a work stream, drag it onto a group's drop zone → it becomes its own workspace in that group (existing `/api/split`).
- `server.py` `ensure_scratch()` runs with the Overworld check every 15s: creates "Scratch" if missing (with a claude tab), removes it from any group, pins it, and holds it at index 1 (⌘2). The existing Scratch was in Personal; it was pulled out and pinned on the first pass.
- Map: Scratch renders as a full-width strip above the groups, sessions side by side (grid, 320px min). No rename/auto-name/drag on its header, so its title stays "Scratch" (renaming it would make the server create a second one). Auto-name still names its tabs.
- Verified at 1700x1100: cmux order Overworld(0, pinned), Scratch(1, pinned); strip 117px tall with 2 sessions; Work/Personal still 2+2 columns. Page 977px vs 961px viewport (16px over, from the strip).

## 2026-09-29 (auto-name tracks recent turns)
- Problem: Robert: names "don't help me find the last thing that I was working on". Auto-name fed Haiku the session's `aiTitle` and FIRST user prompt, both fixed early, so drifted sessions (AEO Product Strategy) kept their opening topic.
- Fix: `server.py` `recent_prompts()` replaces `session_brief()`. Input per tab is now the last `RECENT_PROMPTS = 5` real user prompts (read from the last 2MB of the transcript, deduped, tool results and `<`-wrapped hook/command records skipped) plus the last reply. `aiTitle` and first prompt dropped. `NAME_RULES` tells the model to name the latest topic.
- Verified: autoname on AEO Product Strategy renamed 7 of 9 tabs to match their latest replies (e.g. "Discover Scoring Mechanism" → "Quality Gate Scoring", whose last reply is aeo-quality-gate PR 4; "Acceptance Criteria Writing" → "Peek Attribution Framework"). 1 call, $0.022. Server restarted (pid 19952).

## 2026-10-01 (pull a session out within its group)
- Robert wanted to drag a tab out of a workspace and drop it in the same group's blank space to make it a new workspace there. `/api/split` already did this, but only through the dashed strip at the top of each group.
- Fix in `index.html`: the whole group section now accepts a session drop and splits the session into a new workspace in that group (Ungrouped → new ungrouped workspace). Workspace boxes stop session drags from bubbling, so a drop on a workspace still moves the session and a drop on its own workspace does nothing. A lone session already in the group is refused, because splitting it would only recreate its workspace.
- Verified with synthetic drag events on a throwaway shell tab (OW-TEST): Discover → blank Work space produced a new 1-session workspace in `workspace_group:2`; own-workspace drop sent no request; lone-in-Work refused by Work, accepted by Personal. Test workspace closed after.

## 2026-10-14 (subagent lane)
- Origin: compared a "Session Board" zip (Muse-built, self-reported JSONL event log → SQLite board of agents per session). Kept only its idea, a per-session lane of agents. Its pipeline, goal hierarchy and Muse shim duplicate what cmux + Overworld already do.
- Source: `<transcript stem>/subagents/agent-<id>.jsonl` + `.meta.json` (`agentType`, `description`). cmux's `SubagentStop` events carry no agent id (`extra_fields` redacted), so they can't be used.
- Status: last assistant record `stop_reason == end_turn` with no tool_use → done (detail = final text). Otherwise running (detail = current tool + first string arg), or stopped once silent for 15 min (`STALE_AFTER`).
- Lane shows running agents, plus agents that finished in the last 30 min (`LANE_WINDOW`). Max 6 rows (`LANE_MAX`), then "+N more". Header tally adds "N subagents running". Cached per file mtime.
- Verified: a Haiku Explore agent spawned from Scratch / Session Board Overworld showed as `running · Bash: ls -la …`, then as `done · 5s` with its final text, in /api/state and in the rendered page.
- Not covered: Workflow tool runs (only the subagents they spawn appear). The town status ignores background agents, so a session can show "your turn" while its agents still run.
- 2026-10-17: Robert's call on the status gap: a session waiting on him stays "your turn" even while its background agents run. The meta line now adds "(N agents still running)" so both facts show.

## 2026-10-17 (turn timeline: "why is this taking so long")
- Robert asks this almost daily. ⏱ on any Claude session row (hover), or a click on its subagent lane, opens a right-hand drawer for the current turn (last real prompt → now). It refreshes every 3s; Esc closes it.
- Drawer contents: turn length, a breakdown (model generating / tool calls / waiting on background agents / waiting on you), the 3 slowest steps with their lane, then a swimlane with one row for the main session and one per subagent. Hover a bar for its label and duration.
- `/api/timeline?surface=<uuid>` → `timeline()` in server.py. Segments come from the transcript: model = previous record → assistant record (back-to-back slices merged), tool = tool_use → matching tool_result by id, you = reply → next real prompt, agents = reply → `<task-notification` record. Open calls run to now.
- Prompt detection skips `isMeta`, `isCompactSummary` and task notifications. A reply left open while subagents still run counts as "waiting on background agents", not "your turn".
- The axis ends at the last activity, so a multi-day your-turn tail is reported in the summary instead of drawn. Example: Labs Revenue Mission shows a 59s turn plus "your turn for 5.8d".
- Verified live: Local Harness Eval, turn 12m21, one Bash call (oracle check) took 10m01. Black Book Visibility, 3 forks drawn side by side, its main lane hatched while waiting on them (1m39).

## 2026-10-21 (auto-name reads Antigravity sessions)
- Bug: auto-name named every agy tab "Gemini Argon Agent". `agent_sessions()` kept no transcript for agy, so the namer got zero prompts, and the recap fell back to `read-screen`, whose last lines are agy's model footer ("Gemini 4 Argon").
- Fix: `agy_turns()` reads cmux's agy `transcriptPath` (`~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript_full.jsonl`). Prompts = `USER_INPUT` records (text inside `<USER_REQUEST>`), reply = last `PLANNER_RESPONSE` with text. agy sessions now carry `prompts`, `recap`, `turn_at`, `turn_role`. `NAME_RULES` covers Antigravity tabs and bans Gemini/Argon/Antigravity/Agent.
- Verified: workspace "Gemini Argon Agent" → "Cobot Corp Podcast Transcripts", tab → "YouTube Transcript Pull" (1 call, $0.0003). agy recaps on the map now show the last reply instead of the footer. Timeline (⏱) still covers Claude only.

## 2026-11-06 (message a session from the map)
- Idea taken from AIOffice (github.com/ChristianFJung/AIOffice): talk to an agent without opening its tab. Rest of AIOffice skipped: it runs its own agents outside cmux, so it can't see these sessions.
- ↩ on any agent session opens a box under the card. Enter sends, Shift+Enter = new line, Esc cancels. Renders pause while it is open (same `editing` flag as rename).
- `/api/send` → `cmux paste --submit -` (text on stdin): a bracketed paste plus Enter, so multi-line text arrives as one message. cmux errors return 502 and show in red under the box ("not sent: …") and in the server log.
- Verified on a throwaway Haiku session: a 1-line and a 2-line message, via curl and via the page. Both arrived as one message and got answers. Bad surface id → 502 "Terminal surface not found". Test tab closed.
- Found while cleaning up (not fixed): cmux's `close-surface` now refuses a tab with a running process ("confirmation_required … retry with force=true"); `--force` works. Overworld's × close (`/api/close`) passes no `--force`, so it likely fails silently on live sessions. Not tested from the page. Robert: won't fix, he only closes tabs once their tasks are finished.

## 2026-11-06 (keyboard: reply inbox, move, tick, message several)
- Keys (page must have focus; ignored while typing in a box): r = reply (highlighted card, else the first "your turn" card in map order); j/k or ↓/↑ = move highlight; Enter = open that tab; Space = tick; b = one message to every ticked session; Esc = clear highlight, ticks and the pass.
- Reply box on a "your turn" card: Enter sends and jumps to the next "your turn" card (map order, wrapping), Tab skips, Esc ends the pass. Cards answered or skipped are remembered for the pass (`sent`) because the map's status only changes once the hook fires. On any other card, Enter sends and closes.
- b opens a bar at the bottom naming the targets. Sends go out in parallel; failures are named in red and stay ticked, successes are unticked.
- Highlight and ticks are kept by session id, so they survive the 3s re-render.
- Verified in the automation Chrome with two throwaway Haiku sessions: the page saw only those two as "your turn", and sends to any other session were blocked in the page for the test. r → INBOX-A, box moved itself to the second card → INBOX-B, pass ended; j/k moved; Space ticked both; b → BROADCAST reached both (read back from each tab); Enter fired focus for the highlighted card; Esc cleared. Test tabs closed.
- Not verified: real keypresses inside cmux after ⌘1. Plain letter keys worked before (`a`), but only once the page has keyboard focus.

## 2026-11-06 (keys simplified, per Robert)
- One key per job. r is the only reply key: with cards ticked it opens the bottom bar to message all of them, otherwise the box on the highlighted card (or the first "your turn" card). b removed.
- Arrows move by screen position: the nearest card in that direction, preferring cards that line up with the current one (distance on the other axis weighted 3x). Left/right cross columns and groups. j/k removed (two ways to move would conflict).
- Verified in the automation Chrome with sends blocked: Right ×3 along the Scratch row, Down into Personal, Left across into Work, Up within a column; r with nothing ticked → box on the highlighted card; Space on 2 cards then r → bar addressed to both; Esc cleared. No sends fired.

## 2026-11-06 (show the ask; reply view)
- Problem: cards showed the first ~2 lines of the last reply, but the question or next step sits at the end, so "your turn" cards hid the thing you need to answer.
- Server: `last_reply` also returns the full reply. Sessions carry `full` (last 8,000 chars) and `ask`. `ask_of()` is text-only, no model call: links reduced to their text, URLs dropped (a URL's "?" never counts), "Sources:" paragraphs skipped; then the last question in the last 4 paragraphs, else the last next-step sentence (`ASK_CUE`: next step, only you, should I, want me to, pick, decide, …), else the closing sentences of the last prose paragraph (~120 chars).
- Checked on the 8 live "your turn" sessions: 5 show the real ask ("Which option, A, B or C?", "Should I push the branch…?", "Next step only you can take: ask Austin…"); the other 3 replies ask nothing, so their cards show the closing line. "choose" was dropped from the cues after it matched "want to choose by December".
- Page: "your turn" cards show the ask in brighter text. r / ↩ opens the reply view: the session blown up over the dimmed map, full last message scrolled to the end, reply box focused. Enter sends (+ next on your-turn), Tab skips, Esc or click outside closes. Replaces the inline box under the card.
- /api/state grew to ~110 KB per 3s poll (local only).
- Verified in the automation Chrome with sends blocked: view opened on Apollo Mobile Fix scrolled to its question, Tab moved to the next your-turn session (7 waiting), Esc closed, no sends fired.

## 2026-11-06 (reply view: rendered markdown, ask first)
- Reply view renders the message as markdown (`markdown()` + `inline()` in index.html: headings, paragraphs, lists incl. wrapped/indented items, tables, code fences, quotes, bold/italic/code/links). Builds DOM with textContent only, no innerHTML, so reply text can't inject markup. Tables scroll sideways; cells ≤28 chars don't wrap.
- The ask is pinned at the top in a callout ("Needs from you" on your-turn sessions, "Where it left off" otherwise); the message starts at the top below it. 14px text, 1.6 line height, 980px panel.
- Verified on Sequence Pilot Reps (the screenshot Robert flagged): 8-row table rendered as a table, 3 lists, no raw "|" lines, callout "Next step: confirm the two names with Tim before Monday's call with Nooks."

## 2026-11-06 (the action, worked out by Haiku)
- Robert: the view needs a clear "what is the action / decision", not where it left off. Picking text out of the reply can't state an action when the reply never says one outright, so this is a model call.
- `work_out_action(full, prompt)`: one headless Haiku call (same flags as auto-name, thinking off) with `ACTION_SCHEMA` → `{kind: decision|action|none, action, options}`. Input = the user's last prompt + the reply. Cached by sha1 of the reply in `~/.overworld/actions.json`, so each reply costs one call, once.
- `keep_actions` thread: every 20s, works out the action for every "your turn" session with none cached. `/api/action?surface=` does it on demand for other sessions when the reply view opens (shows "Working out the action…" until it lands, ~5s).
- Cards: "your turn" cards show the action (fallback: the text-picked `ask`). Reply view callout: "Your decision" + option chips / "Your action" / "Nothing needed" (grey, with a suggested next instruction).
- First run: 8 your-turn sessions, $0.0051 total, ~4s each. Examples: "Choose how Austin's roundup guidance enters the Discover sales scorecard…" with chips A/B/C; "Ask Austin to add you as an admin or billing viewer on Apollo, LeadMagic and BetterContact"; "Approve pushing fix/mobile-and-direct and opening it as a stacked PR on top of #14?". On demand: Sequence Pilot Reps → "Ask Tim to confirm Tariq Rana and Mari Kawasaki…" ($0.0007).
- Known wording slip: one "none" suggestion read "Ask me how you can contribute…" ("me" = the agent).

## 2026-11-08 (Waterfall + Agents tabs, ideas from affectUI Pro)
- Built our own versions of affectUI Pro's Trace Waterfall and Agent Tree (paid, not bought; ideas only, no code). The ⏱ drawer now has tabs: Timeline (unchanged) | Waterfall | Agents. Tab and scope are remembered in localStorage.
- Server: `/api/trace?surface=&scope=turn|session&running=0|1` → `trace()` / `_agent()` in server.py. One tree: agent → model calls (deduped by `message.id`, tokens, cost) and tool calls (input/output preview, 1,200 chars) → child agents hang under the tool call that spawned them, linked by `subagents/*.meta.json` `toolUseId` (works at any depth). Session scope returns agents only (small payload). `running` comes from the map's status, because the transcript alone misread idle sessions as running.
- Cost = list price from token counts: `PRICES` table (claude-api skill, cached 2026-10-06), cache writes 1.25x (5 min) / 2x (1 h), per-model cache-read price, Haiku 5.5 >100K tier, fast mode 2x. Unknown models (e.g. `<synthetic>`, gpt) show "no price for …". Same rates as ccusage (within 3% on a token total; the gap is 1-hour writes).
- Waterfall: idle stretches over 30s are squeezed (dashed line) so a 44h turn with 12 min of work stays readable; summary shows wall time and active time; slowest step marked; sub-agents start folded; click a tool call for input/output.
- Agents: tree of cards with status, model, duration, calls, own cost and cost with sub-agents; Whole session / This turn toggle.
- Verified on all 25 live Claude sessions (each request under 0.1s; biggest turn payload 401 KB) and in the browser on "Discover sales rep scorecard" (9 parallel Sonnet sub-agents, $19.72). Live server restarted (pid 59671).
- Not built yet: Context Map (estimate only), Agent Inbox upgrades, Handoff view.
