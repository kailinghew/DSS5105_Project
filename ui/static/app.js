/* Subcontracting desk — front end. Plain JS, no build step.
   Every number shown here comes from the server's tools; this file only lays them out. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => "$" + Math.round(n).toLocaleString("en-US");
const days = (n) => `${n} day${Math.abs(n) === 1 ? "" : "s"}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: fine */ } },
};

const state = {
  today: new Date(Date.UTC(2026, 3, 1)),
  parser: "llm",
  llm: false,
  inbox: [],
  outcome: {},        // request id -> behaviour | "confirmed"
  current: null,      // inbox item being worked on
};

const LABEL = {
  allocate: "Ready to send", clarify: "Ask first", refuse: "Refuse",
  impossible: "Can't make date", decline: "Can't answer", confirmed: "Sent",
};

/* ------------------------------------------------------------------ api */
async function api(path, body) {
  const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const res = await fetch(path, opts);
  let data;
  try { data = await res.json(); } catch { throw new Error(`The server sent an unreadable reply (HTTP ${res.status}).`); }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 2600);
}

function dateAfter(n) {
  const d = new Date(state.today.getTime() + Math.round(n) * 86400000);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

/* ------------------------------------------------------------------ init */
async function init() {
  setupTabs();
  setupParser();
  $("#sender").value = store.get("qr.sender", "Dispatcher");
  $("#sender").addEventListener("change", (e) => store.set("qr.sender", e.target.value));

  try {
    const s = await api("/api/status");
    state.llm = s.llm;
    const sel = $("#objective");
    sel.innerHTML = s.objectives.map((o) =>
      `<option value="${esc(o)}">${esc(objectiveLabel(o))}</option>`).join("");
    sel.value = store.get("qr.objective", s.primary);
    if (!s.objectives.includes(sel.value)) sel.value = s.primary;
    sel.addEventListener("change", () => store.set("qr.objective", sel.value));
    if (!s.llm) {
      $("#p-llm").disabled = true;
      $("#p-llm").title = "Claude is not configured on this server (no API key).";
      setParser("baseline");
    } else {
      setParser(store.get("qr.parser", "llm"));
    }
    state.inbox = await api("/api/inbox");
    renderInbox();
  } catch (e) {
    $("#result").innerHTML = `<div class="error-box">Couldn't reach the desk server: ${esc(e.message)}. Is <code>python -m ui.server</code> running?</div>`;
  }

  $("#compose").addEventListener("submit", (e) => { e.preventDefault(); readCurrent(); });
  $("#message").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); readCurrent(); }
  });
  $("#message").addEventListener("input", () => {
    if (state.current && $("#message").value.trim() !== state.current.text) state.current = null;
  });
  $("#read-all").addEventListener("click", readAll);
  $("#query").addEventListener("submit", (e) => { e.preventDefault(); loadRegister(); });
}

function objectiveLabel(o) {
  return { lateness: "On-time delivery", fair: "Fair share across shops", defects: "Fewest defects",
           robust: "Robust to a shop closing", hybrid: "Balanced (time, defects, cost)" }[o] || o;
}

function setupParser() {
  document.querySelectorAll(".seg button").forEach((b) =>
    b.addEventListener("click", () => { if (!b.disabled) setParser(b.dataset.parser); }));
}
function setParser(p) {
  state.parser = p;
  store.set("qr.parser", p);
  document.querySelectorAll(".seg button").forEach((b) =>
    b.setAttribute("aria-checked", String(b.dataset.parser === p)));
}

/* ------------------------------------------------------------------ tabs */
function setupTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const show = (tab) => {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (tab.id === "tab-log") loadLog();
    if (tab.id === "tab-register" && !$("#register-out").innerHTML) loadRegister();
  };
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t));
    t.addEventListener("keydown", (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (d) { const n = tabs[(i + d + tabs.length) % tabs.length]; n.focus(); show(n); }
    });
  });
}

