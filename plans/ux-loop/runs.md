# UX loop run log

Signals: S1 needs-you recall on the golden set (target 19/19, at most 1 false flag of 12); S2 clicks from load to the first needs-you session (target 1); S3 asks visible on the first screen (target all); S4 open blockers / majors in `plans/ux-backlog.md` (target 0 / at most 4).
Checks: `python3 evals/check_needs_you.py` (S1), `node evals/walk.mjs` against `python3 evals/test_server.py` on :7718 (S2, S3).

| Round | Date | Item | PR | S1 | S2 | S3 | S4 | Cost |
|---|---|---|---|---|---|---|---|---|
| baseline | 2026-11-26 | (main) | | 3/19, 0 false | 2 + Cmd-1 | 0 asks | 3 / 16 | |
| 1 | 2026-11-26 | #1 needs you from the last reply | [#8](https://github.com/robertmnyborg/agent-overworld/pull/8) | 19/19, 0 false (live: same) | 2 | 0/20 | 2 / 16 | $3.19 (ccusage, session 1abe41a4, includes writing the checks) |
| 2 | 2026-11-26 | #2/#7 needs-you list on the first screen | PR_URL | 19/19, 0 false | 1 | 20/20 | 2 / 15 | COST |

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
