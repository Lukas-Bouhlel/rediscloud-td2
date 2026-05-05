const socket = io({
  transports: ["websocket"],
  upgrade: false,
  reconnection: true,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 5000,
});

const serverPill = document.getElementById("server-pill");
const socketPill = document.getElementById("socket-pill");
const messagesFeed = document.getElementById("messages-feed");
const messageCount = document.getElementById("message-count");
const debugLog = document.getElementById("debug-log");
const clearDebugBtn = document.getElementById("clear-debug-btn");
const publishForm = document.getElementById("publish-form");
const input = document.getElementById("message-input");
const publishBtn = document.getElementById("publish-btn");
const publishStatus = document.getElementById("publish-status");

let totalMessages = 0;

function getPublishedAt(payload) {
  return payload?.data?.published_at || payload?.published_at || "";
}

function formatDate(value) {
  if (!value) {
    return "date inconnue";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("fr-FR", { hour12: false });
}

function setSocketState(label) {
  socketPill.textContent = `socket: ${label}`;
}

function setEmptyState() {
  if (messagesFeed.childElementCount > 0) {
    return;
  }

  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = "Aucun message pour le moment.";
  messagesFeed.appendChild(empty);
}

function clearEmptyState() {
  const empty = messagesFeed.querySelector(".empty");
  if (empty) {
    empty.remove();
  }
}

function addDebug(label, details = null) {
  const entry = document.createElement("div");
  entry.className = "debug-entry";

  const head = document.createElement("div");
  head.className = "debug-head";
  head.textContent = `[${new Date().toISOString()}] ${label}`;
  entry.appendChild(head);

  if (details !== null && details !== undefined) {
    const payload = document.createElement("pre");
    payload.className = "debug-payload";
    payload.textContent =
      typeof details === "string" ? details : JSON.stringify(details, null, 2);
    entry.appendChild(payload);
  }

  debugLog.prepend(entry);

  while (debugLog.childElementCount > 250) {
    debugLog.removeChild(debugLog.lastChild);
  }
}

function renderMessage(payload, kind) {
  clearEmptyState();

  const card = document.createElement("article");
  card.className = "message-card";

  const top = document.createElement("div");
  top.className = "message-top";

  const title = document.createElement("div");
  title.className = "message-title";
  title.textContent = payload?.data?.message || "(message vide)";

  const kindLabel = document.createElement("div");
  kindLabel.className = "message-kind";
  kindLabel.textContent = `${kind} | ${formatDate(getPublishedAt(payload))}`;

  top.appendChild(title);
  top.appendChild(kindLabel);

  const meta = document.createElement("div");
  meta.className = "message-meta";
  const sourceServer = payload?.data?.server_id || payload?.server_id || "unknown";
  meta.textContent = `server: ${sourceServer}`;

  card.appendChild(top);
  card.appendChild(meta);

  messagesFeed.prepend(card);

  totalMessages += 1;
  messageCount.textContent = String(totalMessages);
}

function replaceWithInitialState(payload) {
  messagesFeed.innerHTML = "";
  totalMessages = 0;
  messageCount.textContent = "0";

  const entries = Object.entries(payload.entries || {}).map(([key, value]) => ({
    redis_key: key,
    ...value,
  }));

  entries.sort((a, b) => {
    const aTime = Date.parse(getPublishedAt(a)) || 0;
    const bTime = Date.parse(getPublishedAt(b)) || 0;
    return bTime - aTime;
  });

  entries.forEach((entry) => renderMessage(entry, "initial"));
  setEmptyState();
}

clearDebugBtn.addEventListener("click", () => {
  debugLog.innerHTML = "";
  addDebug("debug log reset");
});

socket.on("connect", () => {
  const transport = socket.io.engine && socket.io.engine.transport
    ? socket.io.engine.transport.name
    : "unknown";

  setSocketState(`connected (${transport})`);
  publishStatus.textContent = "Connecte au serveur";
  addDebug("socket connected", { socket_id: socket.id, transport });
});

socket.on("connect_error", (err) => {
  setSocketState("error");
  publishStatus.textContent = `Erreur websocket: ${err.message}`;
  addDebug("socket connect_error", err.message);
});

socket.on("disconnect", (reason) => {
  setSocketState(`disconnected (${reason})`);
  publishStatus.textContent = `WebSocket deconnecte (${reason})`;
  addDebug("socket disconnected", reason);
});

socket.on("initial_state", (payload) => {
  serverPill.textContent = `server_id: ${payload.server_id}`;
  replaceWithInitialState(payload);
  addDebug("initial_state recu", {
    server_id: payload.server_id,
    entries: Object.keys(payload.entries || {}).length,
  });
});

socket.on("update", (payload) => {
  renderMessage(payload, "update");
  addDebug("update recu", payload);
});

publishForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const message = input.value.trim();
  if (!message) {
    publishStatus.textContent = "Veuillez saisir un message";
    return;
  }

  publishBtn.disabled = true;
  publishStatus.textContent = "Publication en cours...";
  addDebug("publish start", { message });

  try {
    const response = await fetch("/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });

    const text = await response.text();
    let data = {};

    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      data = { raw_response: text };
    }

    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }

    publishStatus.textContent = `Publie: ${data.redis_key || "ok"}`;
    input.value = "";
    addDebug("publish success", data);
  } catch (err) {
    publishStatus.textContent = `Erreur: ${err.message}`;
    addDebug("publish failed", err.message);
  } finally {
    publishBtn.disabled = false;
  }
});

setSocketState("connecting...");
setEmptyState();
addDebug("client started");