/* ------------------------------------------------------------------ inbox */
function renderInbox() {
  $("#inbox").innerHTML = state.inbox.map((m) => {
    const o = state.outcome[m.id];
    const chip = o ? `<span class="chip ${o}">${LABEL[o]}</span>` : "";
    const cur = state.current && state.current.id === m.id ? ' aria-current="true"' : "";
    return `<li><button class="msg" data-id="${esc(m.id)}"${cur}>
      <span class="msg-who"><b>${esc(m.sender)}</b> ${esc(m.time)} · ${esc(m.id)}</span>${chip}
      <span class="msg-text">${esc(m.text)}</span></button></li>`;
  }).join("");
  const list = [...document.querySelectorAll(".msg")];
  list.forEach((b, i) => {
    b.addEventListener("click", () => pick(b.dataset.id));
    b.addEventListener("keydown", (e) => {
      const d = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
      if (d && list[i + d]) { e.preventDefault(); list[i + d].focus(); }
    });
  });
  summarise();
}

function summarise() {
  const vals = Object.values(state.outcome);
  const open = state.inbox.length - vals.length;
  const count = (k) => vals.filter((v) => v === k).length;
  const parts = [];
  if (count("confirmed")) parts.push(`${count("confirmed")} sent`);
  if (count("allocate")) parts.push(`${count("allocate")} ready to confirm`);
  const needs = count("clarify") + count("refuse") + count("impossible");
  if (needs) parts.push(`${needs} need a reply`);
  if (count("decline")) parts.push(`${count("decline")} can't be answered`);
  if (open) parts.push(`${open} unread`);
  $("#inbox-summary").textContent = parts.length ? parts.join(", ") + "." : "Inbox is empty.";
}

function pick(id) {
  const m = state.inbox.find((x) => x.id === id);
  state.current = m;
  $("#message").value = m.text;
  $("#sender").value = m.sender;
  document.querySelectorAll(".msg").forEach((b) =>
    b.toggleAttribute("aria-current", b.dataset.id === id));
  document.querySelectorAll(".msg[aria-current]").forEach((b) => b.setAttribute("aria-current", "true"));
  readCurrent();
}

async function readCurrent() {
  const text = $("#message").value.trim();
  if (!text) { $("#message").focus(); return; }
  const line = state.current ? state.current.line : text;
  const btn = $("#read-btn");
  btn.disabled = true;
  btn.textContent = state.parser === "llm" ? "Reading with Claude…" : "Reading…";
  $("#result").innerHTML = `<p class="loading">Checking all eight workshops…</p>`;
  try {
    const d = await api("/api/handle", { line, sender: $("#sender").value, parser: state.parser, objective: $("#objective").value });
    if (state.current) { state.outcome[state.current.id] = d.behaviour; renderInbox(); }
    renderDecision(d);
  } catch (e) {
    $("#result").innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Read request";
  }
}

async function readAll() {
  const b = $("#read-all");
  b.disabled = true;
  let n = 0;
  for (const m of state.inbox) {
    if (state.outcome[m.id]) continue;
    b.textContent = `Reading ${m.id}…`;
    try {
      const d = await api("/api/handle", { line: m.line, parser: state.parser, objective: $("#objective").value });
      state.outcome[m.id] = d.behaviour;
      n++;
    } catch (e) { toast(`${m.id}: ${e.message}`); break; }
    renderInbox();
  }
  b.disabled = false;
  b.textContent = "Read all";
  toast(n ? `Read ${n} request${n === 1 ? "" : "s"}.` : "Everything is already read.");
}

/* ------------------------------------------------------------------ decision */
function nameOf(d, id) {
  const c = d.candidates.find((x) => x.workshop_id === id);
  return c ? c.name : id;
}

