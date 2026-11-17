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
  parser: "baseline",
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
  if (!res.ok) {
    const error = new Error(data.error || 'HTTP ' + res.status);
    error.status = res.status;
    throw error;
  }
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

function init() {
  setupTabs();
  document.querySelectorAll(".seg button").forEach((button) =>
    button.addEventListener("click", () => setParser(button.dataset.parser)));
  $("#query").addEventListener("submit", (event) => { event.preventDefault(); loadRegister(); });
  initChat();
  loadChatSettings();
}

function setParser(parser, remember = true) {
  state.parser = parser;
  if (remember) store.set("qr.parser", parser);
  document.querySelectorAll(".seg button").forEach((button) =>
    button.setAttribute("aria-checked", String(button.dataset.parser === parser)));
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

/* ------------------------------------------------------------------ decision */
function nameOf(d, id) {
  const c = d.candidates.find((x) => x.workshop_id === id);
  return c ? c.name : id;
}

function renderDecision(d, container, chat, latest) {
  const r = d.request;
  const pick = d.candidates.find((c) => c.workshop_id === d.chosen);
  const split = d.split && d.facts.split;
  const facts = split ? [["Back by", dateLabel(split.eta_date), "good"], ["Due", d.due_label],
    ...d.split.map((part) => [part.name, part.pieces.toLocaleString() + " pcs"])]
    : d.behaviour === "allocate" && pick ? factsFor(pick, d) : [];
  const parser = r.parser === "follow-up" ? "Field update" : r.parser.startsWith("llm") ? "Claude Haiku" : "Regex";
  const canConfirm = latest && d.behaviour === "allocate" && !chat.confirmed && !chat.expired;
  const choices = latest && d.behaviour === "clarify" && r.candidate_orders.length
    ? '<div class="candidate-buttons">' + r.candidate_orders.map((order) =>
      '<button type="button" class="ghost small" data-order="' + esc(order) + '">' + esc(order) + '</button>').join("") + '</div>'
    : "";
  const candidateDetails = d.candidates.length ? '<details class="candidate-details"><summary>Compare workshops</summary>'
    + stripsHTML(d.candidates, d.due_in_days, d.due_label, d.chosen, d.alternative, "Workshop estimates") + '</details>' : "";
  container.innerHTML = '<div class="chat-decision ' + esc(d.behaviour) + '">'
    + '<div class="decision-heading"><strong>' + esc(LABEL[d.behaviour] || d.behaviour) + '</strong>'
    + '<span>' + esc(parser + " · " + weightsText(Number(d.objective.split("_")[1]))) + '</span></div>'
    + '<p class="answer">' + esc(d.reply) + '</p>' + choices
    + (facts.length ? '<dl class="facts">' + facts.map(([key, value, tone]) =>
      '<div><dt>' + esc(key) + '</dt><dd class="' + (tone || "") + '">' + esc(value) + '</dd></div>').join("") + '</dl>' : "")
    + (r.warnings.length ? '<ul class="notes">' + r.warnings.map((note) => '<li class="warn">' + esc(note) + '</li>').join("") + '</ul>' : "")
    + candidateDetails
    + '<div class="chat-actions">'
    + (canConfirm ? '<input class="confirm-name" type="text" maxlength="40" aria-label="Confirmed by" placeholder="Your name" value="' + esc(store.get("qr.name", "")) + '">'
      + '<button type="button" class="primary small confirm-action">Confirm and log</button>' : "")
    + (latest && chat.confirmed ? '<span class="done">Confirmed by ' + esc(chat.confirmed) + '</span>' : "")
    + '<button type="button" class="ghost small copy-action">Copy reply</button></div></div>';
  $(".copy-action", container).addEventListener("click", () => copy(d.reply));
  if (!canConfirm) return;
  const confirm = $(".confirm-action", container);
  const input = $(".confirm-name", container);
  confirm.addEventListener("click", async () => {
    const who = input.value.trim();
    if (!who) { input.focus(); return; }
    confirm.disabled = true;
    try {
      const result = await api("/api/confirm", { id: d.id, confirmed_by: who });
      chat.confirmed = result.confirmed_by;
      store.set("qr.name", who);
      saveChats();
      refreshList();
      if (workspace.current === chat.key) renderChat();
      toast("Allocation confirmed and logged.");
    } catch (error) {
      confirm.disabled = false;
      toast(error.message);
    }
  });
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") confirm.click(); });
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
        ? (r.confirmed_by ? `Allocation ${r.split ? r.split.map((part) => part.name).join(" + ") : nameOf(r, r.chosen)} — confirmed by ${r.confirmed_by}` : `Proposed ${nameOf(r, r.chosen)} (not confirmed)`)
        : LABEL[r.behaviour];
      return `<div class="log-item"><div class="log-when">${esc(r.created_at.replace("T", " "))}<br>${esc(r.request_id)} · ${esc(r.request.sender)}</div>
        <div class="log-what">${esc(what)}</div><p class="log-text">${esc(r.explanation)}</p></div>`;
    }).join("");
  } catch (e) { el.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

document.addEventListener("DOMContentLoaded", init);
