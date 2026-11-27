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

## 2026-11-08 (Context, Handoffs, Inbox: rest of the affectUI Pro ideas)
- Drawer tabs are now Timeline | Waterfall | Agents | Context | Handoffs.
- Context (`/api/context?surface=&agent=`, `context_map()`): treemap of the latest model call's context window for the main session or any sub-agent (picker). Total is exact (input + cache read + cache write of the last call). The split is estimated: system prompt and tool definitions from the `api-request-shape` record Claude Code writes, the rest from transcript text since the last `compact_boundary` (conversation, tool calls, tool results, files by path, CLAUDE.md + memory, skills, reminders, hooks), scaled to the exact total. Images count as ~1,600 tokens, not their base64 length. Free space is the dashed tile (limit 1M; Haiku 4.5 200K).
- Handoffs (`/api/handoffs?surface=`): each `/spinoff` edge (in or out, brief text) and each sub-agent (prompt given, final report). Chips: files and links the brief names (went along), and struck-through files the parent read or edited in the 30 min before that the brief never names. Screenshots, scratchpad, /tmp and tool-results files are filtered out as noise.
- Inbox (header button or `i`): every agent session plus running background sub-agents in one list, tabs Needs you / Working / Finished / All with counts, stable title order. A row unfolds to its last 6 steps (`/api/steps`, cached 5s so the 3s redraw doesn't wipe them) and Open / Reply / Waterfall, plus the Haiku-worked-out option chips on "your turn" rows (each sends that text to the session).
- Cost caveat found: Claude Code's own `cost-state` record ran ~15% above the transcript-based total for the same session; it counts calls the transcript never records. Waterfall costs are a slight undercount.
- Verified: all endpoints on all 26 live Claude sessions (each under 0.5s); browser checks of Context (Affectui session, 357k of 1M), Handoffs (Multi Provider Loops, 3 sub-agents, 1 real file flagged) and Inbox (steps survive the redraw). Live server restarted (pid 92741).

## 2026-11-08 (weekly usage meter)
- Header shows the weekly limit like the Claude desktop app: bar, %, reset time + countdown, "on pace for N%" (straight-line projection to the reset; amber at 80%+, red "on pace to run out <day time>" at 100%+), and a sparkline of this week's readings.
- Source: `https://api.anthropic.com/api/oauth/usage` (header `anthropic-beta: oauth-2025-04-20`) with the Claude Code login token read from Keychain `Claude Code-credentials` each poll (Claude Code keeps it fresh). `keep_usage` polls every 5 min and appends to `~/.overworld/usage.jsonl`; `/api/usage` returns the latest reading + this week's history. Page refreshes every 60s.
- Endpoint gives whole percents only, and `resets_at` jitters by ~1s (23:59:59.8 vs 00:00:00.4 UTC); the page rounds it to the minute.
- Verified on a test copy (:7718): live reading 10%, resets Thu 4:00 PM PST, on pace for 23%; fake 35% → amber 82%; fake 60% → "run out Tue 3:56 PM"; server down → red message. Header is now 2 rows (key hint on its own line), 67px.

## 2026-11-08 (quick capture)
- `POST /api/capture {text}` in `server.py`. If the text has a Slack link whose thread already has a tab (`~/.overworld/threads.json`, key = channel + thread ts, so reply links and top-level links of one thread match), it pastes the note into that tab. Otherwise it opens a new Claude tab in Scratch from a brief in `~/.overworld/captures/`. The session reads the source with its connector, moves and renames its own tab (`cmux move-surface --surface $CMUX_SURFACE_ID`), then does the work.
- Global hotkey: Hammerspoon (brew cask), `~/.hammerspoon/init.lua`, ctrl+alt+cmd+N. Prefills a link from the clipboard if it changed since the last capture. Needs the server, so it fails while cmux is down (the alert says so).
- Verified: a Slack reply link started a session that read the thread and filed itself as Parrots / Morgan Regional Managers. The top-level link of the same thread continued that tab. Not yet verified: a real keypress through Hammerspoon.
- Only Slack threads continue. Gmail/Jira links always start a new tab.
- Screenshots: if the clipboard holds a new image when the hotkey fires, Hammerspoon saves it to `~/.overworld/captures/<ts>.png` and appends `Screenshot: <path>` to the note. The brief tells the session to Read it. Verified: `hs -c 'return saveClipImage()'` saved a valid PNG, and a capture with that path got a correct one-line description and filed itself. `hs.ipc` is on, so `hs -c` can test functions without a keypress.

- 2026-11-09: keypress confirmed by Robert. Hover version: with Slack in front and no new link on the clipboard, the hotkey right-clicks under the mouse, presses L (Copy link), and prefills the permalink; if nothing copied it presses Escape and opens the plain box. Needs Accessibility for Hammerspoon (first press opens the prompt). Brief now also reads the Slack channel after the message (unthreaded replies). `hs -c 'hs.reload()'` can hang the client; wrap with `perl -e 'alarm 8; exec @ARGV'`.

## 2026-11-11 (capture: never file into a group; bigger box)
- Bug: the capture brief listed cmux's generated group anchors (the Work/Personal folder headers) as workspaces, so sessions filed tabs into the group itself. The Work anchor (workspace:1000020002) was renamed "Auto-approve workflow failure logs" by one.
- Fix in `server.py`: `capture_listing()` drops anchors and lists workspaces under `## Group <name> (group ref …)` headers. Rules: never move into a group itself; use a workspace that fits, else `cmux new-workspace --group <ref> --name <name>` and move there, else stay in Scratch; never rename a workspace or group. Verified `new-workspace --group` lands in Work (throwaway created and closed). Server restarted. A real end-to-end capture under the new rules is not yet verified.
- Hammerspoon: `hs.dialog.textPrompt` (one line) replaced by a 760x360 resizable webview with a wrapping textarea. Enter sends, Shift+Enter new line, Esc cancels. Verified by opening it via `capturePrompt` (global for testing) with a long Slack URL and closing it with Cancel. Backup: `~/.hammerspoon/init.lua.bak-2026-11-11`.
- `hs -c` gotcha: returning a timer/userdata object from `hs -c` gives "_coresetup.lua:26: stack overflow"; end test commands with `return "ok"`.
- Left as is: the Personal anchor (workspace:1000020007) holds a real tab, "Room Of Me", which the map hides because anchors are hidden.

## 2026-11-11 (work items, option C; branch feat/work-items, uncommitted)
- Problem (session "Open tab sprawl across spaces"): a tab was the only home for a piece of work, so re-entry meant hunting tabs, any ping off the exact Slack thread opened a duplicate tab, and nothing could be parked (29 of 56 tabs were dead shells). Plan: `plans/work-items.md`.
- Work item = record in `~/.overworld/work.json` (title, goal, people, sources, state active/parked/done, note/next/waits_on, sessions keyed by transcript path because surface ids change on cmux relaunch, per-session meta for resume). cmux workspaces untouched; people are a field, not an item.
- Seed: `/api/work/seed`, one Sonnet call over all agent tabs → proposal reviewed on the page (rename, people, move tabs, leave out) → Accept. Real run: 25 tabs → 16 items, 16s, $0.075. The 7 per-rep Rep Help tabs became one item.
- `keep_work` (30s): tabs on no item get attached to an existing item or start one flagged "new" (Haiku). Parked item whose tab comes back flips to active.
- Park (`/api/work/park`): Haiku writes note/next/waits_on, then `close-surface --force` on its tabs. Resume: `claude --resume <session>` in the last workspace (Scratch if gone) and cwd; same transcript, so the tab rejoins its item.
- Capture: Slack thread on an item's sources → that item; else Haiku route (confident only) → paste into its live tab, or resume it with the note. No match → old new-tab flow.
- Page: Work view default (`w` toggles to the tab map). Sections Needs you / Working / Open / No live tab / Parked (on you, on others) / Not on an item / Old tabs with no session (× force-closes plain shells) / Done. Drag tab onto item = move, onto dashed zone = own item, item header onto item = merge (asks in a bar).
- Verified end to end on a throwaway Haiku tab: auto-sorted to its own new item ($0.0014), parked (4.7s, tab closed), resumed (history kept, rejoined item), capture routed to it confidently ($0.0015) and delivered. Test tab closed.
- Live server restarted on this code (pid 75659). work.json holds the 16-item proposal, not accepted: Robert reviews it.
- Not verified: drag-and-drop and merge with real mouse input; a capture that resumes a parked item through the hotkey.

## 2026-11-11 (diff review, accepted, capture routing notice)
- Seed review is now a side-by-side diff (workspaces/tabs left, items right, one colored line per tab, hover isolates, drag a tab to move it). Robert accepted 16 items.
- Captures: every hotkey note logs to `~/.overworld/captures.jsonl` with where it went and why (route call now returns a reason). Hotkey alert shows "Sent to <item>: <reason>. Wrong? Fix it in Overworld." for 7s. Work view top: "Recent captures" (24h, 6 rows), each with a "Wrong? Move to…" menu (another item or New tab). `/api/capture/redirect`: tells a wrongly continued tab to ignore the note (or closes a tab opened only for it), unlinks the Slack thread, then delivers to the new target.
- Bug found and fixed: a capture moved to a new tab got re-filed by the sorter into the item it was moved out of. `work.json` `avoid` {surface: item} makes the sorter give that tab its own item instead. Verified with throwaway tabs (OWTEST3); test tabs, items and log rows removed.
- Decided: groups should be by goal, not by who's asking; people are found through capture routing + item people. Next: sender tagging on items, then goal groups in the Work view (open question: mirror in cmux sidebar or not).

## 2026-11-11 (senders, goal groups, work map)
- Sender tagging: capture briefs and item deliveries tell the session to POST `/api/work/sender` {surface, person, ask} once it has read the source. Goes on the tab's item (`asked_by`, added to people), or waits in `pending_senders` until the sorter files the tab. Verified both paths with a throwaway tab.
- Goal groups (Overworld only, cmux sidebar untouched): `/api/work/groups` = one Sonnet call grouping items by the objective they serve. First rules gave domain groups ("Parrot Automation Tools"); tightened (few groups, a tool is never a goal, "this quarter I'm trying to <title>" test) → 4 groups: Grow Discover Sales Revenue (7), Support And Coach Sales Reps (3), Build My Agent Tooling (4), Grow AI Community Presence (2), $0.016. New items from the sorter pick a group.
- Robert: the card grid "doesn't achieve its goals"; he wants to see open sessions and what they serve, like the review diff. Work view is now a 3-column map: spaces and tabs → work items → goals, curved lines per link, hover traces the chain (tab → item → goal; goal → items → tabs). Item hover shows Park/Resume/Done; drag tab→item (move), item→goal (regroup), item→item (merge, asks). Card grid code removed.

- 2026-11-12: Work map click-to-pin (click a box keeps its chain lit; click it again, empty space or Esc clears). Arriving in the Overworld pins the tab you came from: server thread keep_came_from polls cmux tree every 1s and exposes state.came_from {id, at}; page pins and scrolls to it (Tabs view selects it).

## 2026-11-12 (captures clickable, capture box movable, send confirmation)
- Recent captures: click a row → opens its session (`/api/focus`); if its session is gone, pins and scrolls to its item. Hover lights the chain in the map (tab → item → goal), or the item when the tab isn't drawn (exited sessions are hidden). Verified in the automation Chrome with focus calls intercepted: 4 rows opened the right surfaces, hover lit the expected chains, mouse-out cleared.
- Hammerspoon box: drag the top strip to move it (JS posts deltas, Lua moves the window); position and size saved in `hs.settings` `capture.frame` and reused if still on a screen. Verified by synthetic drag (+60/+40), reopen landed at the saved spot, height stable. Backup `~/.hammerspoon/init.lua.bak-2026-11-12`.
- Confirmation: instant "Capture received, finding where it belongs…" alert on send, replaced by "✓ <where it went>" (8s) plus a macOS notification "Capture filed" that stays in Notification Center. Not yet verified with a real send.
- hs -c gotcha: after a hung `hs.reload()` every call returned "stack overflow"; quitting and relaunching Hammerspoon fixed it. Test JS passed to `evaluateJavaScript` must not redeclare the page's top-level consts (wrap in an IIFE).
- Capture box redesign (same day): a leading link becomes a chip above the note ("Slack message <channel>", × drops it); screenshot shows as a chip; system font with whole-word wrap (old `word-break:break-all` split words); corner grip resizes (custom, via the same JS→Lua channel as the header drag, min 420x200); default 600x260. Sent text = link + note, same format as before. Verified by screenshots (`screencapture -l <hswindow id>`; `screen:snapshot(frame)` grabbed the wrong area) and synthetic grip drag (600x293 → 720x373). Title bar stays light in dark mode: `webview:darkMode` and `hs.preferencesDarkMode` both left it light; reverted. `hs -c 'hs.reload()'` hangs even under perl alarm; restart the app instead.

## 2026-11-19 (Galaxy view, option A of 3)
- Robert's job: track work and see its lineage as a context graph; Borderlands-style galaxy map but flat. Options offered: A galaxy map, B subway timeline, C free-form graph. Picked A, with B's timeline as the planet view.
- Page: `g` or the Galaxy button. Goals = star systems (suns), work items = planets on orbit rings (needs-you first, dormant on the outer rings, faded), size = session count, amber beacon = needs you. Pinch/⌘-scroll zooms, drag/scroll pans, click a sun = fly into that goal, click a planet = side panel, Esc goes up, 0 fits all. Breadcrumb top left; link-kind filter + dormant toggle bottom left.
- Planet panel: status, goal, next, waits on, Open tab / Resume / Park, History (one row per session on a shared time axis: first to last turn, tick per prompt, sub-agent count, purple curve = spun off from a sibling session via a /spinoff brief), Linked items (click flies there), projects, PRs, Slack threads, files edited.
- Server: `/api/galaxy`, `/api/planet?id=`. Per-transcript facts (time span, prompt times, cwd, files edited, project folders, Slack threads from prompts, PR links in replies, handoff briefs written/read, sub-agent count) cached in `~/.overworld/facts.json` by mtime: cold 2.5s for 112 transcripts / 544 MB, warm instant.
- Links are inferred, nothing new recorded: spinoff (item A wrote the brief a session of item B was started on; works across cmux relaunches, unlike edges.jsonl surface ids), same Slack thread, same files (ignoring files on >6 items), same project folder, same person (first name). Project and person links show only on hover (212 project links would be a tangle).
- Dormant = derived, never written: active item, no live tab working or waiting, no transcript activity for 5 days (`DORMANT_DAYS`). First run: 81 items, 26 dormant, 9 need you.
- Findings: no two items share an edited file (0 file links), only 3 spinoff and 2 thread links; 45 of 81 items have no goal (sorter goal-pick isn't covering new items). "Sort into goals" button on the map reruns `propose_groups` (Sonnet, ~2 cents) and replaces current goals; not run, Robert's call.
- Verified in the automation Chrome with POSTs stubbed: galaxy renders, planet click opens the panel and flies to the item, linked items list the 2 cross-item spinoffs. Live server restarted (pid 31773). Not committed.
- Not verified: real trackpad pinch/pan, Open tab / Resume / Park from the panel (stubbed).

## 2026-11-19 (galaxy is the default)
- Robert: "galaxy map isn't working". Cause: his cmux Overworld tab never reloaded, so it was still running the old page (no galaxy code). Fix: `/api/state` returns the page's mtime (`page`), and the page reloads itself when it changes. Verified: an index.html edit reached his tab within one tick.
- The galaxy now opens on every load (the stored view is ignored); `w` and `g` still switch views for the current visit.
- cmux's browser is WebKit: pinch zoom comes through gesture events, now handled alongside ctrl+wheel.
- Arriving in the Overworld from a tab opens that tab's item in the galaxy.
- Goals re-sorted at Robert's request ($0.08, 18s): Equip Sales Reps To Win 31, Build My Agent Tooling 20, Personal Life Admin 14, Grow Peek Product Revenue 10, Next Career Move 6; 0 without a goal. This replaced the old 4 goals.
- Verified in his live tab (cmux browser eval + screenshot): galaxy renders 81 planets in 5 systems; sun click zooms in, Fit returns. Server restarted.

## 2026-11-19 (Darlene's design review, all five changes)
- Source: "Design Advice" Gemini notes + transcript, 2026-11-19 (Darlene Tjahjo). Her model: goals = planets, work items = landmasses, sessions = cities, roads between; flat; the group blinks when something needs you ("air control system"); blow things up.
- Built: (1) goal suns pulse amber with "N need you" while any item needs you; (2) "Next that needs you (N)" button + `n` key cycles through them and opens each; (3) clicking an item zooms into its session map: sessions as square cities on a ring around the item, spokes to the item, purple roads for spinoffs, live ones click to open; everything else dims; (4) shared project folders drawn as hexagon hubs (2-12 items each, 41 hubs) with dashed roads to their items, replacing 212 item-to-item project lines; hidden zoomed far out; (5) distinct shape per level (sun / circle / square / hexagon, legend key) and bigger items: goals packed by size, items never under ~10px on screen.
- Fixes found while testing: transcripts with no turns made the history start in 1970 (now skipped, and left off the session map); a hidden cmux tab (0 width) produced a negative zoom, so fitting now waits until the tab has a size.
- Verified in the automation Chrome: 3 goals pulse, n visits 3 needs-you items in order, Harness Doctrine Updates opens 4 cities + history. In Robert's cmux tab the page hadn't reloaded yet (hidden tabs don't tick; it reloads when shown). Not committed.

## 2026-11-19 (dock a session beside the map)
- Robert: clicking a session took him to its cmux tab and away from the galaxy; wants it in the right pane. Options: A dock the real tab, B read/reply view in the panel. Picked A.
- `/api/dock {surface}`: moves the session's real tab into the Overworld workspace (`move-surface`, then `split-off right`), focuses it, records home pane + index in `~/.overworld/dock.json`. Docking another first sends the current one back. `/api/undock` returns it to its pane at its old position (its workspace if the pane is gone, Scratch if that's gone too).
- Page: city click, history row click and "Show beside map" dock; "Go to tab" keeps the old jump; breadcrumb shows "Docked: <title> · Send back". The map refits its current level when the pane narrows it.
- The map keeps a docked session under its home workspace (state() reads it from the Overworld workspace), so its item, status and sorter attachment don't change. `/api/focus` on a docked tab focuses it in the Overworld.
- Gotchas found: cmux applies a move a moment after answering OK, so dock/undock wait until the tree shows the move (`_settle`, up to 3s); a dock record younger than 10s is trusted even if the tree lags; state() reads the dock record before the tree. Closing a docked tab clears the record.
- Verified with throwaway tabs: dock, undock to the same index, 3 back-to-back swaps under concurrent map polling, closed-tab cleanup. Page wiring checked in the automation Chrome with POSTs stubbed. Not yet done on a real session; not committed. Known gap: a cmux relaunch while docked leaves that tab in the Overworld workspace (new surface ids), move it home by hand.
- 2026-11-19 (later): leaving the docked session's item (opening another item, `n`, Esc/up a level, Fit, closing the panel) now sends the docked session home; opening another session already swapped. dock.json is written atomically (the map refresh had hit a half-written file: JSONDecodeError in state()). Docks and send-backs are logged in server.log. Verified with stubbed POSTs: opening its own item sends nothing, another item or the galaxy level sends /api/undock. First real dock seen: QUEST-480 Hunter cleanup from Parrots.

## 2026-11-19: Galaxy search
- Search box under the breadcrumbs (key `/`). `GET /api/search?q=` matches items whose name, goal, next, note, waits-on, people, projects, edited files or prompt text hold every word. Prompt text (last 300 prompts per transcript, 600 chars each, system-reminder/command tags stripped) is now cached in facts.json as `texts`; entries without it are re-read once.
- Matches get an orange ring and a name bubble; the rest dim. Bubbles that would cover a better-ranked one are hidden until you zoom in. Hovering a bubble shows the matched line; the hover card also shows it. Enter / Shift+Enter open the next / previous match; Esc clears.
- Verified in the automation Chrome: "hunter" 14 matches, stepping, clearing, no-match text, two-word query, matches survive the 3s refresh, no console errors.

## 2026-11-19: Galaxy motion pass
- Plain JS/CSS, no library (Magic UI / Animate UI are React+Tailwind; not worth a rewrite). All motion off under prefers-reduced-motion.
- Camera: one cancel token (`G.anim`, `gStop()`); grabbing the map or starting a new motion stops the old one. Fly-to uses an ease-out with ~2% overshoot (480ms). ⌘-scroll, ctrl-wheel and +/- zoom ease toward a target (`gZoomBy`). Releasing a drag mid-swipe glides to a stop (`gGlide`, 230ms decay). Two-finger scroll keeps the trackpad's own momentum.
- Fades: planets, links, roads, hubs fade 180ms on focus/search. Opening an item: spokes grow, sessions fade in staggered 28ms apart; search bubbles rise in staggered; the item panel slides in.
- Verified in the automation Chrome: one wheel notch zooms over ~100ms to the same final zoom as before, a 120px drag glides on, fly-to and city entrance render, no console errors.

## 2026-11-19: Galaxy legibility pass + minimap
- Worktrees (extra branch checkouts like parrots-nest-QUEST-477) fold into their main repo at read time (`main_repo()`, also by name when the folder is gone): 46 project hubs -> 35.
- Project roads and hexagons are off by default (storage key bumped to `ow.gkinds3`); a planet's roads still show on hover/open. Labels at galaxy level only for needs-you / working / hovered / search hits; inside a goal every active item is labelled; dormant items are faint 8px dots with no label. Other goals fade to 7% while you're inside one (`away` class, kept through `gStatusPatch`). Legend collapsed to one "Legend & filters" line (remembered).
- Minimap bottom right (moves left of the item panel) whenever the whole galaxy isn't in view: goals, item dots (blue working, orange needs you), and a rectangle for the current view. Click to fly there, drag to scrub. Camera tween factored into `gTween`.
- Removed the auto-open on arrival (`gCameFrom`): switching to the Overworld no longer flies into the item you came from; the camera stays where you left it.

## 2026-11-19: Reopen closed sessions into the dock
- Docking only ever worked for sessions with an open tab; clicking a closed session did nothing (user hit this on "New Discover Report Run", both sessions closed).
- Now a closed Claude session city is clickable: `POST /api/work/resume {id, transcript, dock: true}` reopens that exact transcript (`resume(..., transcript=)`), waits for the new tab to appear in the tree, and docks it. The panel's Resume became "Resume beside map" (latest session, docked). The flat Work view's Resume still switches to the workspace.
- Verified: client sends the right request (stubbed POST in Chrome); server path tested with a throwaway OWDOCKTEST tab: new tab visible after 0.2s, docked into Overworld, sent back to Scratch, closed.

## 2026-11-19: Depth pass (option B)
- Planets, suns and cities share one highlight-and-shadow overlay (`#gshade`), so they read as lit spheres; suns get a hot-core gradient (`#gsun`).
- Working items glow blue and items that need you glow amber (CSS drop-shadow on those only).
- Each goal sits in a faint coloured haze (`.nebula`, 5 hues); it fades with the other goal when you're inside one.
- Parallax stars: a canvas behind the map (`gStars`, called from `gApply`) with 3 layers that move 6%, 16% and 32% as much as the map. Redraw costs ~0.2ms a frame.

## 2026-11-19: Star-system pass (option A)
- Layout (`gLayout`): one orbit per item, gaps widen outward (36+4n world units), golden-angle placement nudged so planets keep 56 units clear. Needs-you items orbit closest. Dormant items form an outer asteroid belt (dotted `.belt` rings). Galaxy grew from ~2x to 6365x5126 world units.
- Planet look from a stable hash of the item id (`gHash`): gas giant (3 band patterns), cratered rock, ice (frost cap + thin atmosphere), ringed giant (ring drawn behind and in front). Idle planets get their own muted hue; working/needs/done colours unchanged. Size varies +-15% around the sessions-based radius.
- Suns: size grows with item count (46 + 8*sqrt(n), max 92); under 7 items an orange dwarf, under 14 a yellow sun, else white-hot. Each has a corona.
- Names: inside a goal, names show at any zoom and sit just under the planet. `gLabelCull` hides names that would land on another planet or name (needs-you and working keep theirs first); hover or pin shows a hidden name.

## 2026-11-19: Design-review fixes (Fable 5.2 review, all 12)
Review screenshots: `.shots/review-*.png`; after: `.shots/fix-*.png`.
1. Needs-you planets always show their name (amber, bold) at every zoom; the breadcrumb button names the next one ("Needs you: <title> (+n)").
2. `gAutoSys`: zooming in by hand past 2x the whole-galaxy zoom with a goal under the screen centre makes it the current goal (names + breadcrumb); below 1.5x it leaves.
3. A goal opens fitted to its inner 8 orbits (`s.inner`), not its full reach: zoom 0.27-0.38 -> 0.52-0.92; planets 21-54px instead of a flat 20px.
4. `gFit` keeps a 64px top band clear for breadcrumb/search. Inside a goal the floating title/count hide; the breadcrumb carries "N active · N needs you".
5. Amber only means needs-you: search rings/bubbles are white/blue, minimap goal outlines grey, goal counts muted, small-goal suns are red dwarfs.
6. Search never dims needs-you items; bubbles keep clear of the breadcrumb, search box and results list.
7. Header hint line shows galaxy keys while in the galaxy.
8. Minimap dots are fixed screen sizes: needs-you 4px with a pulse, working 2.5px.
9. Search results list under the box (title, status, goal, matched snippet). Arrow keys light the planet without moving the camera; Enter or click opens.
10. One-session items (47 of 63 active) open the panel without flying in or drawing cities; camera only moves if the planet is off-screen or under the panel. "Show/Resume beside map" is the filled primary button. The panel now starts below the header.
11. Systems pack to the real viewport shape (clamped 1.2-2.6); orbit gap growth capped at 64. Galaxy 6365x5126 -> 6394x4090, fit zoom 0.128 -> 0.145.
12. Idle hues limited to 240-340 (purple to rose). A ring now means "has an open tab" (ring shown via `.live`); surface type (gas/rock/ice) stays decorative. Legend explains colours and rings.

## 2026-11-25 (capture prompt: announce tab moves)
- `server.py` capture template, step 2: the agent now opens its reply with "Moved: <old workspace / tab> -> <new workspace / tab>. Same conversation." when it moved or renamed the tab, so an unexpected notification explains itself. Same rule added to `~/CLAUDE.md` Communication.
- Merged (PR #6) and live server restarted on it (pid 39499), 2026-11-25.
- Next: confirm the next capture that moves a tab opens with the Moved line.

## 2026-11-25 (UX audit, no code changed)
- Report: `plans/ux-audit-2026-11-25.md`; screenshots `.shots/ux-audit-01` to `-14`. 34 findings: 3 blockers, 16 major, 15 minor.
- Blockers: "3 needs you" missed 9 open sessions whose last reply asks for an action or decision (they read idle and sit on dormant planets); the galaxy shows no recap or reply box; Inbox Reply does nothing outside the Tabs view.
- Top change proposed: count an open ask as needs-you until answered or dismissed, and open on a needs-you list instead of the galaxy. Nothing built; Robert picks.

## 2026-11-26 (UX loop round 1)
- Loop approved; spec `plans/ux-loop/SPEC.md`, log `plans/ux-loop/runs.md`, backlog `plans/ux-backlog.md` (seeded from the audit).
- Checks: `evals/check_needs_you.py` (S1, frozen golden set), `evals/test_server.py` (read-only copy on :7718, POSTs stubbed, no threads, no model calls), `evals/walk.mjs` (S2, S3 via CDP on :9223).
- Round 1 (branch `feat/needs-you-from-reply`): "needs you" now comes from the last reply. `needs_you()` in server.py: waiting status, or an unanswered reply whose worked-out action is action/decision, or (before that action exists) an ask in its text. Actions are worked out for every unanswered reply, not only "waiting" ones. A session that needs you shows as "your turn"; a "waiting" one whose reply asks nothing shows idle. Compaction records no longer count as a new turn; claude-home transcripts are found under the home project folder.
- S1 3/19 -> 19/19 with 0 false flags; galaxy header 3 -> 18 needs you. S2 and S3 unchanged (2 clicks, 0 asks on the first screen): next items are #2/#3 and the needs-you list.
- Waiting on Robert: merge the PR and restart the live server; go/no-go on rounds 2-5 (projected above $20).

## 2026-11-26 (UX loop round 2)
- Branch `feat/needs-you-list` (stacked on round 1): "Needs you" list on the galaxy's first screen with the ask and a one-click Open per session; header count = sessions that need you. S2 2 -> 1 click, S3 0 -> 20/20.
- Round 2 Fable re-audit ran against the round 1 code on a :7718 test copy (PR #8 not merged yet); its findings go to `plans/ux-audit-r2.md` (local) and the backlog.

## 2026-11-26 (UX loop: Parrots Nest label)
- Robert ruled: when the requested work is done and the only ask is to start a fresh session (/spinoff, /compact), that is an FYI, not needs-you. Golden row "Parrots Nest" relabeled no (local file); the action classifier rules say so.
- `evals/check_needs_you.py --reclassify` re-runs the current classifier on the golden replies (one Haiku call per row, no cache). New rules: 16/18, 1/13. Old rules: 16/18, 2/13. The 2 misses and 1 false flag are on both, logged as backlog #44.
- Robert's second ruling: an optional offer that only repackages finished work (shareable page, Confluence doc, email draft) is FYI. Next steps that move the goal (commit, push, PR) should just happen, with a PR and tagged reviewer when one is needed; that rule went into ~/CLAUDE.md, not the classifier. Fresh classifier run after both rules: 17/18, 0/13 (miss: "Communication harness", which ends on an uncommitted note).
- Robert's third ruling: finished work left uncommitted is the agent's own next step, not needs-you. "Communication harness skills and hooks" and "Tenet Drafts Review" relabeled no; classifier rule added. Golden kinds refrozen on the new rules (`--refreeze`; labels untouched): S1 16/16, 0/15 false.

## 2026-11-26 (Impeccable UI/UX critique + cockpit overhaul; branch feat/ui-design-40)
- Updated Impeccable skill to v4.11.1 (`npx impeccable update`), added `PRODUCT.md` and `.impeccable/config.json` (`buildPath: "code"`), and recorded the baseline dual-agent audit in `plans/ux-audit-ui-2026-11-26.md` (local only; baseline score **15/40**).
- Rebuilt `index.html` into a unified dark cockpit:
  - **Triage default view (`1`/`t`):** Prioritized 2-column `Needs you` queue (recent <24h asks first, ended shells clearly marked `Ended` with `Resume` instead of broken Reply, `Dismiss` + `Dismiss older` with Undo toast, 2-click armed inline decision option chips) above a unified `By workspace | By goal` board with full readable titles, compact counts, and collapsed dormant/capture folds.
  - **Universal Session Sheet:** Merged Reply + 5-tab Turn Diagnostics (`Timeline`, `Waterfall`, `Agents`, `Context`, `Handoffs`) reachable from every view with preserved Reply drafts across tab switches, disabled empty Send, explicit `Open tab` / `Dock beside` / `Dismiss` / `Close`, and fixed `span()` collision (`fmtSpan()` vs `spanBetween()`).
  - **Links (`2`/`w`) & Galaxy (`3`/`g`):** Responsive 900px split-pane support (`52px` single-row header, `0px` horizontal overflow across all views), muted Links wires until hover, uncluttered Galaxy without permanent `.gneeds` rail (optional drawer at all widths), dynamic collision-free system/planet/history-date labels (`0` SVG collisions at 1440px and 900px), fixed 0px search dropdown, `gStop()` cleanup on view switch, 2-click arming on destructive/LLM controls (`Park`, `Auto-name`, `Regroup`, `Sort`), global `/` search covering live sessions + dormant items, `?` shortcuts modal with focus trapping/restoration, and non-destructive poll error banner.
- Verified on read-only test server (`:7721`) via `impeccable detect --json` (`[]`, exit 0), `evals/walk.mjs` (`S2 = 1` click, `S3 = 18/20` above fold), automated Chrome CDP measurements at `1440x900` and `900x900` (`0` console errors, `0` visible WCAG AA contrast failures, `0` horizontal overflow, `0` SVG collisions), and a second independent dual-agent re-critique (score jumped `15/40 -> 28/40` on pass 1, followed by fixing all 6 remaining pass-1 findings in pass 2).
