# Work items (option C) — 2026-11-11

## Problem
A tab is one conversation. The thing people ping Robert about is a piece of work (goal, people, next step) that outlives
any one conversation. Today the tab is the only home for that work's state, so: re-entry = hunting tabs by drifted names;
any ping not on the exact same Slack thread opens a new tab (duplicates); nothing can be parked, so dead tabs stay open
as bookmarks (29 of 56 on 2026-11-11); person-split and topic-split workspaces both claim the same work.

## Design
- **Work item** = durable record in `~/.overworld/work.json`: title, goal, people, sources (Slack thread keys, links),
  state (active / parked / done), park note + next step + who it waits on, and its sessions.
- Sessions are keyed by transcript path, not cmux surface id (surface ids change on every cmux relaunch).
- cmux workspaces are untouched. Work items are a layer in Overworld only. People are a field on an item, not an item.
- **Seed**: one model call clusters every agent tab into proposed items; Robert reviews and accepts on a screen.
- **Sort**: every 30s, agent tabs not on any item get attached to an existing item, or start a new one flagged "new".
- **Park**: one Haiku call writes where it stands + next step + who it waits on; tabs close (transcript stays).
- **Resume**: new tab in the item's last workspace, `claude --resume <session>` in its cwd.
- **Capture**: Slack thread already on an item → that item. Else one Haiku call matches the note to an item.
  Match → paste into its live tab, or resume it if parked. No match → today's new-tab flow, and the tab is sorted later.
- **Merge**: drag one item onto another. Drag a tab onto an item to move it.
- **View**: Work view is the default; the existing map is the Tabs view (key `w` toggles).

## Not doing
- Changing cmux workspaces or groups to mirror items.
- Antigravity resume (no resume command known); agy tabs can be attached and parked, not resumed.