function renderDecision(d) {
  const r = d.request;
  const b = d.behaviour;
  const f = d.facts || {};
  const pick = d.candidates.find((c) => c.workshop_id === d.chosen);
  const alt = d.candidates.find((c) => c.workshop_id === d.alternative);

  let title, status, body = "", facts = [];
  if (b === "allocate") {
    status = "Ready to send";
    if (d.split) {
      title = `Split between ${d.split.map((p) => esc(p.name)).join(" and ")}`;
      facts = [["Back by", dateLabel(f.split.eta_date), "good"], ["Due", d.due_label],
               ...d.split.map((p) => [p.name, `${p.pieces.toLocaleString()} pcs`])];
    } else {
      title = `Send to ${esc(pick.name)}`;
      facts = factsFor(pick, d);
    }
    body = `<p class="explain">${esc(d.explanation)}</p>`;
  } else if (b === "clarify") {
    status = "Ask first";
    title = "Ask before allocating";
    body = `<p class="ask-box">${esc(d.question)}</p>`;
  } else if (b === "refuse") {
    status = "Refuse";
    title = `${esc(nameOf(d, f.refused.workshop))} can't take this`;
    if (alt) facts = [["Instead", alt.name], ...factsFor(alt, d).slice(0, 4)];
    body = `<p class="explain">${esc(d.explanation)}</p>`;
  } else if (b === "impossible") {
    status = "Date can't be met";
    title = `No workshop can make ${esc(d.due_label)}`;
    const e = f.earliest || {};
    if (alt) facts = [["Earliest", alt.eta_label, "bad"], ["Due", d.due_label], ["Late by", days(e.days_late), "bad"], ["Fastest shop", alt.name]];
    body = `<p class="explain">No allocation was made. Choose one:</p>
      <ul class="options">${d.options.map((o) => `<li>${esc(capital(o))}</li>`).join("")}</ul>`;
  } else {
    status = "Can't answer";
    title = "This isn't in the data";
    body = `<p class="explain">${esc(d.explanation)}</p>`;
  }

  const notes = [
    ...r.constraints.map((c) => `<li>Following ${esc(c.imposed_by)}'s instruction: “${esc(c.source_text)}”</li>`),
    ...r.warnings.map((w) => `<li class="warn">${esc(w)}</li>`),
    `<li>Read by ${r.parser.startsWith("llm") ? "Claude Haiku 5.5" : r.parser.includes("fallback") ? "the regex parser (Claude unavailable)" : "the regex parser"}; optimising for ${esc(objectiveLabel(d.objective).toLowerCase())}.</li>`,
  ];

  const actions = b === "allocate"
    ? `<label class="field-inline">Confirmed by <input id="confirm-name" type="text" maxlength="40" value="${esc(store.get("qr.name", ""))}" placeholder="Your name"></label>
       <button class="primary" id="confirm-btn">Confirm and log</button>
       <button class="ghost" id="copy-btn">Copy reply for the chat</button>`
    : `<button class="ghost" id="copy-btn">Copy reply for the chat</button>
       <span class="verdict-meta">Logged automatically — nothing was sent to a workshop.</span>`;

  $("#result").innerHTML = `
    <article class="decision">
      <div class="verdict ${b}">
        <div class="verdict-top">
          <span class="verdict-status">${status}</span>
          <span class="verdict-meta">${esc(r.request_id)} · ${esc(r.sender)} at ${esc(r.time)}${r.order_id ? " · " + esc(r.order_id) : ""}</span>
        </div>
        <h2>${title}</h2>
        <p class="quote">${esc(r.raw_text.replace(/^R\d+\s+\[[^\]]+\]\s+[^:]+:\s*/, ""))}</p>
        ${facts.length ? `<dl class="facts">${facts.map(([k, v, tone]) =>
          `<div><dt>${esc(k)}</dt><dd class="${tone || ""}">${esc(v)}</dd></div>`).join("")}</dl>` : ""}
        ${body}
        <ul class="notes">${notes.join("")}</ul>
        <div class="actions">${actions}</div>
      </div>
      ${d.candidates.length ? stripsHTML(d.candidates, d.due_in_days, d.due_label, d.chosen, d.alternative,
        b === "allocate" ? "Every workshop for this batch" : "Every workshop, for reference") : ""}
    </article>`;

  $("#copy-btn").addEventListener("click", () => copy(d.reply));
  if (b === "allocate") {
    $("#confirm-btn").addEventListener("click", () => confirm(d));
    $("#confirm-name").addEventListener("keydown", (e) => { if (e.key === "Enter") confirm(d); });
  }
}

function factsFor(c, d) {
  const late = c.slack_days < 0;
  return [
    ["Back by", c.eta_label, late ? "bad" : "good"],
    ["Due", d.due_label],
    [late ? "Late by" : "Days to spare", days(Math.abs(c.slack_days)), late ? "bad" : ""],
    ["Cost", money(c.cost)],
    ["Defect rate", `${Math.round(c.defect_rate * 100)}%`],
    ["Queue now", days(Math.round(c.queue_days * 10) / 10)],
  ];
}
// Tool reasons are terse ("status SUSPENDED", "does not make TOPS"); say them plainly.
const plainReason = (r) => r
  .replace(/^status SUSPENDED$/, "suspended, may not take new work")
  .replace(/\b(TOPS|ACCESSORIES)\b/g, (m) => m.toLowerCase());
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
function dateLabel(iso) { const [y, m, dd] = iso.split("-").map(Number); return `${MONTHS[m - 1]} ${dd}`; }

