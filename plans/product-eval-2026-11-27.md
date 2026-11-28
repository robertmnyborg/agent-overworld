# Agent Overworld: product self-interview, 2026-11-27

Trigger: Robert, "I'm not seeing the progress I wanted." Method: product-thinking Why Gate + demand check, then PM-loop questions answered from logs and live state. A second, independent interview by agy is appended at the end.

## Evidence (measured 2026-11-27, `/api/state` + `~/.overworld/*`)
| Fact | Value |
|---|---|
| Open tabs | 42: 18 needs you, 12 dead shells, 9 idle, 3 working |
| Age of the 18 asks | 12 are 5.9 days old, 6 are 2.2-3.3 days |
| Needs-you count over time | 19 on 11-26, 18 on 11-27 (not draining) |
| Live false flags by Robert's own rules | at least 3 of 18 ("I can turn this into a shareable page", "Run /compact…", "Checking the harness evidence now.") while the golden set scores 18/18 |
| Work items | 128, all `active`. 0 parked, 0 done, ever. Resume used 4 times |
| Captures (hotkey) | 62 in 16 days (~4/day), most-used write feature |
| Spinoffs | 17 total. Real docks: ~5. Auto-name all: 25 runs |
| Usage logging of views | none. No way to tell if Galaxy, Links, Waterfall, Context are opened |
| Real-input verification | 11 CONTEXT entries say "not verified" / "stubbed"; nearly every check ran in automation Chrome with POSTs stubbed |
| Build churn | 63 commits; 34 on 11-26; full UI overhauls on 11-26 and 11-27; Galaxy made default on 11-27 while PRODUCT.md principle 1 says "Triage first" |

## The interview

**1. What job was it hired for?** "One glance shows which tab needs me; one click there and back" (BUILD-SHEET). Robert called that done on 09-29 ("worked"). Every build after it served a different job.

**2. What jobs did it pick up since?** Five, each from a one-off complaint or someone else's product: re-entry/work items (tab sprawl), lineage graph (Galaxy, Borderlands map), "why is this slow" diagnostics (affectUI Pro clone), capture routing, message-from-map (AIOffice). Opinion: this is the "copying a tool's screens" trap. The screens came over; the evidence that each job hurts did not.

**3. What does "progress" mean, as a number?** Never defined. The loop optimized S1 classifier accuracy, S2 clicks-to-open, S3 asks visible, and a design score (15 -> 28/40). Those measure *seeing* asks. None measure *clearing* them. Proposed north star: open asks older than 24h. Today: 18. Guardrail: false flags on the live list (today: 3+).

**4. Is the lever the tool, or something else?** The tool surfaces asks well. The queue doesn't drain because most asks aren't one-line replies: "grade the calibration tab", "review the three lead claims", "decide with Chace on admin ownership", "edit the tenet drafts". Those need a work block, not a reply box. This is the "notify under-solves" trap: the value is in the 10 minutes after the ping, and the map has no verb for "this needs 30 minutes, put it on Tuesday" or "you do it".

**5. What's the cost of the asks that shouldn't exist?** Several asks are agents handing back work they could finish (commit, compact, repackage). The CLAUDE.md rules already say "just do it", and the classifier now marks some FYI, but the agents still stop and ask. Fixing it at the source cuts the queue more than any view.

**6. What does the data say is unused?** The work-item lifecycle: 128 items, none ever parked or done, so the Galaxy is a map of everything ever started, growing by a few planets a day. The map's main structure encodes no decisions. Docks (~5) and resume (4) are near zero. Unknown: every view, because nothing logs view opens.

**7. Has anyone watched real use?** No. Verification is synthetic. The "galaxy map isn't working" bug (11-19) was a stale tab only real use found. Opinion: the 11-26/27 overhauls were judged by a design-review agent, not by whether Robert used them.

**8. What should stop?** New surfaces and visual overhauls until the north star moves. Galaxy as the default (principle 1 already says triage first).

## Verdict
- Working: the needs-you detection, the ask/action line, capture (4/day, steady), the ⌘1/⌘⇧1 loop.
- Not working: draining the queue (18, flat, 6 days old); work-item lifecycle (0 closed of 128); everything past triage is unmeasured.
- Cut or hide: Galaxy as default; Links view; turn diagnostics tabs stay but off the main path. Re-enable only if view logging shows use.
- Next build, one thing: **a drain pass.** Each needs-you ask gets one of four verbs in one key: Reply / Do it yourself (sends "finish this without me, then report") / Block time (date, hides until then) / Dismiss. Plus auto-park items dormant 5 days and close dead shells. Success = asks older than 24h under 5 within one week.
- Cheapest test first (today, 15 minutes, $0): add view-open + verb logging, then run one timed pass over today's 18 by hand and tag each ask reply / work-block / agent-should-do / false. That split says whether the drain verbs are right before building them.

