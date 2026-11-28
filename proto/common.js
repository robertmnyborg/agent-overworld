// Shared by the three galaxy prototypes: loads tasks + asks, and owns the side panel with the four verbs.
// A task = an open work item (dormant ones are left off the map), or a waiting session that is on no item.
// An ask = a session that needs Robert. Age = time since its last reply (turn_at), not cmux's relaunch time.
"use strict";
const OW = (() => {
  const DAY = 86400e3, OW_DAY = DAY;
  const BLOCK_WORDS = /\b(review|grade|edit|read|look (it )?over|draft|write|record|walk through|go through|judge|rank|answer (the|their) open|fill|rewrite|audit|check the)\b/i;
  const DIY_TEXT = "Finish this yourself without waiting on me: make the call you would recommend, take the next step, then report what you did in 3 lines. If it truly needs me (approval to post or spend, or access only I have), say exactly what and why in one line.";
  let data = null, triage = {}, sent = JSON.parse(sessionStorage.getItem("ow.proto.sent") || "{}");
  let renderFn = null, openId = null, typing = false, cleared = Number(sessionStorage.getItem("ow.proto.cleared") || 0);

  const ts = x => x == null ? null : typeof x === "number" ? (x > 1e11 ? x : x * 1000) : Date.parse(x);
  const askKey = s => (s.full || s.ask || "").slice(-400);
  const effortOf = s => {
    const a = s.action || {};
    if (a.options && a.options.length) return "quick";
    return BLOCK_WORDS.test(a.action || s.ask || "") ? "block" : "quick";
  };
  const ago = ms => {
    const d = (Date.now() - ms) / DAY;
    if (d < 1 / 24) return Math.max(1, Math.round(d * 1440)) + "m";
    if (d < 1) return Math.round(d * 24) + "h";
    return (d < 10 ? d.toFixed(1).replace(/\.0$/, "") : Math.round(d)) + "d";
  };
  const hidden = s => {
    const t = triage[s.id];
    if (sent[s.id] && sent[s.id] === askKey(s)) return "sent";
    if (!t || t.ask !== askKey(s)) return null;
    if (t.verb === "dismiss") return "dismissed";
    if (t.verb === "block" && t.until && t.until > Date.now()) return "blocked";
    return null;
  };

  async function load() {
    const [st, gx, tr, hist] = await Promise.all(["/api/state", "/api/galaxy", "/api/triage", "/api/asks-history"].map(u => fetch(u).then(r => r.json())));
    triage = tr;
    const sessions = st.regions.flatMap(r => r.sessions);
    const workById = Object.fromEntries(((st.work && st.work.items) || []).map(i => [i.id, i]));
    const bySurface = Object.fromEntries(sessions.map(s => [s.id, s]));
    const goals = new Map(gx.systems.map(g => [g.id, { id: g.id, title: g.title, tasks: [] }]));
    const unfiled = { id: "_unfiled", title: "Not on a work item", tasks: [] };
    const placed = new Set();
    let dormant = 0, parked = 0;
    const mkAsk = (s, task) => ({
      id: s.id, session: s, task, title: s.title, at: ts(s.turn_at) || ts(s.since) || ts(s.updated),
      text: (s.action && s.action.action) || s.ask || s.recap || "", kind: (s.action && s.action.kind) || "action",
      options: (s.action && s.action.options) || [], effort: effortOf(s), exited: !!s.exited, hide: hidden(s),
    });
    for (const p of gx.planets) {
      if (p.state !== "active") { parked++; continue; }
      const live = (p.tabs || []).map(id => bySurface[id]).filter(Boolean);
      live.forEach(s => placed.add(s.id));
      const asks = live.filter(s => s.needs);
      if (p.dormant && !asks.length) { dormant++; continue; }
      const task = { id: p.id, title: p.title, goal: p.goal, next: p.next, waits_on: p.waits_on, people: p.people,
        status: asks.length ? "needs" : live.some(s => s.status === "working") ? "working" : "open",
        lastActive: ts(p.last_active), live, sessions: p.sessions, asks: [],
        askedBy: ((workById[p.id] || {}).asked_by || []).map(x => x.person), people: p.people || [] };
      task.asks = asks.map(s => mkAsk(s, task));
      (goals.get(p.group) || unfiled).tasks.push(task);
    }
    for (const s of sessions) {
      if (!s.needs || placed.has(s.id)) continue;
      const task = { id: "s:" + s.id, title: s.title, goal: "", status: "needs", lastActive: ts(s.turn_at), live: [s], sessions: 1, asks: [] };
      task.asks = [mkAsk(s, task)];
      unfiled.tasks.push(task);
    }
    if (unfiled.tasks.length) goals.set(unfiled.id, unfiled);
    const all = [...goals.values()].filter(g => g.tasks.length);
    for (const g of all) for (const t of g.tasks) {
      t.goalTitle = g.title;
      t.openAsks = t.asks.filter(a => !a.hide);
      t.oldest = t.openAsks.length ? Math.min(...t.openAsks.map(a => a.at || Date.now())) : null;
    }
    const asks = all.flatMap(g => g.tasks.flatMap(t => t.openAsks)).sort((a, b) => (a.at || 0) - (b.at || 0));
    const stale = asks.filter(a => a.at && Date.now() - a.at > DAY).length;
    const set = all.flatMap(g => g.tasks.flatMap(t => t.asks));
    data = { history: hist.rows, goals: all, asks, stale, dormant, parked, deadShells: sessions.filter(s => s.status === "shell").length,
      hiddenCount: { dismissed: set.filter(a => a.hide === "dismissed").length, blocked: set.filter(a => a.hide === "blocked").length, sent: set.filter(a => a.hide === "sent").length } };
    return data;
  }

  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.status);
    return j;
  }


  const css = document.createElement("style");
  css.textContent = `
  [hidden]{display:none!important}
  .ow-head{position:fixed;top:0;left:0;right:0;height:44px;display:flex;align-items:center;gap:14px;padding:0 16px;z-index:5;
    background:var(--head);border-bottom:1px solid var(--line);font:13px/1.2 var(--ui);color:var(--fg)}
  .ow-head>*{white-space:nowrap;flex-shrink:0} .ow-head .ow-sub{flex-shrink:1;min-width:0}
  .ow-title{font-weight:650;letter-spacing:.02em}
  .ow-metric{font-weight:650;color:var(--hot)} .ow-metric.ok{color:var(--good)}
  .ow-trend{display:flex;align-items:center;gap:6px;color:var(--mut);font-size:12px}
  .ow-spark-line{fill:none;stroke:var(--hot);stroke-width:1.5} .ow-spark-dot{fill:var(--hot)} .ow-spark-goal{stroke:var(--good);stroke-dasharray:2 2;stroke-width:1}
  .ow-delta.down{color:var(--good)} .ow-delta.up{color:var(--hot)}
  .ow-sub{color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ow-flex{flex:1} .ow-nav{display:flex;gap:4px}
  .ow-nav a{color:var(--mut);text-decoration:none;padding:5px 9px;border-radius:6px} .ow-nav a:hover{color:var(--fg)}
  .ow-nav a.on{color:var(--fg);background:var(--chip)}
  .ow-panel{position:fixed;top:44px;right:0;bottom:0;width:440px;overflow:auto;padding:18px 20px 40px;z-index:4;
    background:var(--panel);border-left:1px solid var(--line);color:var(--fg);font:14px/1.5 var(--ui);box-shadow:-12px 0 40px var(--shadow,rgba(0,0,0,.18))} /* design-gate: allow */
  .ow-p-top{position:relative;padding-right:28px} .ow-p-goal{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
  .ow-p-title{margin:2px 0 6px;font-size:19px;line-height:1.25} .ow-p-meta{color:var(--mut);margin:4px 0 12px}
  .ow-x{position:absolute;top:0;right:0;background:none;border:0;color:var(--mut);font-size:22px;cursor:pointer}
  .ow-ask{border-top:1px solid var(--line);padding:14px 0 6px}
  .ow-ask-head{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .ow-tag{font-size:11px;padding:2px 7px;border-radius:99px;background:var(--chip);color:var(--fg)}
  .ow-tag.decision{background:var(--hot);color:var(--onhot)} .ow-tag.block{outline:1px solid var(--hot)}
  .ow-age{color:var(--hot);font-size:12px;font-weight:600;margin-left:auto} .ow-sess{color:var(--mut);font-size:12px;width:100%}
  .ow-ask-text{font-size:15px;margin:8px 0 10px}
  .ow-warn{color:var(--hot);font-size:12px} .ow-status{font-size:12px;color:var(--good);min-height:1em;margin:6px 0} .ow-status.err{color:var(--hot)}
  .ow-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
  .ow-chip{border:1px solid var(--line);background:var(--chip);color:var(--fg);border-radius:8px;padding:5px 9px;cursor:pointer;font:13px var(--ui);text-align:left}
  .ow-chip[data-armed]{border-color:var(--hot)}
  .ow-reply{width:100%;box-sizing:border-box;background:var(--input);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px;font:14px var(--ui);resize:vertical}
  .ow-verbs,.ow-menu{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
  .ow-btn{border:1px solid var(--line);background:var(--chip);color:var(--fg);border-radius:7px;padding:6px 10px;cursor:pointer;font:13px var(--ui)}
  .ow-btn:disabled,.ow-chip:disabled,.ow-reply:disabled{opacity:.35;cursor:not-allowed}
  .ow-btn:hover{border-color:var(--fg)} .ow-btn.primary{background:var(--acc);color:var(--onacc);border-color:var(--acc)} .ow-btn.ghost{background:none}
  .ow-full summary{color:var(--mut);font-size:12px;cursor:pointer;margin-top:6px}
  .ow-full pre{white-space:pre-wrap;font:12px/1.5 var(--mono);color:var(--mut);max-height:320px;overflow:auto}
  .ow-toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:7;display:flex;gap:12px;align-items:center;padding:9px 12px 9px 16px;border-radius:10px;background:var(--panel);color:var(--fg);border:1px solid var(--line);font:13px var(--ui)}
  .ow-tip{position:fixed;pointer-events:none;z-index:6;max-width:320px;padding:8px 10px;border-radius:8px;background:var(--panel);color:var(--fg);
    border:1px solid var(--line);font:12px/1.4 var(--ui);box-shadow:0 6px 24px var(--shadow,rgba(0,0,0,.25))} /* design-gate: allow */
  .ow-tip b{display:block;font-size:13px}
  @media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
  `;
  document.head.append(css);
  // ---------- header ----------
  function header(title, viewName) {
    const h = document.createElement("header");
    h.className = "ow-head";
    h.innerHTML = `<b class="ow-title"></b><span class="ow-metric"></span><span class="ow-trend"><svg class="ow-spark" width="84" height="20"></svg><span class="ow-delta"></span></span><span class="ow-sub"></span><span class="ow-flex"></span><nav class="ow-nav"></nav>`;
    h.querySelector(".ow-title").textContent = title;
    const nav = h.querySelector(".ow-nav");
    [["A", "orbit"], ["B", "radar"], ["C", "atlas"], ["D", "rings"]].forEach(([k, v]) => {
      const a = document.createElement("a");
      a.href = `/proto/${v}.html`; a.textContent = `${k} ${v[0].toUpperCase()}${v.slice(1)}`;
      if (v === viewName) a.className = "on";
      nav.appendChild(a);
    });
    const live = document.createElement("a"); live.href = "/"; live.textContent = "Live map"; nav.appendChild(live);
    document.body.prepend(h);
  }
  function paintHeader() {
    const m = document.querySelector(".ow-metric"), sub = document.querySelector(".ow-sub");
    m.textContent = `${data.stale} asks waiting over 24h`;
    m.classList.toggle("ok", data.stale < 5);
    // trend: change against the reading closest to 24h ago, and a 7-day line of the same number
    const rows = data.history || [], delta = document.querySelector(".ow-delta"), sp = document.querySelector(".ow-spark");
    const dayAgo = rows.filter(r => r.at * 1000 <= Date.now() - 20 * 3600e3).pop();
    if (dayAgo) { const d = data.stale - dayAgo.stale; delta.textContent = d === 0 ? "same as yesterday" : `${d < 0 ? "▼" : "▲"}${Math.abs(d)} since yesterday`; delta.className = "ow-delta " + (d < 0 ? "down" : d > 0 ? "up" : ""); }
    else delta.textContent = rows.length ? `tracking since ${new Date(rows[0].at * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}` : "first reading now";
    const pts = [...rows.map(r => [r.at * 1000, r.stale]), [Date.now(), data.stale]];
    const t0 = Date.now() - 7 * OW_DAY, max = Math.max(5, ...pts.map(p => p[1]));
    sp.innerHTML = "";
    const NSs = "http://www.w3.org/2000/svg", line = document.createElementNS(NSs, "polyline");
    line.setAttribute("points", pts.map(([t, v]) => `${(Math.max(0, t - t0) / (7 * OW_DAY) * 82 + 1).toFixed(1)},${(19 - v / max * 17).toFixed(1)}`).join(" "));
    line.setAttribute("class", "ow-spark-line"); sp.append(line);
    const [lt, lv] = pts[pts.length - 1], dot = document.createElementNS(NSs, "circle");
    Object.entries({ cx: (Math.max(0, lt - t0) / (7 * OW_DAY) * 82 + 1).toFixed(1), cy: (19 - lv / max * 17).toFixed(1), r: 2.5, class: "ow-spark-dot" }).forEach(([k, v]) => dot.setAttribute(k, v)); sp.append(dot);
    const goal = document.createElementNS(NSs, "line"); const gy = (19 - 5 / max * 17).toFixed(1);
    Object.entries({ x1: 0, x2: 84, y1: gy, y2: gy, class: "ow-spark-goal" }).forEach(([k, v]) => goal.setAttribute(k, v)); sp.append(goal);
    sp.setAttribute("aria-label", `Asks waiting over 24h, last 7 days; goal under 5`);
    const hc = data.hiddenCount;
    sub.textContent = `${data.asks.length} open asks · cleared this visit ${cleared} · blocked ${hc.blocked} · dismissed ${hc.dismissed} · ${data.dormant} dormant items off the map · ${data.deadShells} dead shells`;
  }

  // ---------- panel ----------
  const panel = document.createElement("aside");
  panel.className = "ow-panel";
  panel.hidden = true;
  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  function findTask(id) { for (const g of data.goals) for (const t of g.tasks) if (t.id === id) return t; return null; }

  function open(taskId) {
    openId = taskId;
    paintPanel();
    if (renderFn) renderFn(data, { selected: openId });
  }
  function close() { openId = null; panel.hidden = true; if (renderFn) renderFn(data, { selected: null }); }

  function paintPanel() {
    const t = openId && findTask(openId);
    if (!t) { panel.hidden = true; return; }
    if (typing) return; // never rebuild under the cursor
    panel.hidden = false;
    panel.replaceChildren();
    const top = el("div", "ow-p-top");
    top.append(el("div", "ow-p-goal", t.goalTitle), el("h2", "ow-p-title", t.title));
    const x = el("button", "ow-x", "×"); x.title = "Close (Esc)"; x.onclick = close; top.append(x);
    panel.append(top);
    if (t.goal) panel.append(el("p", "ow-p-meta", t.goal));
    if (!t.openAsks.length) {
      panel.append(el("p", "ow-p-meta", t.status === "working" ? "Working. Nothing needs you." : `Nothing needs you. Last active ${t.lastActive ? ago(t.lastActive) + " ago" : "unknown"}.`));
      if (t.next) panel.append(el("p", "ow-p-meta", "Next: " + t.next));
    }
    for (const a of t.openAsks) panel.append(askBlock(a));
    const tabs = t.live.filter(s => s.agent);
    if (tabs.length && !t.openAsks.length) {
      const b = el("button", "ow-btn", "Open tab");
      b.onclick = () => post("/api/focus", { workspace: tabs[0].workspace, surface: tabs[0].id });
      panel.append(b);
    }
  }

  function askBlock(a) {
    const box = el("section", "ow-ask");
    const head = el("div", "ow-ask-head");
    head.append(el("span", "ow-tag " + a.kind, a.kind === "decision" ? "Decision" : "Action"),
      el("span", "ow-tag " + a.effort, a.effort === "block" ? "Needs a work block" : "Quick"),
      el("span", "ow-age", a.at ? `waiting ${ago(a.at)}` : ""));
    head.append(el("span", "ow-sess", "Session: " + a.title));
    box.append(head, el("p", "ow-ask-text", a.text));
    if (a.exited) box.append(el("p", "ow-warn", "This session's agent has exited. Open the tab and resume it before replying."));
    const status = el("p", "ow-status");
    const done = (label, undoable) => {
      sent[a.id] = askKey(a.session); sessionStorage.setItem("ow.proto.sent", JSON.stringify(sent));
      cleared++; sessionStorage.setItem("ow.proto.cleared", cleared);
      typing = false;
      toast(label, undoable ? () => post("/api/triage", { id: a.id, verb: "undo" }).then(() => {
        delete sent[a.id]; sessionStorage.setItem("ow.proto.sent", JSON.stringify(sent));
        cleared = Math.max(0, cleared - 1); sessionStorage.setItem("ow.proto.cleared", cleared); refresh();
      }) : null);
      // clearing loop: once this task has nothing left for you, move to the next oldest ask
      setTimeout(() => refresh().then(() => { const t = findTask(a.task.id); if (!t || !t.openAsks.length) nextAsk(); }), 600);
    };
    const fail = e => { status.textContent = "Not sent: " + e.message; status.className = "ow-status err"; };
    const send = text => post("/api/send", { workspace: a.session.workspace, surface: a.id, text });

    if (a.options.length) {
      const chips = el("div", "ow-chips");
      a.options.forEach(o => {
        const c = el("button", "ow-chip", o);
        c.onclick = () => { if (c.dataset.armed) send(o).then(() => done("Sent: " + o)).catch(fail); else { c.dataset.armed = 1; c.textContent = "Send: " + o; } };
        chips.append(c);
      });
      box.append(chips);
    }
    const ta = el("textarea", "ow-reply"); ta.rows = 2; ta.placeholder = "Reply (Enter sends, Shift+Enter new line)";
    ta.onfocus = () => typing = true; ta.onblur = () => typing = !!ta.value;
    ta.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (ta.value.trim()) send(ta.value).then(() => done("Reply sent")).catch(fail); } };
    box.append(ta);

    const verbs = el("div", "ow-verbs");
    const v = (label, key, fn, cls = "") => { const b = el("button", "ow-btn " + cls, label); b.title = key; b.onclick = fn; verbs.append(b); return b; };
    v("Reply", "r", () => { if (ta.value.trim()) send(ta.value).then(() => done("Reply sent")).catch(fail); else ta.focus(); }, "primary");
    v("Do it yourself", "d", () => send(DIY_TEXT).then(() => done("Handed back: the agent will finish and report")).catch(fail));
    const blk = v("Block time ▾", "b", () => menu.hidden = !menu.hidden);
    v("Dismiss", "x", () => post("/api/triage", { id: a.id, ask: askKey(a.session), verb: "dismiss" }).then(() => done("Dismissed until a new reply", true)).catch(fail));
    const fo = v(a.exited ? "Open tab to resume" : "Open tab", "o", () => post("/api/focus", { workspace: a.session.workspace, surface: a.id }), a.exited ? "primary" : "ghost");
    if (a.exited) { verbs.querySelectorAll("button").forEach(b => { if (b !== fo && b !== blk && b.textContent !== "Dismiss") b.disabled = true; }); ta.disabled = true; box.querySelectorAll(".ow-chip").forEach(c => c.disabled = true); verbs.firstChild.classList.remove("primary"); }
    const menu = el("div", "ow-menu"); menu.hidden = true;
    const at9 = (addDays, weekday) => { const d = new Date(); d.setHours(9, 0, 0, 0); if (weekday != null) { do d.setDate(d.getDate() + 1); while (d.getDay() !== weekday); } else d.setDate(d.getDate() + addDays); return d.getTime(); };
    [["In 3 hours", Date.now() + 3 * 3600e3], ["Tomorrow 9am", at9(1)], ["Monday 9am", at9(0, 1)], ["Next week", at9(7)]].forEach(([l, until]) => {
      const b = el("button", "ow-btn", l);
      b.onclick = () => post("/api/triage", { id: a.id, ask: askKey(a.session), verb: "block", until }).then(() => done(`Blocked until ${new Date(until).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}`, true)).catch(fail);
      menu.append(b);
    });
    box.append(verbs, menu, status);
    const more = el("details", "ow-full"); more.append(el("summary", null, "Full last reply"), el("pre", null, (a.session.full || "").slice(-4000)));
    box.append(more);
    return box;
  }

  async function refresh() {
    try { await load(); } catch (e) { document.querySelector(".ow-sub").textContent = "Server unreachable: " + e.message; return; }
    paintHeader();
    if (renderFn) renderFn(data, { selected: openId });
    paintPanel();
  }

  function nextAsk() {
    if (!data.asks.length) { close(); return; }
    const ids = [...new Set(data.asks.map(a => a.task.id))];
    const i = ids.indexOf(openId);
    open(ids[i < 0 ? 0 : (i + 1) % ids.length]);
  }

  function start(title, viewName, render) {
    renderFn = render;
    header(title, viewName);
    document.body.append(panel);
    document.addEventListener("keydown", e => {
      if (e.target.closest && e.target.closest("textarea,input")) { if (e.key === "Escape") e.target.blur(); return; }
      if (e.key === "Escape") close();
      else if (e.key === "n") nextAsk();
    });
    refresh();
    setInterval(refresh, 5000);
  }

  const toastEl = el("div", "ow-toast"); toastEl.hidden = true; let toastTimer = null;
  function toast(label, undo) {
    if (!toastEl.isConnected) document.body.append(toastEl);
    toastEl.replaceChildren(el("span", null, label));
    if (undo) { const u = el("button", "ow-btn", "Undo"); u.onclick = () => { toastEl.hidden = true; undo(); }; toastEl.append(u); }
    toastEl.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.hidden = true, 8000);
  }
  const tip = el("div", "ow-tip"); tip.hidden = true;
  function showTip(e, title, line) { if (!tip.isConnected) document.body.append(tip); tip.hidden = false; tip.replaceChildren(el("b", null, title), el("span", null, line || "")); tip.style.left = Math.min(innerWidth - 340, e.clientX + 14) + "px"; tip.style.top = (e.clientY + 14) + "px"; }
  function hideTip() { tip.hidden = true; }

  return { showTip, hideTip, start, open, close, ago, DAY, get data() { return data; }, get selected() { return openId; } };
})();
