# Overworld UX loop (approved by Robert 2026-11-26)

Job card waiver: personal internal tool with one user (Robert); his complaint in the 2026-11-25 capture is the buyer evidence. Claude, 2026-11-26.

## Goal
Robert opens the Overworld and, from the first screen, sees every session that needs him, what it is asking, and can act on it in one click.

## Closing signals (script-checked, reported every round)
| Signal | Baseline 2026-11-26 | Target |
|---|---|---|
| S1 needs-you recall on `evals/needs-you-golden.jsonl` (19 yes of 31) | 3 of 19 flagged (map status `waiting`) | 19 of 19, at most 1 false flag among the 12 no's |
| S2 clicks from load to first waiting session (scripted walk) | 2 + Cmd-1 between sessions | 1 |
| S3 recap/ask of each session visible without opening anything | no | yes (asserted in walk) |
| S4 open audit findings, blocker / major (`plans/ux-backlog.md`) | 3 / 16 | 0 / at most 4 |

Checks live in `evals/` (to be written in round 1): `check_needs_you.py` (S1, runs the server's status logic on the frozen tails, no live state), `walk.mjs` (S2, S3, automation Chrome against the test server).

Note: the server's existing action classifier (`action.kind` in action/decision) already agrees with 17 of the 19 yes labels and all 12 no's. Blocker #1 is mostly wiring that into status, plus the 2 sessions it has no action for (one has no reply parsed, one is a recap line).

## Guardrail
Refuse to miss a session that needs Robert. A false flag costs a glance; when unsure, flag.

## Each round
1. Fable re-audits the live page at http://127.0.0.1:7717, GET only, with every POST stubbed. New findings go into `plans/ux-backlog.md` (seeded from `plans/ux-audit-2026-11-25.md`, 34 findings).
2. Pick the top open item (blockers first, then by audit rank).
3. Build it on a branch in a worktree. Test against a second server on port 7718 with all POSTs stubbed. Never restart the live server, never move, close or message Robert's real tabs.
4. Run S1 to S4. Keep the change only if no signal gets worse. Commit, open a PR on robertmnyborg/agent-overworld. Robert merges.
5. Append a row to `plans/ux-loop/runs.md`: round, item, PR, S1 to S4, cost.

## Stops
- 5 rounds per run.
- Targets met.
- Same item fails twice: stop and ask Robert (the item is ambiguous).
- Two rounds in a row with no signal movement: stop and re-plan.
- Cost: measure round 1 with ccusage. If 5 rounds would exceed $20, ask before continuing.

## Golden set
`evals/needs-you-golden.jsonl`: 31 live sessions frozen 2026-11-26 with their last-reply tails, pre-labeled by Claude, 10 borderline rows marked for Robert's spot-check. Never relabel to make a change pass; only Robert's corrections change labels.
