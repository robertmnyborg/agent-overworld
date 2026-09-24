# Sourced from ~/.zshrc. Starts the Overworld server once per cmux session, from inside cmux
# (cmux's socket rejects processes launched outside it). Costs one `ps` per new shell.
if [[ -n $CMUX_SOCKET_PATH ]]; then
  _ow_pid=$(<~/.overworld/server.pid 2>/dev/null)
  if [[ -z $_ow_pid ]] || ! ps -p $_ow_pid -o command= 2>/dev/null | grep -q agent-overworld/server.py; then
    mkdir -p ~/.overworld
    ( nohup /usr/bin/python3 ~/Projects/agent-overworld/server.py >> ~/.overworld/server.log 2>&1 & )
  fi
  unset _ow_pid
fi
