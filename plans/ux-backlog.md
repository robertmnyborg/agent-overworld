# Overworld UX backlog

Seeded 2026-11-26 from `plans/ux-audit-2026-11-25.md` (34 findings; local only, gitignored because it quotes session text). Each round's Fable re-audit appends new rows with source `r<N> audit` (round 2: `plans/ux-audit-r2.md`, local only).
Order: blockers first, then audit rank. S4 counts open blockers / majors. Full where/problem/fix text stays in the audit; this file tracks state.

| # | Sev | State | Problem (short) | Source |
|---|---|---|---|---|
| 1 | blocker | fixed r1 (PR pending) | "3 needs you" misses 9 open sessions whose last reply asks for an action (6) or a decision (3), for example "Approve creating two HubSpot... | audit 2026-11-25 |
| 2 | blocker | open (r2: asks of needs-you sessions now on the first screen; recap of the rest, hover card and reply box still missing) | The default view shows no recap, no last reply and no reply box | audit 2026-11-25 |
| 3 | blocker | open | Inbox, row, Reply: the Inbox closes and nothing opens when the galaxy or Work view is behind it | audit 2026-11-25 |
| 4 | major | open | The `a` key renames every workspace and tab (one model call per workspace) from any view, with no confirm and no undo | audit 2026-11-25 |
| 5 | major | open | One session, three names | audit 2026-11-25 |
| 6 | major | open | One state, several words: "your turn", "needs you", "waiting" | audit 2026-11-25 |
| 7 | major | fixed r2: Open on each needs-you row | Jumping takes 2 clicks, and the filled button "Show beside map" moves the real tab into the Overworld workspace | audit 2026-11-25 |
| 8 | major | open | Opening another item, Esc, Fit, `n` or closing the panel sends the docked tab back to its workspace with no message | audit 2026-11-25 |
| 9 | major | open | No control clears a needs-you item without typing in its tab | audit 2026-11-25 |
| 10 | major | open | The Work view sorts by goal first | audit 2026-11-25 |
| 11 | major | open | 7 of 8 "working" sessions had no hook event for 6 to 22 hours | audit 2026-11-25 |
| 12 | major | open | No view tells you background work finished | audit 2026-11-25 |
| 13 | major | open | Park in the galaxy panel closes the item's tabs on one click | audit 2026-11-25 |
| 14 | major | open | "Sort into goals (17 have none)" sits first in the breadcrumb in the same amber as "Needs you" | audit 2026-11-25 |
| 15 | major | open | The header shows "Auto-name all", "+ New group" and "show plain shells" in the galaxy, where they change nothing you can see | audit 2026-11-25 |
| 16 | major | open | Rename, timeline, reply and close on a session card, and Park / Resume / Done on a work item, appear only on hover | audit 2026-11-25 |
| 17 | major | open | At 900px the header takes 4 rows and 119px | audit 2026-11-25 |
| 18 | major | open | 12 of 124 items (6 of 34 active) are named "Capture NNNNNN Follow-Up" | audit 2026-11-25 |
| 19 | major | open | Arrow, Enter, Space and `r` stay live in the galaxy with nothing visibly selected | audit 2026-11-25 |
| 20 | minor | open | An Inbox row click unfolds tool steps | audit 2026-11-25 |
| 21 | minor | open | At 1440px wide the search box drops about 210px while you type, because the results list sits beside it and the row centres | audit 2026-11-25 |
| 22 | minor | open | The default lines are 30 "same files" links in white across the screen | audit 2026-11-25 |
| 23 | minor | open | The legend starts closed and leaves out planet size, the number on a planet, sun size and colour, the pulsing sun, and the hollow sun | audit 2026-11-25 |
| 24 | minor | open | Ages contradict | audit 2026-11-25 |
| 25 | minor | open | Inside a goal, the sun fills the middle of the screen with no name and no information | audit 2026-11-25 |
| 26 | minor | open | Sub-agent rows print "running · NaNh NaNm" | audit 2026-11-25 |
| 27 | minor | open | The galaxy opens on every load and ignores the view you used last | audit 2026-11-25 |
| 28 | minor | open | "Linked items" fills the panel with "same project" rows | audit 2026-11-25 |
| 29 | minor | open | "Recent captures" takes the top of the Work view, and each row's "Wrong? Move to..." menu lists all 124 items | audit 2026-11-25 |
| 30 | minor | open | "Done" on a work item takes one click | audit 2026-11-25 |
| 31 | minor | open | The only key documentation is one 11px grey line | audit 2026-11-25 |
| 32 | minor | open | The reply view has no "Open tab" button | audit 2026-11-25 |
| 33 | minor | open | Card titles cut off at about 17 characters ("Cheap Model R...", "Stone Ridge D...") while the status text takes the rest of the row | audit 2026-11-25 |
| 34 | minor | open | Five Esc handlers run on one keypress | audit 2026-11-25 |
| 35 | blocker | open (r2: header and list both say 20; Tabs view and Inbox say 19, planets and the "Needs you" button count 18 items) | Views give three numbers for "needs you" | r2 audit |
| 36 | blocker | open (r2: the session shows in the needs-you list; still no planet, not in search) | A flagged session on no work item has no planet ("HubSpot Cleanup Proposal") | r2 audit |
| 37 | major | open | A session whose agent ended (shell) is flagged in the galaxy only; a reply would reach a plain shell | r2 audit |
| 38 | major | open (r2: the list shows both tabs as rows; the item panel still shows one) | An item with two asking sessions shows one ask and counts once | r2 audit |
| 39 | major | open, needs Robert: "Parrots Nest" is labeled yes in the golden set | 1 clear false flag (a /spinoff session-size note) and 3 weak ones (optional offers) | r2 audit |
| 40 | major | open (r2: list sorts by longest wait and falls back to cmux's update time for the age) | Asks come with no order; 10 of 20 show no waiting age; decision and chore look alike | r2 audit |
| 41 | major | fixed r2: needs-you list with every ask on the first screen | First screen shows 18 amber names, 0 of 20 asks, overlapping labels | r2 audit |
| 42 | minor | open | Decisions' ready answers show only in the Inbox after a row click | r2 audit |
| 43 | minor | open | 4 of 19 asks cut off at two lines on Tabs view cards | r2 audit |

Open: 4 blockers, 19 major, 17 minor.