async function confirm(d) {
  const who = $("#confirm-name").value.trim();
  if (!who) { $("#confirm-name").focus(); toast("Enter your name to confirm."); return; }
  store.set("qr.name", who);
  try {
    await api("/api/confirm", { id: d.id, confirmed_by: who });
    if (state.current) { state.outcome[state.current.id] = "confirmed"; renderInbox(); }
    const target = d.split ? "the split" : nameOf(d, d.chosen);
    $(".actions").innerHTML = `<span class="done">Confirmed by ${esc(who)} — ${esc(target)} is on record.</span>
      <button class="ghost" id="copy-btn">Copy reply for the chat</button>`;
    $("#copy-btn").addEventListener("click", () => copy(d.reply));
    toast("Allocation confirmed and logged.");
  } catch (e) { toast(e.message); }
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Reply copied."); }
  catch {
    const t = document.createElement("textarea");
    t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); toast("Reply copied."); } catch { toast("Copy failed — select the text instead."); }
    t.remove();
  }
}

/* ------------------------------------------------------------------ strips */
function stripsHTML(cands, dueDays, dueLabel, chosen, alternative, heading) {
  const inPlay = (c) => c.eligible && !c.excluded_by;
  const ok = cands.filter(inPlay).sort((a, b) => a.eta_days - b.eta_days);
  const out = cands.filter((c) => !inPlay(c));
  const max = Math.max(...ok.map((c) => c.eta_days), dueDays > 0 ? dueDays : 0, 1) * 1.06;   // ok may be empty
  const pct = (v) => `${(Math.max(0, v) / max) * 100}%`;
  const step = max > 40 ? 10 : max > 16 ? 5 : 2;
  const ticks = [];
  const hasDue = dueDays != null && dueDays >= 0;
  for (let t = 0; t <= max; t += step) {
    if (hasDue && Math.abs(t - dueDays) < step * 0.75) continue;   // keep the due label readable
    ticks.push(`<span style="left:${pct(t)}">${dateAfter(t)}</span>`);
  }
  const dueTag = dueDays != null && dueDays >= 0 ? `<span class="due-tag" style="left:${pct(dueDays)}">due ${esc(dueLabel)}</span>` : "";

  const row = (c) => {
    const isPick = c.workshop_id === chosen;
    const isAlt = !isPick && c.workshop_id === alternative;
    if (!c.eligible || c.excluded_by) {
      const why = c.excluded_by ? `Excluded on ${c.excluded_by}'s instruction` : capital(c.ineligible_reasons.map(plainReason).join("; "));
      return `<div class="strip out"><div class="s-name">${esc(c.name)}</div>
        <div class="why-not">${esc(why)}</div><div class="s-out">—</div></div>`;
    }
    let x = 0;
    const seg = (cls, v, label) => { const s = `<span class="bar-seg ${cls}" style="left:${pct(x)};width:${pct(v)}" title="${label}: ${v.toFixed(1)} days"></span>`; x += v; return s; };
    const late = c.meets_due === false;
    const verdict = c.slack_days == null ? "" : late ? `${days(-c.slack_days)} late` : `on time, ${days(c.slack_days)} spare`;
    return `<div class="strip${isPick ? " pick" : ""}">
      <div class="s-name">${esc(c.name)}${isPick ? '<span class="s-pick">Recommended</span>' : isAlt ? '<span class="s-pick">Suggested instead</span>' : ""}
        <span class="s-sub">${Math.round(c.defect_rate * 100)}% defects · ${money(c.cost)}</span></div>
      <div class="track" role="img" aria-label="${esc(c.name)}: waits ${c.queue_days} days, works ${c.work_days} days, transport ${c.lead_days} days, back ${esc(c.eta_label)}">
        ${seg("seg-q", c.queue_days, "Waiting in queue")}${seg("seg-w", c.work_days, "Making the batch")}${seg("seg-r", c.rework_days, "Expected rework")}${seg("seg-m", c.lead_days, "Pickup and delivery")}
        ${dueDays != null && dueDays >= 0 ? `<span class="due-line" style="left:${pct(dueDays)}"></span>` : ""}
      </div>
      <div class="s-out"><span class="s-eta ${late ? "late" : "ok"}">${esc(c.eta_label)}</span><br>${verdict}</div>
    </div>`;
  };

  return `<section class="cands" aria-label="${esc(heading)}">
    <div class="cands-head"><h3>${esc(heading)}</h3>
      <div class="legend"><span><i style="background:var(--seg-queue)"></i>Waiting in queue</span>
        <span><i style="background:var(--seg-work)"></i>Making it</span>
        <span><i style="background:var(--seg-rework)"></i>Expected rework</span>
        <span><i style="background:repeating-linear-gradient(90deg,var(--seg-move) 0 4px,transparent 4px 6px)"></i>Pickup and delivery</span>
        ${dueDays != null ? `<span><i class="due-key"></i>Due date</span>` : ""}</div></div>
    <div class="strips">
      <div class="axis-row" aria-hidden="true"><div></div><div class="track-axis">${ticks.join("")}${dueTag}</div><div></div></div>
      ${ok.map(row).join("")}${out.map(row).join("")}
    </div></section>`;
}

