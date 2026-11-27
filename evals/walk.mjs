#!/usr/bin/env node
// S2 and S3 for the UX loop: a scripted walk in the automation Chrome (CDP on :9223) against the stubbed test server.
//   S2: clicks from page load until the page asks to open a session that needs you (a POST to /api/focus or /api/dock
//       naming a needs-you surface). Every POST is stubbed by evals/test_server.py, so nothing real moves.
//   S3: of the sessions that need you, how many show their ask on the first screen, without opening anything.
// The walk takes the shortest path the page offers: a visible [data-walk="open-need"] control (1 click), else the galaxy's
// "Needs you" button and then the item panel's primary button (2 clicks).
// Usage: node evals/walk.mjs [--base http://127.0.0.1:7718] [--shot .shots/name.png] [--json]
import { writeFileSync } from "node:fs";

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg("--base", "http://127.0.0.1:7718"), SHOT = arg("--shot", null), CDP = "http://127.0.0.1:9223";
if (BASE.includes(":7717")) { console.error("walk runs against the test server, never the live one"); process.exit(2); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

const st = await (await fetch(BASE + "/api/state")).json();
const needs = st.regions.flatMap(r => r.sessions).filter(t => t.needs);
const askOf = t => ((t.action && t.action.action) || t.ask || "").trim();

const target = await (await fetch(`${CDP}/json/new?about:blank`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
let seq = 0; const waiting = new Map();
ws.onmessage = m => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); } };
const send = (method, params = {}) => new Promise(r => { const id = ++seq; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const run = async expr => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || "page error");
  return r.result.result.value;
};

const out = { base: BASE, needs: needs.length };
try {
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  // Record every POST the page makes; the test server stubs them anyway.
  await send("Page.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { window.__posts = []; const f = window.fetch;
    window.fetch = (u, o) => { if (o && o.method === "POST") window.__posts.push({ url: String(u), body: String(o.body || "") }); return f(u, o); }; })();` });
  await send("Page.navigate", { url: BASE + "/" });
  await sleep(5000);

  // S3: asks visible in the first viewport (elements inside 1440x900, not hidden), before any click.
  const visible = await run(`(() => {
    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const n = walker.currentNode, e = n.parentElement;
      if (!n.textContent.trim() || !e) continue;
      const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
      if (r.width && r.height && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth && cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0)
        out.push(n.textContent);
    }
    return out.join(" ").replace(/\\s+/g, " ");
  })()`);
  const norm = s => s.replace(/\s+/g, " ").trim();
  const shown = needs.filter(t => askOf(t) && visible.includes(norm(askOf(t)).slice(0, 40)));
  out.s3 = `${shown.length}/${needs.length}`;
  out.s3_missing = needs.filter(t => !shown.includes(t)).map(t => t.title);
  if (SHOT) {
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(SHOT, Buffer.from(shot.result.data, "base64"));
    out.shot = SHOT;
  }

  // S2: shortest path the page offers to open a needs-you session.
  const ids = new Set(needs.map(t => t.id));
  const opened = async () => {
    const posts = await run("window.__posts");
    return posts.some(p => /\/api\/(focus|dock)$/.test(new URL(p.url, BASE).pathname) && [...ids].some(id => p.body.includes(id)));
  };
  const click = sel => run(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})]
    .find(e => { const r = e.getBoundingClientRect(); return r.width && r.height && r.top < innerHeight; }); if (!e) return false; e.click(); return true; })()`);
  let clicks = 0;
  if (await click('[data-walk="open-need"]')) { clicks = 1; await sleep(800); }
  else if (await click("button.gnext")) {
    clicks = 1; await sleep(2500);
    if (await click(".gp-acts button.primary, .gp-acts button")) { clicks = 2; await sleep(800); }
  }
  out.s2 = (await opened()) ? clicks : `failed after ${clicks} clicks`;
  out.posts = (await run("window.__posts")).map(p => new URL(p.url, BASE).pathname);
} finally {
  ws.close();
  await fetch(`${CDP}/json/close/${target.id}`);
}

if (process.argv.includes("--json")) console.log(JSON.stringify(out));
else {
  console.log(`S2 clicks to first needs-you session: ${out.s2}`);
  console.log(`S3 asks visible on first screen: ${out.s3}`);
  if (out.shot) console.log(`screenshot: ${out.shot}`);
}
