# UX loop run log

Signals: S1 needs-you recall on the golden set (target 19/19, at most 1 false flag of 12); S2 clicks from load to the first needs-you session (target 1); S3 asks visible on the first screen (target all); S4 open blockers / majors in `plans/ux-backlog.md` (target 0 / at most 4).
Checks: `python3 evals/check_needs_you.py` (S1), `node evals/walk.mjs` against `python3 evals/test_server.py` on :7718 (S2, S3).

| Round | Date | Item | PR | S1 | S2 | S3 | S4 | Cost |
|---|---|---|---|---|---|---|---|---|
| baseline | 2026-11-26 | (main) | | 3/19, 0 false | 2 + Cmd-1 | 0 asks | 3 / 16 | |
| 1 | 2026-11-26 | #1 needs you from the last reply | [#8](https://github.com/robertmnyborg/agent-overworld/pull/8) | 19/19, 0 false (live: same) | 2 | 0/20 | 2 / 16 | $3.19 (ccusage, session 1abe41a4, includes writing the checks) |
| 2 | 2026-11-26 | #2/#7 needs-you list on the first screen | [#9](https://github.com/robertmnyborg/agent-overworld/pull/9) | 19/19, 0 false | 1 | 20/20 | 2 / 15 before the r2 audit; 4 / 19 after it added 9 findings | $4.37 (ccusage, session total $7.56 minus round 1; Fable audit not included yet) |
| 3 | 2026-11-26 | #44 needs-you rules on Robert's corrected labels | [#11](https://github.com/robertmnyborg/agent-overworld/pull/11) | 17/17, 1 false of 14 (3 reclassify runs: 0, 0, 1) | 1 | 18/18 | 4 / 18 | $1.94 (ccusage, session b71422ef; Haiku eval calls not counted, Fable audit not included) |
| 4 | 2026-11-26 | #3 Reply from any view | [#12](https://github.com/robertmnyborg/agent-overworld/pull/12) | 17/17, 1 false of 14 | 1 | 18/18 | 3 / 18 (before the r3 audit's findings) | in round 3's session total |

## Round 1 notes
- Audit step: the 2026-11-25 audit seeded the backlog; the first Fable re-audit runs in round 2, after this PR is live, so it audits the change.
- Live read on the test server: 20 sessions need you (19 golden yes + "Overworld UX Audit", newer than the golden set); galaxy header 3 -> 18 items.
- Two misses found only live, not in the frozen set: an idle compaction record read as a new prompt, and `~/bin/claude-home` sessions whose transcript sits under `~/.claude/projects/-Users-robertnyborg/` while cmux records the launch folder. Both fixed in the PR. `check_needs_you.py` assumes every golden row's last turn is the reply, so it cannot catch this class; the live read did.
- "HubSpot Cleanup Proposal" needs you but belongs to no work item yet, so the galaxy cannot show it until the sorter files it.
- Cost check: $3.19 for round 1 without a Fable audit. 5 rounds with audits project above $20, so round 2 waits for Robert's go.

## Round 2 notes
- The galaxy now opens with a "Needs you" list at the left: one row per session, longest wait first, with tab name, item, wait, the ask in one line and an Open button (goes to the tab). Clicking the row shows its item on the map. The header count now counts these sessions (20), so it matches the list; before it counted items (18).
- The legend moves to the bottom right while the list is up; the map fits to the space right of the list.
- walk.mjs S3 now ignores text scrolled out of view inside a scrolling list; before the fix the check would have passed rows hidden below the fold.
- 20 rows fit at 1440x900. With more than about 20 the list scrolls and S3 will drop; not checked at 900x900.
- Fable re-audit (on the round 1 code, :7718): 9 new findings, 35 to 43 (2 blockers, 5 major, 2 minor), now in the backlog. Round 2 already fixes #41 and part of #35, #36, #38 and #40. Finding 39 says "Parrots Nest" is a false flag, but the golden set labels it yes; only Robert can change that label.

## Label corrections (2026-11-26, before round 3)
- Robert corrected the 10 borderline labels (`~/.overworld/handoffs/2026-11-26-overworld-ux-loop-labels.md`) and earlier in session ruled "Tenet Drafts Review" no (uncommitted finished work). Golden set: 17 yes of 31.
- S1 on the corrected labels, current rules, refrozen kinds: 15/17 caught, 1/14 false flags. Target missed.
  - Missed "AI PM Grade": stalled work that can't resume needs him. The classifier says nothing needed.
  - Missed "Liked AI Stories": now yes. This contradicts the round 3 rule that repackaging offers are FYI; round 3 must undo that rule.
  - False flag "Jev Router Terminal": the agent could take the screenshot itself.

## Round 3 notes
- Rules changed in `ACTION_RULES`: removed "repackaging offers are FYI"; added stalled work = action (including a reply that announces work then ends), checks the agent's own tools can do = none (even "I can't see your screen"), the agent offering more work = decision (but not an offer to undo a small side effect), advice naming a step only Robert can take = action, and "when unsure, flag".
- One Haiku call per reply flipped borderline rows between runs: on the same rules, single runs gave 0 to 2 false flags and once missed a yes. The classifier now takes 3 parallel votes and keeps the majority; with no majority it flags. Cost goes from 1 to 3 Haiku calls per new reply. A failed vote is logged and dropped; all 3 failing still raises.
- The frozen run's one false flag is "Tenet Drafts Review", the label still open with Robert (his main-checkout copy says yes).
- S2/S3 walk first returned 0 sessions because the test server was started inside the sandbox and could not reach cmux; restarted outside it.
- S4 majors 19 -> 18 (#44 fixed). The 4-major target is still far off; that's the backlog's job, not this round's.

## Round 4 notes
- Cause of #3: `openReply` returned early unless a Tabs-view card was on the page. It now builds from the session record; "next" and the waiting count come from the needs-you list when there are no cards.
- Each needs-you row has Reply (outlined) next to Open. Checked on a :7719 stubbed copy with 0 cards on the page: row Reply opens the view, Tab moves to the next session, Esc closes; Inbox row Reply opens it too (it did nothing before).

## Round 3 audit (Fable, on the round 3 code at :7718)
- Report `plans/ux-audit-r3.md` (local). 8 new findings, 45 to 52: 2 blockers, 4 major, 2 minor. S4 after it: 5 blockers / 22 majors (round 4 had already fixed #3, which the audit saw on the round 3 code).
- #45 and #46 mean the live page still misses or over-flags sessions the frozen S1 says are right: cached verdicts ignore rule changes, and a harness record after a reply (task notification, interrupt marker) counts as Robert's turn. S1 forces the last turn to the agent's, so it can't see #46. Both are next, ahead of #35.
- The audit's own S1 run (16/18, 3/13) used the main checkout's older golden copy, not the round 3 labels.