## Where the two interviews agree and differ
- Agree: north star = asks older than 24h; capture is the real habit; work-item lifecycle and Dock are unused; stop overhauls; Galaxy off the default; log view and action use first.
- agy adds: the 5.9d ages are a cmux-relaunch artifact; true waits run 6.5 to 47 days (backlog #48). Clicks-to-open regressed 1 -> 2 with the 11-27 Galaxy default.
- agy cuts harder: also drop goal grouping and the 5-tab diagnostics drawer. Mine keeps diagnostics off the main path until logging shows whether they are used.
- Mine adds: the asks need verbs other than Reply (Do it yourself, Block time), and agents should stop creating asks the rules already say to just do.

## agy interview (independent, verbatim)

### Agent Overworld: Product Interview Evaluation

## 1. Eight Interview Questions

**1. User: Are you building for the operator or the tool-builder?**
`PRODUCT.md:11` names one operator running 25 to 35 sessions. You shipped 34 commits on 11-26, two UI overhauls on 11-26 and 11-27 (`CONTEXT.md:360-378`), parallax stars and gas giants (`CONTEXT.md:286-296`), and zero usage logs. Opinion: you build for craft while the operator stays blocked.

**2. Job: Did you solve the core job in September?**
In `BUILD-SHEET.md:4,23`, you defined the job: spot waiting tabs, read a recap, jump in one click. You called that thin slice working on 09-29 (`CONTEXT.md:75`). Background-done status (`BUILD-SHEET.md:23`) remains open (`plans/ux-backlog.md:19`). Opinion: you solved the job on day one, then built an unrequested project manager.

**3. Original bet: Where did you break it?**
In `BUILD-SHEET.md:5,41`, you bet on a read-only focus map for 30 tabs with no tab closing or replies. `PRODUCT.md:48` set Principle 1 as "Triage first, exploration second." On 11-27 you made Galaxy default again (`CONTEXT.md:372-374`), regressing clicks-to-open from 1 (`CONTEXT.md:366`) to 2 (`CONTEXT.md:378`).

**4. Actual usage: Which features do you use, and which sit idle?**
Logs show 62 hotkey captures in 16 days, 25 auto-name runs, and 17 spinoffs. Against that: all 128 work items stay active (0 parked, 0 done); Resume ran 4 times; Dock ran about 5 times; 12 of 42 open tabs are dead shells. Opinion: capture and auto-naming are real habits; work-item states and Galaxy docking are shelfware.

**5. Success metric: Why did 63 commits produce no felt progress?**
You optimized build proxies (`evals/walk.mjs`, golden sets, `impeccable` 15/40 to 28/40, `CONTEXT.md:366`) while the queue fell by 1 (19 on 11-26 to 18 on 11-27). Twelve of 18 asks are 5.9 days old (real waits 6.5 to 47 days, `plans/ux-backlog.md:55`), and rule-breaking asks ("Run /compact", "I can turn this into a shareable page") leak through.

**6. North star: What should the north star be?**
`PRODUCT.md:16` promises one glance for live decisions and one click to act. Opinion: the north star is zero stale decisions blocking live sessions, clearing asks and closing dead tabs.

**7. Cut: What should you cut right now?**
You built unused machinery (`CONTEXT.md:198-311`): 0 parked, 0 done, 0 file links (`CONTEXT.md:237`), about 5 docks, and 46 open UX bugs (`plans/ux-backlog.md:61`). Opinion: cut Galaxy as default, the active/parked/done work-item lifecycle, LLM goal grouping, Dock-beside-map, and the 5-tab diagnostics drawer.

**8. Next build and stop-building: What changes tomorrow?**
Stop UI overhauls and classifier-tuning loops (`CONTEXT.md:323-378`). Opinion: ship one release that logs view and action clicks, restores a flat Triage default sorted by true transcript age (`plans/ux-backlog.md:55`), and adds 1-click Dismiss and 1-click Close for dead shells (`plans/ux-backlog.md:16`).

## 2. Single Progress Metric

**Stale needs-you asks older than 24 hours** (target: 0).
- **Current value:** 12 of 18 open asks (each 5.9 days old; net queue fell from 19 on 11-26 to 18 on 11-27).

## 3. Verdict

- **Working:** Quick capture (62 uses in 16 days), Auto-name (25 runs), `/spinoff` (17 uses), and cmux status aggregation.
- **Not working:** Galaxy default, work-item states (128 active, 0 parked, 0 done), Dock (about 5 uses), Resume (4 uses), stale queue (18 waiting, 12 dead shells), and unmeasured iteration.
- **Cut:** Galaxy default, work-item park/done/goal grouping, Dock-beside-map, and the 5-tab diagnostics drawer.
- **One next build:** Add local view/action telemetry plus a flat Triage default sorted by real last-turn age, with 1-click Dismiss and 1-click Close for dead shells.