/* ------------------------------------------------------------------ register */
async function loadRegister() {
  const q = new URLSearchParams({ category: $("#q-cat").value, pieces: $("#q-pieces").value, due: $("#q-due").value });
  const outEl = $("#register-out");
  outEl.innerHTML = `<p class="loading">Checking workshops…</p>`;
  try {
    const d = await api(`/api/register?${q}`);
    const n = d.rows.filter((r) => r.eligible && r.meets_due !== false).length;
    const heading = `${n} of 8 can deliver ${d.pieces.toLocaleString()} ${d.category === "TOPS" ? "tops" : "accessories"}${d.due_label ? " by " + d.due_label : ""}`;
    outEl.innerHTML = stripsHTML(d.rows, d.due_in_days, d.due_label, null, null, heading) + `
      <table class="reg-table"><thead><tr><th>Workshop</th><th>Makes</th><th class="num">Pieces / day</th>
        <th class="num">Queue now</th><th class="num">Transport</th><th class="num">Defect rate</th><th class="num">$ / piece</th><th>Status</th><th>Reputation</th></tr></thead>
      <tbody>${d.rows.map((r) => `<tr><td><b>${esc(r.name)}</b></td><td>${esc(r.makes.map((m) => m.toLowerCase()).join(" + "))}</td>
        <td class="num">${r.capacity}</td><td class="num">${days(r.queue_days)}</td><td class="num">${days(r.lead_days)}</td>
        <td class="num">${Math.round(r.defect_rate * 100)}%</td><td class="num">${r.cost_per_piece.toFixed(2)}</td>
        <td>${r.status === "ACTIVE" ? (r.max_batch ? `On trial, max ${r.max_batch} pcs` : "Active") : "Suspended"}</td>
        <td class="notes-cell">${esc(r.notes)}</td></tr>`).join("")}</tbody></table>`;
  } catch (e) { outEl.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

/* ------------------------------------------------------------------ log */
async function loadLog() {
  const el = $("#log-out");
  el.innerHTML = `<p class="loading">Loading…</p>`;
  try {
    const rows = await api("/api/log");
    if (!rows.length) { el.innerHTML = `<p class="log-empty">No decisions yet. Read a request on the Requests tab and it will appear here.</p>`; return; }
    el.innerHTML = rows.map((r) => {
      const what = r.behaviour === "allocate"
        ? (r.confirmed_by ? `Sent to ${nameOf(r, r.chosen)} — confirmed by ${r.confirmed_by}` : `Proposed ${nameOf(r, r.chosen)} (not confirmed)`)
        : LABEL[r.behaviour];
      return `<div class="log-item"><div class="log-when">${esc(r.created_at.replace("T", " "))}<br>${esc(r.request_id)} · ${esc(r.request.sender)}</div>
        <div class="log-what">${esc(what)}</div><p class="log-text">${esc(r.explanation)}</p></div>`;
    }).join("");
  } catch (e) { el.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

init();
