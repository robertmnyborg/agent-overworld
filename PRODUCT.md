# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary user:** Robert Nyborg, sole operator running 25 to 35 parallel AI coding and research sessions (Claude Code and Antigravity) across cmux workspaces on one Mac.
- **Opening situation:** Switches to the pinned Overworld workspace (`Cmd+1`) mid-flow to see which sessions need a decision or action right now, answer or jump in one click, and return (`Cmd+Shift+1`).

## Product Purpose

Agent Overworld is a local air-traffic-control cockpit for parallel terminal agent sessions. Success means one glance tells Robert which sessions need him and what each is asking, one click answers inline or opens the live cmux tab, and deeper views expose work-item grouping, cross-session lineage, and turn-level time/cost/context bottlenecks without manual tab scanning.

## Positioning

Reads live cmux state, local session transcripts, subagent logs, and worked-out action classifications directly from disk and the cmux socket with zero external cloud sync, zero database, and zero framework build step, while operating directly on real cmux workspaces and tabs (focus, split-dock, send reply, park/resume, rename, group).

## Operating Context

- Runs inside a pinned cmux browser pane (`http://127.0.0.1:7717`, WebKit engine) at both full-width (`1440x900`+) and narrow split-pane widths (`~900px` when a terminal tab is docked beside it), as well as desktop Chrome for verification.
- Paired with a global Hammerspoon quick-capture hotkey (`Ctrl+Alt+Cmd+N`) and `/spinoff` lineage briefs.
- Evaluated with automated local checks (`evals/check_needs_you.py` for classifier accuracy, `evals/walk.mjs` for clicks-to-open and asks-visible-on-load against `evals/test_server.py`).

## Capabilities and Constraints

- **Architecture constraint:** Single self-contained `index.html` (vanilla HTML, CSS, JS, zero runtime frameworks or build tools) served by stdlib Python `server.py` on `localhost`.
- **Core capabilities:**
  - Prioritized triage of sessions needing a decision or action, with inline markdown reply (`Enter` send+next), quick-option chips, and 1-click cmux focus or side-by-side docking.
  - Workspace and goal organization (Scratch strip, Personal/Work workspace groups, work items, drag-to-move/split/merge/regroup, park/resume/done, recent capture redirect, LLM auto-name).
  - Spatial Galaxy map of goals, work items, sessions, shared project hubs, and cross-item links (spinoff, Slack thread, files, project, person) with pan/zoom/search/minimap.
  - Turn diagnostics (Timeline, idle-squeezed Waterfall, Agent cost tree, Context window treemap, Handoffs brief-loss diff) and Claude weekly usage meter.
- **Safety constraints:** Destructive or LLM-cost actions (closing live tabs via Park/Close, running Auto-name all, overwriting goal groupings) must require explicit arming or confirmation; read-only test server stubs all POSTs.
- **Scale ceiling:** 1 user, ~30-50 open tabs, ~8-15 workspaces, ~100-150 work items on one Mac.

## Evidence on Hand

- Product build sheet and original job priority: `BUILD-SHEET.md`.
- Full decision log and iteration history: `CONTEXT.md`.
- UX audits and backlog: `plans/ux-audit-ui-2026-11-26.md`, `plans/ux-backlog.md`, `plans/ux-loop/runs.md`.
- Live local state and transcripts via `evals/test_server.py` (no invented demo data needed).

## Product Principles

1. **Triage first, exploration second:** Opening Overworld immediately answers what needs a decision or action right now; spatial maps and deep diagnostics stay one click or key away without cluttering the default glance.
2. **One truth across every view:** Counts, status labels, ages, and session actions stay identical across Triage, Work/Goal views, Galaxy, and Inbox.
3. **Act from where you stand:** Reading a full reply, sending a response, inspecting turn diagnostics, or opening a tab works identically from any view.
4. **Honest signal over noise:** Stale asks, stalled working sessions, dormant items, and non-urgent chrome recede visually so live decisions stand out.
5. **Fast keyboard flow with safe guardrails:** Power-user keys speed up triage, while destructive or paid actions stay guarded and reversible where possible.

## Accessibility & Inclusion

- Full keyboard operability (`Tab`, `Enter`, `Space`, `Escape` layered dismissal, visible `:focus-visible` rings, proper dialog/tablist ARIA semantics).
- WCAG 2.1 AA contrast (>=4.5:1 normal text, >=3:1 UI components) and complete `prefers-reduced-motion` support across all animated beacons and transitions.
