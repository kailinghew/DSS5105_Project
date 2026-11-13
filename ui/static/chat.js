/* Requests view. Browser storage keeps a bounded transcript; the server keeps the dispatch draft. */
const TRADEOFF_DEFAULT = [[100, 0], [75, 25], [50, 50], [25, 75], [0, 100]];
const CHAT_KEY = "qr.chat.v1";
const MAX_HISTORY = 12;
const MAX_CONVERSATIONS = 24;

function restoreChats() {
  try {
    const saved = JSON.parse(store.get(CHAT_KEY, "{}"));
    return Array.isArray(saved.chats) ? saved : { chats: [], current: null };
  } catch { return { chats: [], current: null }; }
}

const workspace = { ...restoreChats(), samples: [], weights: TRADEOFF_DEFAULT, pending: new Set() };
const currentChat = () => workspace.chats.find((chat) => chat.key === workspace.current);
const weightsText = (level) => {
  const [cost, defects] = workspace.weights[level] || TRADEOFF_DEFAULT[2];
  return cost + "% cost · " + defects + "% defects";
};
const messageText = (line) => line.replace(/^R\d+\s+\[[^\]]+\]\s+[^:]+:\s*/, "");

function saveChats() {
  store.set(CHAT_KEY, JSON.stringify({ chats: workspace.chats, current: workspace.current }));
}

function refreshList() {
  const rows = workspace.chats.filter((chat) => chat.messages.length);
  $("#chat-list").innerHTML = rows.map((chat) =>
    '<li><button type="button" class="chat-item" data-chat="' + esc(chat.key) + '"'
    + (chat.key === workspace.current ? ' aria-current="true"' : '')
    + '><span class="chat-item-title">' + esc(chat.title) + '</span><small>'
    + esc(chat.confirmed ? "Confirmed" : chat.order || "Dispatch request") + '</small></button></li>'
  ).join("") || '<li class="rail-empty">Your chats will appear here.</li>';
}

function openChat(key) {
  workspace.current = key;
  saveChats();
  refreshList();
  $("#view-desk").classList.remove("rail-open");
  $("#rail-toggle").setAttribute("aria-expanded", "false");
  renderChat();
}

function createChat() {
  if (currentChat() && !currentChat().messages.length && !workspace.pending.has(workspace.current)) {
    $("#message").value = "";
    openChat(workspace.current);
    $("#message").focus();
    return;
  }
  workspace.chats = workspace.chats.filter((chat) => chat.messages.length || workspace.pending.has(chat.key));
  const key = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random();
  workspace.chats.unshift({ key, title: "New conversation", level: 2, turn: 0,
    id: null, messages: [], compacted: 0 });
  workspace.chats.length = Math.min(workspace.chats.length, MAX_CONVERSATIONS);
  $("#message").value = "";
  openChat(key);
  $("#message").focus();
}

function syncComposer() {
  const chat = currentChat();
  const range = $("#tradeoff");
  range.value = chat?.level ?? 2;
  const label = weightsText(Number(range.value));
  $("#tradeoff-value").textContent = label;
  range.setAttribute("aria-valuetext", label);
  $("#chat-title").textContent = chat?.title || "New conversation";
  const pending = workspace.pending.has(chat?.key);
  const disabled = pending || chat?.confirmed || chat?.expired;
  $("#message").disabled = !!disabled;
  $("#read-btn").disabled = !!disabled;
  range.disabled = !!disabled;
  $("#read-btn").innerHTML = pending ? "Checking…" : 'Send <span aria-hidden="true">↑</span>';
  $("#message").placeholder = chat?.messages.length ? "Reply to the desk…" : "Message the desk…";
  $("#compose-status").textContent = chat?.expired ? "Server session expired. Start a new chat to continue."
    : chat?.confirmed ? "Allocation confirmed. Start a new chat for another order."
    : chat?.error || "";
}

function renderChat() {
  const chat = currentChat();
  const stream = $("#chat-stream");
  syncComposer();
  if (!chat?.messages.length) {
    stream.innerHTML = '<div class="chat-empty"><div class="desk-symbol" aria-hidden="true">≋</div>'
      + '<h3>What needs a workshop?</h3><p>Paste a dispatch message or open a request from the course inbox.</p>'
      + '<div class="starter-list">' + [ "R21", "R05", "R01" ].map((id, i) =>
        '<button type="button" class="starter" data-sample="' + id + '">'
        + ["Find an on-time workshop", "Confirm a new deadline", "Clarify an ambiguous order"][i]
        + '<span aria-hidden="true">↗</span></button>').join("") + '</div></div>';
    return;
  }
  stream.replaceChildren();
  if (chat.compacted) {
    const summary = document.createElement("p");
    summary.className = "history-summary";
    summary.textContent = chat.compacted + " earlier messages condensed · " + chat.summary;
    stream.append(summary);
  }
  chat.messages.forEach((entry, index) => {
    const article = document.createElement("article");
    article.className = "chat-message " + entry.role;
    if (entry.role === "user") {
      const text = document.createElement("p");
      text.textContent = entry.text;
      article.append(text);
    } else {
      const latest = index === chat.messages.length - 1;
      article.innerHTML = '<div class="assistant-label"><span aria-hidden="true">≋</span> Dispatch desk</div>';
      const body = document.createElement("div");
      body.className = "assistant-body";
      if (entry.decision) renderDecision(entry.decision, body, chat, latest);
      else {
        const text = document.createElement("p");
        text.textContent = entry.text;
        body.append(text);
      }
      article.append(body);
    }
    stream.append(article);
  });
  $("#chat-scroll").scrollTop = $("#chat-scroll").scrollHeight;
}

