#!/usr/bin/env python3
"""A read-only copy of the Overworld server for the UX loop's checks, on port 7718 by default.

Serves this checkout's index.html and server.py against live cmux state, with every write cut off:
- every POST is answered {"ok": true, "stubbed": true} and logged, never run (no focus, dock, rename, close, send);
- no background threads (no workspace upkeep, no action or naming model calls, no work sorting);
- no model call on /api/action (cached actions only), no pid file, and the dock record is never cleared.
Usage: python3 evals/test_server.py [port]
"""
import json, sys, time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7718
if PORT == 7717:
    sys.exit("7717 is the live server's port")

server.docked = lambda: None  # state() would delete a stale dock record; the test copy never touches it
server.work_out_action = lambda full, prompt: None  # cached actions only, no model calls
STUBBED = []


class Handler(server.Handler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode(errors="replace") if n else ""
        STUBBED.append({"path": self.path, "body": body[:300], "at": time.time()})
        print(f"{time.strftime('%H:%M:%S')} stubbed POST {self.path} {body[:120]}", flush=True)
        self._send(200, {"ok": True, "stubbed": True})


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Overworld test copy on http://127.0.0.1:{PORT}, POSTs stubbed", flush=True)
    httpd.serve_forever()
