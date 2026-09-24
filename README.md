# Agent Overworld

A live map of every cmux workspace (region) and tab (session), with each Claude/agy session's status and a one-line recap of its last reply. It runs as a local web app inside a pinned cmux browser tab.

- `server.py`: stdlib-only Python server on `127.0.0.1:7717`. Reads cmux's records in `~/.cmuxterm/` and drives cmux through its CLI.
- `index.html`: the map. Click a session to jump to it, drag a session onto another region to move it, `+` starts a new Claude session in a region, `×` twice closes one.
- `autostart.zsh`: source it from `~/.zshrc`. It starts the server from the first cmux shell, because cmux's socket only accepts processes launched inside cmux.
- `spinoff.sh`: backs the `/spinoff` skill. It opens a child session from a handoff brief and records the parent link.

Shortcuts: ⌘1 opens the Overworld (it stays pinned in slot 1). ⌘⇧1 goes back to your last tab, via this line in `~/.config/cmux/cmux.json`:

```jsonc
"shortcuts": { "bindings": { "focusHistoryBack": "cmd+shift+1" } }
```

History and design notes live in `CONTEXT.md` and `BUILD-SHEET.md`.