function compactHistory(chat, decision) {
  // Older rich cards keep their text. Earlier turns become the current validated dispatch facts.
  chat.messages.slice(0, -2).forEach((entry) => { delete entry.decision; });
  if (chat.messages.length > MAX_HISTORY) {
    const removed = chat.messages.length - MAX_HISTORY;
    chat.messages.splice(0, removed);
    chat.compacted += removed;
  }
  const r = decision.request;
  chat.summary = [
    r.order_id || (r.candidate_orders.length ? r.candidate_orders.join(", ") : "Order pending"),
    r.pieces == null ? null : r.pieces.toLocaleString("en-US") + " pieces",
    r.due_date ? "due " + dateLabel(r.due_date) : null,
    decision.keep_together ? "keep together" : null,
    r.missing.length ? "Awaiting " + r.missing.map((field) => ({ order: "order", pieces: "quantity", due_date: "deadline" }[field])).join(", ") : null,
    r.constraints.length ? "Instructions: " + r.constraints.map((item) => item.source_text || item.kind).join("; ") : null,
  ].filter(Boolean).join(" · ");
}

async function sendMessage(text, sender = "Dispatcher") {
  const chat = currentChat();
  if (!chat || workspace.pending.has(chat.key) || chat.confirmed || chat.expired || !text.trim()) return;
  const input = $("#message");
  const visibleText = messageText(text);
  workspace.pending.add(chat.key);
  chat.error = "";
  chat.messages.push({ role: "user", text: visibleText });
  input.value = "";
  renderChat();
  try {
    const decision = await api("/api/chat", {
      line: text, sender, parser: state.parser, level: chat.level,
      ...(chat.id ? { conversation_id: chat.id, turn: chat.turn } : {}),
    });
    chat.id = decision.conversation_id;
    chat.turn = decision.turn;
    chat.order = decision.request.order_id;
    if (chat.messages.length === 1) chat.title = visibleText.length > 52 ? visibleText.slice(0, 52).replace(/\s+\S*$/, "") + "…" : visibleText;
    chat.messages.push({ role: "assistant", text: decision.reply, decision });
    compactHistory(chat, decision);
  } catch (error) {
    chat.messages.pop();
    chat.error = error.message;
    chat.expired = error.status === 410 || error.status === 409;
    if (workspace.current === chat.key) input.value = visibleText;
  } finally {
    workspace.pending.delete(chat.key);
    saveChats();
    refreshList();
    if (workspace.current === chat.key) renderChat();
  }
}

async function useSample(id) {
  const sample = workspace.samples.find((item) => item.id === id);
  if (!sample) { toast("Course inbox is still loading."); return; }
  createChat();
  await sendMessage(sample.line, sample.sender);
}

function initChat() {
  if (!currentChat()) createChat();
  else openChat(workspace.current);
  $("#new-chat").addEventListener("click", createChat);
  $("#rail-toggle").addEventListener("click", (event) => {
    const open = $("#view-desk").classList.toggle("rail-open");
    event.currentTarget.setAttribute("aria-expanded", String(open));
  });
  $("#chat-list").addEventListener("click", (event) => {
    const key = event.target.closest("[data-chat]")?.dataset.chat;
    if (key && key !== workspace.current) {
      $("#message").value = "";
      openChat(key);
      $("#message").focus();
    }
  });
  $("#view-desk").addEventListener("click", (event) => {
    const sample = event.target.closest("[data-sample]")?.dataset.sample;
    const order = event.target.closest("[data-order]")?.dataset.order;
    if (sample) useSample(sample);
    if (order) sendMessage(order);
  });
  $("#tradeoff").addEventListener("input", (event) => {
    currentChat().level = Number(event.target.value);
    syncComposer();
    saveChats();
  });
  $("#tradeoff").addEventListener("change", () => {
    const chat = currentChat();
    const latest = chat.messages.at(-1)?.decision;
    if (!$("#message").value.trim() && latest && ["allocate", "impossible", "refuse"].includes(latest.behaviour)) {
      sendMessage("Recheck");
    }
  });
  $("#compose").addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage($("#message").value.trim());
  });
  $("#message").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("#compose").requestSubmit();
    }
  });
}

async function loadChatSettings() {
  try {
    const [settings, samples] = await Promise.all([api("/api/status"), api("/api/inbox")]);
    state.today = new Date(settings.today + "T00:00:00Z");
    $("#today").textContent = state.today.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    workspace.weights = settings.tradeoff || TRADEOFF_DEFAULT;
    $("#p-llm").disabled = !settings.llm;
    $("#p-llm").title = settings.llm ? "" : "Claude is not configured on this server.";
    setParser(settings.llm && store.get("qr.parser", "llm") === "llm" ? "llm" : "baseline", false);
    workspace.samples = samples;
    $("#sample-count").textContent = samples.length;
    $("#sample-list").innerHTML = samples.map((sample) =>
      '<li><button class="chat-item" type="button" data-sample="' + esc(sample.id) + '">'
      + '<span class="chat-item-title">' + esc(sample.id + " · " + sample.sender) + '</span><small>'
      + esc(sample.text) + '</small></button></li>'
    ).join("");
    syncComposer();
  } catch (error) { toast(error.message); }
}
