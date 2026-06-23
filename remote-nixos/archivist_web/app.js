const state = {
  conversationId: localStorage.getItem("archivist.conversationId") || null,
  adminConversationId: localStorage.getItem("archivist.adminConversationId") || null,
  indexPollTimer: null,
  activeView: "home",
  preDedupePollTimer: null,
  fileOffset: 0,
  fileLimit: 80,
  fileTotal: 0,
  selectedFileIds: new Set(),
  tags: [],
  previewPath: null,
  previewFileId: null,
  cowriterHistory: [],
  cowriterAutosaveTimer: null,
  cowriterCurrentFile: null,
  cowriterAutosaveFile: null,
  explorerPath: null,
  explorerParent: null,
  explorerRoot: null,
  locationBrowserPath: null,
  locationBrowseTargetInput: null,
  ingestQueue: [],
  ingestRunning: false,
  noteSaveTimers: {},
  discoveryData: null,
  selectedDiscoveryNodeId: null,
  selectedConstellationCardNodeId: null,
  adminHistory: [],
  adminControl: null,
  adminConnect: null,
  adminEngineTools: [],
  adminSuggestedTools: [],
  adminDevelopmentTasks: [],
  hostStats: null,
  hostStatsTimer: null,
  installerProfile: null,
  timelineOverview: null,
  timelinePeople: [],
  faceObservations: [],
  selectedFaceObservationId: null,
  faceDetectorStatus: null,
  videoContext: null,
  videoFfmpeg: null,
  visionStatus: null,
  transcriptionStatus: null,
  videoPresets: [],
  videoScanPollTimer: null,
  indexEstimate: 44000
};
const MAINTENANCE_CARD_ORDER_KEY = "archivist.maintenanceCardOrder";
const HOME_CARD_ORDER_KEY = "archivist.homeCardOrder";
const LEFT_RAIL_CARD_ORDER_KEY = "archivist.leftRailCardOrder";
const THEME_KEY = "archivist.theme";

function savedTheme() {
  return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
}

function applyTheme(theme) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  localStorage.setItem(THEME_KEY, nextTheme);
  const button = document.getElementById("themeToggleBtn");
  if (!button) return;
  const nextLabel = nextTheme === "light" ? "Switch to dark theme" : "Switch to light theme";
  button.textContent = nextTheme === "light" ? "L" : "D";
  button.title = nextLabel;
  button.setAttribute("aria-label", nextLabel);
}

function toggleTheme() {
  applyTheme(savedTheme() === "light" ? "dark" : "light");
}

async function readJSON(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed with ${res.status}`);
  }
  return data;
}

async function postJSON(url, payload = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  return await readJSON(res);
}

async function postURL(url) {
  const res = await fetch(url, {method: "POST"});
  return await readJSON(res);
}

async function getJSON(url) {
  const res = await fetch(url);
  return await readJSON(res);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(text) {
  const avatar = document.getElementById("avatarStage");
  avatar?.classList.remove("avatar-thinking", "avatar-speaking");
  if (["Thinking", "Indexing", "Indexing paused for chat", "Starting index", "Ingesting", "Wiping index", "Scanning"].includes(text)) {
    avatar?.classList.add("avatar-thinking");
  }
  document.getElementById("status").textContent = text || "Idle";
}

let thinkingPhaseTimer = null;

function speakEffect(ms = 1800) {
  const avatar = document.getElementById("avatarStage");
  avatar?.classList.remove("avatar-thinking");
  avatar?.classList.add("avatar-speaking");
  setAvatarPose("speaking");
  window.setTimeout(() => {
    avatar?.classList.remove("avatar-speaking");
    if (document.getElementById("status").textContent !== "Idle") return;
    setAvatarPose("idle");
  }, ms);
}

function setAvatarPose(pose) {
  const fg = document.getElementById("avatarFg");
  if (!fg) return;
  const poses = {
    idle: "/web/AvaTar/AvaPoses/AvaPoseBook1.png",
    thinking: "/web/AvaTar/AvaPoses/AvaPose3.png",
    speaking: "/web/AvaTar/AvaPoses/AvaPose1.png",
    reading: "/web/AvaTar/AvaPoses/AvaPoseBook1.png",
    candle: "/web/AvaTar/AvaPoses/AvaPoseCandle.png",
    watch: "/web/AvaTar/AvaPoses/AvaPoseWatch.png",
  };
  const nextSrc = poses[pose] || poses.idle;
  if (fg.src.includes(nextSrc)) return;
  fg.style.opacity = "0";
  setTimeout(() => {
    fg.src = nextSrc;
    fg.style.opacity = "1";
  }, 150);
}

function startThinkingSequence() {
  const fg = document.getElementById("avatarFg");
  if (!fg) return;

  clearTimeout(thinkingPhaseTimer);

  const poses = {
    thinkingStart: "/web/AvaTar/AvaPoses/AvaPose2.png",
    thinkingEnd: "/web/AvaTar/AvaPoses/AvaPose3.png",
    idle: "/web/AvaTar/AvaPoses/AvaPoseBook1.png",
  };

  fg.style.opacity = "0";
  setTimeout(() => {
    fg.src = poses.thinkingStart;
    fg.style.opacity = "1";
  }, 150);

  thinkingPhaseTimer = setTimeout(() => {
    fg.style.opacity = "0";
    setTimeout(() => {
      fg.src = poses.thinkingEnd;
      fg.style.opacity = "1";
    }, 150);
  }, 3000);
}

function clearThinkingSequence() {
  clearTimeout(thinkingPhaseTimer);
}

function setStatus(text) {
  const avatar = document.getElementById("avatarStage");
  avatar?.classList.remove("avatar-thinking", "avatar-speaking");
  if (["Thinking", "Indexing", "Indexing paused for chat", "Starting index", "Ingesting", "Wiping index", "Scanning"].includes(text)) {
    avatar?.classList.add("avatar-thinking");
    startThinkingSequence();
  } else {
    clearThinkingSequence();
    setAvatarPose("idle");
  }
  document.getElementById("status").textContent = text || "Idle";
}

function shortTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let size = value / 1024;
  let unit = units[0];
  for (let i = 1; i < units.length && size >= 1024; i += 1) {
    size /= 1024;
    unit = units[i];
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${unit}`;
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function compactMiddle(value, maxLength = 110) {
  const text = String(value || "");
  if (text.length <= maxLength) return text;
  const keep = Math.max(12, Math.floor((maxLength - 3) / 2));
  return `${text.slice(0, keep)}...${text.slice(-keep)}`;
}

function confirmationCode() {
  if (window.crypto?.getRandomValues) {
    const values = new Uint32Array(1);
    window.crypto.getRandomValues(values);
    return String(100000 + (values[0] % 900000));
  }
  return String(Math.floor(100000 + Math.random() * 900000));
}

function confirmWithNumber(message) {
  const code = confirmationCode();
  const answer = window.prompt(`${message}\n\nType this confirmation number to continue:\n${code}`);
  if (answer === null) return false;
  if (answer.trim() === code) return true;
  window.alert("Confirmation number did not match. Index wipe cancelled.");
  return false;
}

function topNavViewFor(view) {
  if (view === "explorer") return "maintenance";
  if (view === "discovery") return "home";
  if (view === "notes") return "home";
  if (view === "chat") return "home";
  if (["audio", "video"].includes(view)) return "maintenance";
  return view;
}

function updateSubtabs(topView, view, scrollCard = "") {
  document.querySelectorAll(".subtab-group").forEach(group => {
    group.classList.toggle("active", group.dataset.subtabsFor === topView);
  });
  const group = document.querySelector(`.subtab-group[data-subtabs-for="${topView}"]`);
  if (!group) return;
  const tabs = Array.from(group.querySelectorAll(".subtab"));
  tabs.forEach(tab => tab.classList.remove("active"));
  let active = null;
  if (scrollCard) {
    active = tabs.find(tab => tab.dataset.scrollCard === scrollCard);
  }
  if (!active) {
    active = tabs.find(tab => (tab.dataset.view || "") === view && !tab.dataset.scrollCard);
  }
  if (!active) {
    active = tabs.find(tab => (tab.dataset.view || "") === view);
  }
  if (!active) {
    active = tabs.find(tab => !tab.disabled);
  }
  active?.classList.add("active");
}

function scrollToMaintenanceCard(cardId) {
  if (!cardId) return;
  window.setTimeout(() => {
    const container = document.getElementById("maintenanceCards");
    const card = document.querySelector(`#maintenanceCards > [data-card-id="${cardId}"]`);
    if (!container || !card) return;
    if (container.scrollHeight > container.clientHeight) {
      container.scrollTo({top: Math.max(0, card.offsetTop - container.offsetTop - 10), behavior: "smooth"});
    } else {
      card.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }, 180);
}

function scrollToHomeCard(cardId) {
  if (!cardId) return;
  window.setTimeout(() => {
    const container = document.querySelector("#homeView .home-body");
    const card = document.querySelector(`#homeDashboardCards > [data-card-id="${cardId}"]`);
    if (!container || !card) return;
    if (container.scrollHeight > container.clientHeight) {
      container.scrollTo({top: Math.max(0, card.offsetTop - container.offsetTop - 10), behavior: "smooth"});
    } else {
      card.scrollIntoView({behavior: "smooth", block: "start"});
    }
  }, 180);
}

function chatContextForView(view) {
  const contexts = {
    chat: {
      title: "Co-writer Chat",
      placeholder: "Ask, revise, or drop a file..."
    },
    audio: {
      title: "Audio Chat",
      placeholder: "Ask about recordings, transcripts, clips, or audio notes..."
    },
    video: {
      title: "Video Chat",
      placeholder: "Ask about media, edits, scenes, captions, or creation..."
    },
    forensics: {
      title: "Forensics Chat",
      placeholder: "Ask about metadata, OCR, identity, or file evidence..."
    },
    tools: {
      title: "Tools Chat",
      placeholder: "Ask for local or remote admin, setup, recovery, or maintenance..."
    }
  };
  return contexts[view] || {
    title: "Archivist Chat",
    placeholder: "Ask the Archivist..."
  };
}

function setView(view, options = {}) {
  state.activeView = view;
  const topView = options.topView || topNavViewFor(view);
  document.querySelectorAll(".mode-tab").forEach(button => {
    button.classList.toggle("active", button.dataset.view === topView);
  });
  updateSubtabs(topView, view, options.scrollCard || "");
  document.getElementById("homeView").classList.toggle("active", view === "home");
  document.getElementById("chatView").classList.toggle("active", view === "chat");
  document.getElementById("audioView").classList.toggle("active", view === "audio");
  document.getElementById("videoView").classList.toggle("active", view === "video");
  document.getElementById("maintenanceView").classList.toggle("active", view === "maintenance");
  document.getElementById("explorerView").classList.toggle("active", view === "explorer");
  document.getElementById("discoveryView").classList.toggle("active", view === "discovery");
  document.getElementById("notesView").classList.toggle("active", view === "notes");
  document.getElementById("forensicsView").classList.toggle("active", view === "forensics");
  document.getElementById("toolsView").classList.toggle("active", view === "tools");
  const chatTitle = document.getElementById("chatPanelTitle");
  const chatInput = document.getElementById("chatInput");
  const chatContext = chatContextForView(view);
  if (chatTitle) chatTitle.textContent = chatContext.title;
  if (chatInput) chatInput.placeholder = chatContext.placeholder;
  let viewLoad = null;
  if (view === "home") {
    loadDashboard();
    loadMemories();
    loadConstellationCard();
  }
  if (view === "maintenance") {
    renderAdminChat();
    viewLoad = loadMaintenance();
  }
  if (view === "explorer") loadExplorer(state.explorerPath);
  if (view === "discovery") loadDiscovery();
  if (view === "notes") loadNotes();
  if (view === "video") loadVideoToolStatus();
  if (view === "home" && options.homeCard) {
    scrollToHomeCard(options.homeCard);
  }
  if (view === "maintenance" && options.scrollCard) {
    if (viewLoad?.finally) viewLoad.finally(() => scrollToMaintenanceCard(options.scrollCard));
    else scrollToMaintenanceCard(options.scrollCard);
  }
}

const VIEW_COMMANDS = [
  {view: "home", topView: "home", label: "Home", names: ["home", "dashboard", "landing"]},
  {view: "notes", topView: "home", label: "Notes", names: ["notes", "note cards"]},
  {view: "home", topView: "home", homeCard: "constellation", label: "Data Constellation", names: ["constellation", "data constellation", "map"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "index", label: "Archive System", names: ["archive", "maintenance", "index", "index progress", "telemetry", "system", "admin", "settings"]},
  {view: "explorer", topView: "maintenance", label: "Explorer", names: ["explorer", "file explorer", "files"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "files", label: "File View", names: ["file view", "file table"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "dedupe", label: "Dedupe", names: ["dedupe", "deduplication", "duplicates"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "locations", label: "Sources", names: ["sources", "archive locations", "locations"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "face-review", label: "Face Review", names: ["face review", "faces", "face tagging", "people tagging", "timeline people"]},
  {view: "chat", topView: "home", label: "Co-writer", names: ["co-writer", "cowriter", "writer"]},
  {view: "audio", topView: "maintenance", label: "Audio", names: ["audio", "recording", "recordings", "audio notes", "listening"]},
  {view: "video", topView: "maintenance", label: "Video", names: ["video", "media", "video tools", "media creation"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "stats", label: "Archive stats", names: ["stats", "system stats"]},
  {view: "maintenance", topView: "maintenance", scrollCard: "models", label: "Model routing", names: ["models", "model routing"]}
];

function navigationTargetForQuery(query) {
  const text = String(query || "").trim().toLowerCase();
  if (!/^(go to|open|show|switch to|take me to|navigate to)\b/.test(text)) return null;
  const command = text.replace(/^(go to|open|show|switch to|take me to|navigate to)\b/, "").trim();
  return VIEW_COMMANDS.find(item => item.names.some(name => command === name || command.includes(name))) || null;
}

function maybeNavigateFromChat(query) {
  const target = navigationTargetForQuery(query);
  if (!target) return false;
  appendMessage("user", query);
  setView(target.view, {topView: target.topView, scrollCard: target.scrollCard || "", homeCard: target.homeCard || ""});
  appendMessage("assistant", `Opened ${target.label}.`);
  return true;
}

function maintenanceCards() {
  return Array.from(document.querySelectorAll("#maintenanceCards > .reorderable-card"));
}

function savedMaintenanceOrder() {
  try {
    const parsed = JSON.parse(localStorage.getItem(MAINTENANCE_CARD_ORDER_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    if (parsed.length && !parsed.includes("intelligent-admin")) {
      const next = [...parsed];
      const insertAfter = next.indexOf("index");
      next.splice(insertAfter >= 0 ? insertAfter + 1 : 0, 0, "intelligent-admin");
      localStorage.setItem(MAINTENANCE_CARD_ORDER_KEY, JSON.stringify(next));
      return next;
    }
    if (parsed.length && !parsed.includes("face-review")) {
      const next = [...parsed];
      const insertAfter = next.indexOf("intelligent-admin");
      next.splice(insertAfter >= 0 ? insertAfter + 1 : 0, 0, "face-review");
      localStorage.setItem(MAINTENANCE_CARD_ORDER_KEY, JSON.stringify(next));
      return next;
    }
    return parsed;
  } catch {
    return [];
  }
}

function applyMaintenanceCardOrder() {
  const container = document.getElementById("maintenanceCards");
  if (!container) return;
  const cards = maintenanceCards();
  const byId = new Map(cards.map(card => [card.dataset.cardId, card]));
  const seen = new Set();
  savedMaintenanceOrder().forEach(id => {
    const card = byId.get(id);
    if (!card) return;
    container.appendChild(card);
    seen.add(id);
  });
  cards.forEach(card => {
    if (!seen.has(card.dataset.cardId)) container.appendChild(card);
  });
}

function saveMaintenanceCardOrder() {
  const order = maintenanceCards().map(card => card.dataset.cardId).filter(Boolean);
  localStorage.setItem(MAINTENANCE_CARD_ORDER_KEY, JSON.stringify(order));
}

function maintenanceCardAfterPointer(container, y, draggedCard) {
  return Array.from(container.querySelectorAll(".reorderable-card:not(.is-dragging)")).find(card => {
    if (card === draggedCard) return false;
    const box = card.getBoundingClientRect();
    return y < box.top + box.height / 2;
  }) || null;
}

function wireMaintenanceCardReordering() {
  const container = document.getElementById("maintenanceCards");
  if (!container || container.dataset.reorderWired === "true") return;
  container.dataset.reorderWired = "true";
  applyMaintenanceCardOrder();

  maintenanceCards().forEach(card => {
    const head = card.querySelector(".section-head");
    if (!head || head.querySelector(".drag-grip")) return;
    const grip = el("span", "drag-grip", "::");
    grip.draggable = true;
    grip.title = "Drag to reorder";
    grip.setAttribute("aria-label", "Drag to reorder");
    grip.addEventListener("dragstart", event => {
      state.draggedMaintenanceCardId = card.dataset.cardId;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.cardId || "");
    });
    grip.addEventListener("dragend", () => {
      state.draggedMaintenanceCardId = null;
      card.classList.remove("is-dragging");
      maintenanceCards().forEach(item => item.classList.remove("is-drop-target"));
      saveMaintenanceCardOrder();
    });
    head.prepend(grip);
  });

  container.addEventListener("dragover", event => {
    const draggedId = state.draggedMaintenanceCardId;
    if (!draggedId) return;
    const draggedCard = maintenanceCards().find(card => card.dataset.cardId === draggedId);
    if (!draggedCard) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const after = maintenanceCardAfterPointer(container, event.clientY, draggedCard);
    if (after) container.insertBefore(draggedCard, after);
    else container.appendChild(draggedCard);
    maintenanceCards().forEach(item => item.classList.toggle("is-drop-target", item === after));
  });

  container.addEventListener("drop", event => {
    if (!state.draggedMaintenanceCardId) return;
    event.preventDefault();
    maintenanceCards().forEach(item => item.classList.remove("is-drop-target", "is-dragging"));
    state.draggedMaintenanceCardId = null;
    saveMaintenanceCardOrder();
  });
}

function homeCards() {
  return Array.from(document.querySelectorAll("#homeDashboardCards > .reorderable-card"));
}

function savedHomeCardOrder() {
  try {
    const parsed = JSON.parse(localStorage.getItem(HOME_CARD_ORDER_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function applyHomeCardOrder() {
  const container = document.getElementById("homeDashboardCards");
  if (!container) return;
  const cards = homeCards();
  const byId = new Map(cards.map(card => [card.dataset.cardId, card]));
  const seen = new Set();
  savedHomeCardOrder().forEach(id => {
    const card = byId.get(id);
    if (!card) return;
    container.appendChild(card);
    seen.add(id);
  });
  cards.forEach(card => {
    if (!seen.has(card.dataset.cardId)) container.appendChild(card);
  });
}

function saveHomeCardOrder() {
  const order = homeCards().map(card => card.dataset.cardId).filter(Boolean);
  localStorage.setItem(HOME_CARD_ORDER_KEY, JSON.stringify(order));
}

function homeCardAfterPointer(container, y, draggedCard) {
  return Array.from(container.querySelectorAll(".reorderable-card:not(.is-dragging)")).find(card => {
    if (card === draggedCard) return false;
    const box = card.getBoundingClientRect();
    return y < box.top + box.height / 2;
  }) || null;
}

function wireHomeCardReordering() {
  const container = document.getElementById("homeDashboardCards");
  if (!container || container.dataset.reorderWired === "true") return;
  container.dataset.reorderWired = "true";
  applyHomeCardOrder();

  homeCards().forEach(card => {
    const head = card.querySelector(".section-head");
    if (!head || head.querySelector(".drag-grip")) return;
    const grip = el("span", "drag-grip", "::");
    grip.draggable = true;
    grip.title = "Drag to reorder";
    grip.setAttribute("aria-label", "Drag to reorder");
    grip.addEventListener("dragstart", event => {
      state.draggedHomeCardId = card.dataset.cardId;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.cardId || "");
    });
    grip.addEventListener("dragend", () => {
      state.draggedHomeCardId = null;
      card.classList.remove("is-dragging");
      homeCards().forEach(item => item.classList.remove("is-drop-target"));
      saveHomeCardOrder();
    });
    head.prepend(grip);
  });

  container.addEventListener("dragover", event => {
    const draggedId = state.draggedHomeCardId;
    if (!draggedId) return;
    const draggedCard = homeCards().find(card => card.dataset.cardId === draggedId);
    if (!draggedCard) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const after = homeCardAfterPointer(container, event.clientY, draggedCard);
    if (after) container.insertBefore(draggedCard, after);
    else container.appendChild(draggedCard);
    homeCards().forEach(item => item.classList.toggle("is-drop-target", item === after));
  });

  container.addEventListener("drop", event => {
    if (!state.draggedHomeCardId) return;
    event.preventDefault();
    homeCards().forEach(item => item.classList.remove("is-drop-target", "is-dragging"));
    state.draggedHomeCardId = null;
    saveHomeCardOrder();
  });
}

function leftRailCards() {
  return Array.from(document.querySelectorAll("#leftRailCards > .left-card"));
}

function savedLeftRailOrder() {
  try {
    const parsed = JSON.parse(localStorage.getItem(LEFT_RAIL_CARD_ORDER_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function applyLeftRailCardOrder() {
  const container = document.getElementById("leftRailCards");
  if (!container) return;
  const cards = leftRailCards();
  const byId = new Map(cards.map(card => [card.dataset.cardId, card]));
  const seen = new Set();
  savedLeftRailOrder().forEach(id => {
    const card = byId.get(id);
    if (!card) return;
    container.appendChild(card);
    seen.add(id);
  });
  cards.forEach(card => {
    if (!seen.has(card.dataset.cardId)) container.appendChild(card);
  });
}

function saveLeftRailCardOrder() {
  const order = leftRailCards().map(card => card.dataset.cardId).filter(Boolean);
  localStorage.setItem(LEFT_RAIL_CARD_ORDER_KEY, JSON.stringify(order));
}

function leftRailCardAfterPointer(container, y, draggedCard) {
  return Array.from(container.querySelectorAll(".left-card:not(.is-dragging)")).find(card => {
    if (card === draggedCard) return false;
    const box = card.getBoundingClientRect();
    return y < box.top + box.height / 2;
  }) || null;
}

function wireLeftRailCardReordering() {
  const container = document.getElementById("leftRailCards");
  if (!container || container.dataset.reorderWired === "true") return;
  container.dataset.reorderWired = "true";
  applyLeftRailCardOrder();

  leftRailCards().forEach(card => {
    const head = card.querySelector(".section-head");
    if (!head || head.querySelector(".drag-grip")) return;
    const grip = el("span", "drag-grip", "::");
    grip.draggable = true;
    grip.title = "Drag to reorder";
    grip.setAttribute("aria-label", "Drag to reorder");
    grip.addEventListener("dragstart", event => {
      state.draggedLeftRailCardId = card.dataset.cardId;
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.cardId || "");
    });
    grip.addEventListener("dragend", () => {
      state.draggedLeftRailCardId = null;
      card.classList.remove("is-dragging");
      leftRailCards().forEach(item => item.classList.remove("is-drop-target"));
      saveLeftRailCardOrder();
    });
    head.prepend(grip);
  });

  container.addEventListener("dragover", event => {
    const draggedId = state.draggedLeftRailCardId;
    if (!draggedId) return;
    const draggedCard = leftRailCards().find(card => card.dataset.cardId === draggedId);
    if (!draggedCard) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const after = leftRailCardAfterPointer(container, event.clientY, draggedCard);
    if (after) container.insertBefore(draggedCard, after);
    else container.appendChild(draggedCard);
    leftRailCards().forEach(item => item.classList.toggle("is-drop-target", item === after));
  });

  container.addEventListener("drop", event => {
    if (!state.draggedLeftRailCardId) return;
    event.preventDefault();
    leftRailCards().forEach(item => item.classList.remove("is-drop-target", "is-dragging"));
    state.draggedLeftRailCardId = null;
    saveLeftRailCardOrder();
  });
}

function saveConversationId(id) {
  state.conversationId = id;
  if (id) localStorage.setItem("archivist.conversationId", id);
}

function saveAdminConversationId(id) {
  state.adminConversationId = id;
  if (id) localStorage.setItem("archivist.adminConversationId", id);
}

function appendField(container, label, value) {
  const row = el("div", "field-row");
  row.appendChild(el("span", "field-label", label));
  row.appendChild(el("span", "field-value", value || ""));
  container.appendChild(row);
}

function appendLinkedText(container, text) {
  const value = text || "";
  const pattern = /([A-Za-z]:\\[^\n\r<>|?*"]+?\.[A-Za-z0-9]{1,10})(?=$|[\s),.;:!?])/g;
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(value)) !== null) {
    if (match.index > lastIndex) {
      container.appendChild(document.createTextNode(value.slice(lastIndex, match.index)));
    }
    const rawPath = match[1].trim().replace(/[),.;]+$/, "");
    const trailing = match[1].slice(rawPath.length);
    const link = el("a", "text-link", rawPath);
    link.href = `/api/file?path=${encodeURIComponent(rawPath)}`;
    link.target = "_blank";
    container.appendChild(link);
    if (trailing) container.appendChild(document.createTextNode(trailing));
    lastIndex = match.index + match[1].length;
  }
  if (lastIndex < value.length) {
    container.appendChild(document.createTextNode(value.slice(lastIndex)));
  }
}

function scrollMessages() {
  const messages = document.getElementById("messages");
  messages.scrollTop = messages.scrollHeight;
}

function renderMessages(items) {
  const container = document.getElementById("messages");
  container.innerHTML = "";
  if (!items.length) {
    const empty = el("div", "empty-state");
    empty.textContent = "The thread is quiet.";
    container.appendChild(empty);
    return;
  }
  items.forEach(item => {
    const msg = el("article", `message ${item.role === "user" ? "from-user" : "from-archivist"}`);
    const meta = el("div", "message-meta", item.role === "user" ? "Chuk" : "Archivist");
    const body = el("div", "message-body");
    appendLinkedText(body, item.content || "");
    msg.appendChild(meta);
    msg.appendChild(body);
    container.appendChild(msg);
  });
  scrollMessages();
}

function appendMessage(role, content, thinking) {
  const container = document.getElementById("messages");
  const empty = container.querySelector(".empty-state");
  if (empty) empty.remove();
  const msg = el("article", `message ${role === "user" ? "from-user" : "from-archivist"}`);
  msg.appendChild(el("div", "message-meta", role === "user" ? "Chuk" : "Archivist"));
  const body = el("div", "message-body");
  if (thinking && role === "assistant") {
    const thinkingEl = el("details", "thinking-block");
    thinkingEl.appendChild(el("summary", "thinking-label", "🤔 Thinking"));
    thinkingEl.appendChild(el("div", "thinking-content", thinking));
    body.appendChild(thinkingEl);
  }
  appendLinkedText(body, content || "");
  msg.appendChild(body);
  container.appendChild(msg);
  scrollMessages();
}

async function loadConversations() {
  const data = await getJSON("/api/conversations");
  const list = document.getElementById("conversationList");
  list.innerHTML = "";
  if (!data.conversations.length) {
    list.appendChild(el("div", "compact-output", "No threads yet."));
    return;
  }
  data.conversations.forEach(item => {
    const button = el("button", "thread-button", "");
    if (item.id === state.conversationId) button.classList.add("active");
    const title = el("span", "thread-title", item.title || "Untitled thread");
    const meta = el("span", "thread-meta", `${item.message_count || 0} msgs - ${shortTime(item.updated_ts)}`);
    button.appendChild(title);
    button.appendChild(meta);
    button.onclick = async () => {
      saveConversationId(item.id);
      await loadConversation(item.id);
      await loadConversations();
    };
    list.appendChild(button);
  });
}

async function loadConversation(id) {
  if (!id) {
    state.cowriterHistory = [];
    renderMessages([]);
    return;
  }
  const data = await getJSON(`/api/conversations/${encodeURIComponent(id)}`);
  const messages = data.messages || [];
  state.cowriterHistory = messages
    .filter(item => ["user", "assistant"].includes(item.role))
    .map(item => ({role: item.role, content: item.content || ""}));
  renderMessages(messages);
}

async function newConversation() {
  const data = await postURL("/api/conversations");
  saveConversationId(data.conversation_id);
  state.cowriterHistory = [];
  renderMessages([]);
  await loadConversations();
}

function cowriterPayload(instruction = "") {
  return {
    document: document.getElementById("cowriterEditor").value,
    instruction,
    conversation_id: state.conversationId,
    chat_history: state.cowriterHistory
  };
}

function setCowriterStatus(text) {
  document.getElementById("cowriterStatus").textContent = text || "Ready";
}

function setCowriterPaths(data = {}) {
  if (data.current_file) state.cowriterCurrentFile = data.current_file;
  if (data.autosave_file) state.cowriterAutosaveFile = data.autosave_file;
  const pathStatus = document.getElementById("cowriterPathStatus");
  const current = state.cowriterCurrentFile || "not loaded";
  const autosave = state.cowriterAutosaveFile || "not loaded";
  pathStatus.textContent = `Current: ${current} | Autosave: ${autosave}`;
}

async function loadCowriterDocument() {
  try {
    const data = await getJSON("/api/cowriter/document");
    document.getElementById("cowriterEditor").value = data.content || "";
    setCowriterPaths(data);
    setCowriterStatus(`Loaded ${data.current_file || "current draft"}`);
    await loadCowriterTimeline();
  } catch (err) {
    setCowriterStatus(`${err.message}. Co-writer routes will be available after the next server restart.`);
  }
}

async function saveCowriterDocument(autosave = false) {
  const content = document.getElementById("cowriterEditor").value;
  const data = await postJSON(`/api/cowriter/document?autosave=${autosave ? "true" : "false"}`, {content});
  setCowriterStatus(`${autosave ? "Autosaved" : "Saved"} ${data.saved_to || ""}`);
  await loadCowriterTimeline().catch(() => {});
  return data;
}

async function saveCowriterVersion() {
  const content = document.getElementById("cowriterEditor").value;
  const data = await postJSON("/api/cowriter/version", {content});
  setCowriterStatus(`Version saved ${data.saved_to || ""}`);
  if (data.current_file) setCowriterPaths(data);
  await loadCowriterTimeline().catch(() => {});
}

function renderFileTimeline(items = []) {
  const list = document.getElementById("fileTimeline");
  if (!list) return;
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(el("div", "compact-output", "No Co-writer file history yet."));
    return;
  }
  items.forEach(item => {
    const row = el("article", `timeline-item timeline-${item.kind || "file"}`);
    const marker = el("div", "timeline-marker");
    const body = el("div", "timeline-body");
    body.appendChild(el("div", "timeline-kind", item.label || item.kind || "File"));
    body.appendChild(el("div", "timeline-title", item.name || "(unnamed)"));
    body.appendChild(el("div", "timeline-meta", `${shortTime(item.modified_ts)} - ${formatBytes(item.size_bytes)}`));
    body.appendChild(el("div", "timeline-path", item.path || ""));

    const actions = el("div", "timeline-actions");
    const loadBtn = el("button", null, "Load");
    loadBtn.type = "button";
    loadBtn.onclick = () => loadCowriterFromPath(item.path);
    actions.appendChild(loadBtn);
    if (item.path) {
      const openLink = el("a", "button-link", "Open");
      openLink.href = `/api/file?path=${encodeURIComponent(item.path)}`;
      openLink.target = "_blank";
      actions.appendChild(openLink);
    }
    body.appendChild(actions);
    row.appendChild(marker);
    row.appendChild(body);
    list.appendChild(row);
  });
}

async function loadCowriterTimeline() {
  try {
    const data = await getJSON("/api/cowriter/timeline");
    setCowriterPaths(data);
    renderFileTimeline(data.items || []);
  } catch (err) {
    const list = document.getElementById("fileTimeline");
    if (list) {
      list.innerHTML = "";
      list.appendChild(el("div", "compact-output", "File timeline will be available after the next server restart."));
    }
  }
}

async function loadCowriterFromPath(path) {
  if (!path) return;
  setStatus("Loading document");
  try {
    const data = await postJSON("/api/cowriter/load", {path});
    document.getElementById("cowriterEditor").value = data.content || "";
    setCowriterPaths(data);
    setCowriterStatus(`Loaded ${data.source_file || path}`);
    appendMessage("assistant", `Loaded into Co-writer:\n${data.source_file || path}`);
    await loadCowriterTimeline();
    setStatus("Idle");
  } catch (err) {
    appendMessage("assistant", err.message);
    setCowriterStatus(err.message);
    setStatus("Idle");
  }
}

function readDroppedTextFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read dropped file"));
    reader.readAsText(file);
  });
}

function isBrowserReadableTextFile(file) {
  const lower = (file.name || "").toLowerCase();
  return file.type.startsWith("text/") || [".md", ".markdown", ".txt", ".csv", ".json", ".xml", ".log", ".py", ".js", ".ts", ".css", ".html", ".htm", ".yaml", ".yml"].some(ext => lower.endsWith(ext));
}

async function importCowriterDroppedFile(file) {
  setStatus("Loading document");
  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/cowriter/import-upload", {method: "POST", body: form});
    const data = await readJSON(res);
    document.getElementById("cowriterEditor").value = data.content || "";
    setCowriterPaths(data);
    setCowriterStatus(`Loaded ${data.source_name || file.name}`);
    await loadCowriterTimeline();
    setStatus("Idle");
  } catch (err) {
    try {
      if (!isBrowserReadableTextFile(file)) throw new Error("This document needs the Co-writer import route after the next server restart");
      const content = await readDroppedTextFile(file);
      document.getElementById("cowriterEditor").value = content;
      setCowriterStatus(`Loaded local text drop ${file.name}. Save draft when ready.`);
    } catch (fallbackErr) {
      appendMessage("assistant", `${err.message}. ${fallbackErr.message}`);
      setCowriterStatus(err.message);
    }
    setStatus("Idle");
  }
}

function selectedEditorText() {
  const editor = document.getElementById("cowriterEditor");
  return editor.value.slice(editor.selectionStart, editor.selectionEnd);
}

function replaceEditorSelection(text) {
  const editor = document.getElementById("cowriterEditor");
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  editor.setRangeText(text, start, end, "select");
  editor.focus();
}

async function askCowriter(kind = "ask") {
  const input = document.getElementById("chatInput");
  const instruction = input.value.trim();
  const documentText = document.getElementById("cowriterEditor").value;
  const selected = selectedEditorText();
  const helpMode = document.getElementById("writingHelpMode")?.value || "voice";
  const helpModeLabels = {
    voice: "voice and continuity",
    structure: "structure and shape",
    memoir: "memoir and lived detail",
    scene: "scene work and sensory flow",
    technical: "technical clarity",
    tighten: "tighten and refine",
    brainstorm: "brainstorm and expand"
  };
  const endpointByKind = {
    ask: "/api/cowriter/ask",
    edit: "/api/cowriter/edit-selection",
    selection: "/api/cowriter/ask",
    help: "/api/cowriter/help-write",
    preview: "/api/cowriter/preview-draft"
  };
  const endpoint = endpointByKind[kind] || endpointByKind.ask;
  const label = kind === "edit" ? "Edit selection" : kind === "selection" ? "Ask selection" : kind === "help" ? "Help write" : kind === "preview" ? "Preview draft" : "Ask";
  if (kind === "edit" && !selected) {
    appendMessage("assistant", "Select text in the draft first.");
    return;
  }
  if (kind === "selection" && !selected) {
    appendMessage("assistant", "Select text in the draft first.");
    return;
  }
  const effectiveInstruction = kind === "help"
    ? `[Writing help mode: ${helpModeLabels[helpMode] || helpMode}]\n${instruction || "Help me continue and improve this draft while preserving the Archivist voice."}`
    : instruction;

  appendMessage("user", `${label}: ${effectiveInstruction || "(no extra instruction)"}`);
  input.value = "";
  setStatus("Thinking");
  setCowriterStatus("Thinking with the draft...");
  try {
    const payload = {
      document: documentText,
      instruction: effectiveInstruction,
      selected_text: selected,
      conversation_id: state.conversationId,
      chat_history: state.cowriterHistory
    };
    const data = await postJSON(endpoint, payload);
    const answer = data.answer || data.replacement || data.revised_document || "";
    if (data.conversation_id) saveConversationId(data.conversation_id);
    state.cowriterHistory.push({role: "user", content: `${label}: ${effectiveInstruction}`});
    state.cowriterHistory.push({role: "assistant", content: answer});
    appendMessage("assistant", data.replacement ? `Replacement preview:\n\n${data.replacement}` : data.revised_document ? `Preview draft saved.\n\n${data.revised_document}` : answer);
    if (kind === "edit" && data.replacement) {
      const confirmed = window.confirm("Apply this replacement to the selected text?");
      if (confirmed) {
        replaceEditorSelection(data.replacement);
        await saveCowriterDocument(true);
      }
    }
    if (kind === "preview" && data.revised_document) {
      const confirmed = window.confirm("Replace the working draft with this preview?");
      if (confirmed) {
        document.getElementById("cowriterEditor").value = data.revised_document;
        await saveCowriterDocument(false);
      }
    }
    speakEffect();
    await loadConversations();
    await loadMemories();
    setCowriterStatus(data.model_task ? `Ready | route: ${data.model_task}` : "Ready");
    setStatus("Idle");
  } catch (err) {
    appendMessage("assistant", err.message);
    setCowriterStatus(err.message);
    setStatus("Idle");
  }
}

function renderMemoryStatus(status) {
  const total = status?.total || 0;
  const byStatus = status?.by_status || {};
  const parts = Object.entries(byStatus).map(([key, val]) => `${key}: ${val}`);
  document.getElementById("memoryStatus").textContent = parts.length ? `Memory: ${total} (${parts.join(", ")})` : `Memory: ${total}`;
}

function renderMemoryList(memories) {
  const panel = document.getElementById("memoryPanel");
  panel.innerHTML = "";
  if (!memories.length) {
    panel.appendChild(el("div", "compact-output", "No memories yet."));
    return;
  }
  memories.forEach(memory => {
    const item = el("div", "memory-item");
    item.appendChild(el("div", "memory-tag", `${memory.status || "MEMORY"} / ${memory.kind || "observed"}`));
    item.appendChild(el("div", "memory-content", memory.content || ""));
    panel.appendChild(item);
  });
}

async function loadMemories() {
  const data = await getJSON("/api/memories?limit=20");
  renderMemoryStatus(data.status);
  renderMemoryList(data.memories || []);
}

function dashboardLine(title, body) {
  const item = el("div", "dashboard-line");
  item.appendChild(el("div", "dashboard-line-title", title));
  item.appendChild(el("div", "dashboard-line-body", body || ""));
  return item;
}

function renderDashboard(data = {}) {
  const greeting = data.greeting || {};
  const weather = data.weather || {};
  const calendar = data.calendar || {};
  const activity = data.archive_activity || {};
  const run = activity.latest_index_run || {};
  const actions = activity.recent_actions || [];

  const weatherPanel = document.getElementById("weatherPanel");
  weatherPanel.innerHTML = "";
  weatherPanel.appendChild(dashboardLine("Status", weather.summary || "Weather provider not connected yet."));
  weatherPanel.appendChild(dashboardLine("Provider", weather.provider_label || (weather.provider === "open_meteo" ? "Open-Meteo" : "Not connected")));
  weatherPanel.appendChild(dashboardLine("Location", weather.resolved_location || weather.location || "Not configured"));
  if (weather.temperature_f !== undefined && weather.temperature_f !== null) {
    weatherPanel.appendChild(dashboardLine("Current", `${Math.round(Number(weather.temperature_f))}°F${weather.feels_like_f !== undefined && weather.feels_like_f !== null ? `, feels ${Math.round(Number(weather.feels_like_f))}°F` : ""}`));
  }
  const atmosphere = [];
  if (weather.humidity_percent !== undefined && weather.humidity_percent !== null) atmosphere.push(`humidity ${weather.humidity_percent}%`);
  if (weather.wind_mph !== undefined && weather.wind_mph !== null) atmosphere.push(`wind ${Math.round(Number(weather.wind_mph))} mph`);
  if (weather.precipitation_in !== undefined && weather.precipitation_in !== null) atmosphere.push(`precip ${weather.precipitation_in} in`);
  if (atmosphere.length) weatherPanel.appendChild(dashboardLine("Air", atmosphere.join(" | ")));
  const daily = weather.daily || {};
  if ((daily.time || []).length) {
    const forecast = (daily.time || []).slice(0, 3).map((day, index) => {
      const high = daily.temperature_2m_max?.[index];
      const low = daily.temperature_2m_min?.[index];
      const code = daily.weather_code?.[index];
      const rain = daily.precipitation_probability_max?.[index];
      const bits = [];
      if (high !== undefined && low !== undefined) bits.push(`${Math.round(Number(low))}-${Math.round(Number(high))}°F`);
      if (rain !== undefined) bits.push(`${rain}% precip`);
      return `${day}: ${bits.join(", ")}${code !== undefined ? ` (code ${code})` : ""}`;
    }).join("\n");
    weatherPanel.appendChild(dashboardLine("Forecast", forecast));
  }
  weatherPanel.appendChild(dashboardLine("Sync", weather.sync_enabled ? `Connected${weather.updated_ts ? ` | ${shortTime(weather.updated_ts)}` : ""}` : "Awaiting weather location."));
  const weatherForm = el("div", "weather-config");
  const weatherInput = document.createElement("input");
  weatherInput.type = "search";
  weatherInput.placeholder = "City, State or place";
  weatherInput.value = weather.location || "";
  weatherInput.setAttribute("aria-label", "Weather location");
  const saveWeatherBtn = el("button", null, "Save");
  saveWeatherBtn.type = "button";
  saveWeatherBtn.onclick = () => saveWeatherSettings(weatherInput.value.trim());
  const refreshWeatherBtn = el("button", null, "Update now");
  refreshWeatherBtn.type = "button";
  refreshWeatherBtn.disabled = !weather.sync_enabled;
  refreshWeatherBtn.onclick = refreshWeather;
  const clearWeatherBtn = el("button", null, "Clear");
  clearWeatherBtn.type = "button";
  clearWeatherBtn.onclick = () => saveWeatherSettings("");
  weatherForm.appendChild(weatherInput);
  weatherForm.appendChild(saveWeatherBtn);
  weatherForm.appendChild(refreshWeatherBtn);
  weatherForm.appendChild(clearWeatherBtn);
  weatherPanel.appendChild(weatherForm);

  const calendarPanel = document.getElementById("calendarPanel");
  calendarPanel.innerHTML = "";
  calendarPanel.appendChild(dashboardLine("Status", calendar.summary || "Calendar provider not connected yet."));
  calendarPanel.appendChild(dashboardLine("Providers", (calendar.providers || []).join(", ") || "Google/iCloud sync not connected."));
  calendarPanel.appendChild(dashboardLine("Today", "No synced events yet."));

  const greetingPanel = document.getElementById("greetingPanel");
  greetingPanel.innerHTML = "";
  greetingPanel.appendChild(dashboardLine("Hello", greeting.summary || "Archive context is ready."));
  (greeting.recommendations || []).slice(0, 3).forEach((item, index) => {
    greetingPanel.appendChild(dashboardLine(index === 0 ? "Recommendations" : "Next", item));
  });

  const activityPanel = document.getElementById("archiveActivityPanel");
  activityPanel.innerHTML = "";
  activityPanel.appendChild(dashboardLine("Index", run.status ? `${run.status}: ${formatCount(run.indexed_count)} indexed, ${formatCount(run.duplicate_count)} duplicates, ${formatCount(run.failed_count)} failed` : "No persistent index run snapshot yet."));
  if (!actions.length) {
    activityPanel.appendChild(dashboardLine("Recent actions", "No file-operator actions logged yet."));
  } else {
    actions.slice(0, 5).forEach(action => {
      activityPanel.appendChild(dashboardLine(`#${action.id} ${action.tool}`, `${action.status}${action.error ? `: ${action.error}` : ""}`));
    });
  }
}

async function saveWeatherSettings(location) {
  try {
    const clean = String(location || "").trim();
    await postJSON("/api/weather/settings", {
      provider: clean ? "open_meteo" : null,
      location: clean || null,
      sync_enabled: Boolean(clean)
    });
    await loadDashboard();
  } catch (err) {
    appendMessage("assistant", `Weather setup issue: ${err.message}`);
  }
}

async function refreshWeather() {
  try {
    await postURL("/api/weather/refresh");
    await loadDashboard();
  } catch (err) {
    appendMessage("assistant", `Weather refresh issue: ${err.message}`);
  }
}

async function loadDashboard() {
  try {
    const data = await getJSON("/api/dashboard");
    renderDashboard(data);
  } catch (err) {
    ["weatherPanel", "calendarPanel", "greetingPanel", "archiveActivityPanel"].forEach(id => {
      const panel = document.getElementById(id);
      if (!panel) return;
      panel.innerHTML = "";
      panel.appendChild(dashboardLine("Waiting", "Dashboard context will be available after the next server restart."));
    });
  }
}

/* ── Drive Inbox ────────────────────────────────────────── */

let driveSelectedPaths = new Set();
let driveCurrentPath = null;
let driveBreadcrumbs = [];
let drivePollTimer = null;

async function loadDrives() {
  try {
    const data = await getJSON("/api/drives");
    renderDriveList(data.drives || []);
  } catch (err) {
    const list = document.getElementById("driveList");
    if (list) {
      list.innerHTML = "";
      list.appendChild(el("div", "compact-output", `Drive scan: ${err.message}`));
    }
  }
}

function driveIcon(drive) {
  if (drive.transport === "usb") return "&#128427;";
  if (drive.transport === "sata") return "&#128190;";
  return "&#128190;";
}

function formatSize(size) {
  if (!size) return "";
  const match = size.match(/^([\d.]+)([A-Z])/);
  if (!match) return size;
  return `${Number(match[1]).toFixed(1)} ${match[2]}B`;
}

function renderDriveList(drives) {
  const list = document.getElementById("driveList");
  const status = document.getElementById("driveListStatus");
  if (!list) return;
  list.innerHTML = "";

  const mountable = drives.filter(d => d.mountable && d.fstype);
  const mounted = drives.filter(d => d.mounted);

  if (!mountable.length && !mounted.length) {
    if (status) status.textContent = "No external drives detected.";
    const empty = el("div", "compact-output", "Plug in a USB drive or external disk to see it here.");
    list.appendChild(empty);
    return;
  }

  if (status) status.textContent = `${mounted.length} mounted, ${mountable.length} available`;

  mounted.forEach(drive => {
    const item = el("div", "drive-item");
    item.innerHTML = `
      <span class="drive-item-icon">${driveIcon(drive)}</span>
      <div class="drive-item-info">
        <div class="drive-item-name">${drive.label || drive.device} <span style="color:var(--accent-mint)">&#9679;</span></div>
        <div class="drive-item-meta">${formatSize(drive.size)} ${drive.fstype} &middot; mounted at ${drive.mountpoint}</div>
      </div>
      <div class="drive-item-actions">
        <button class="drive-browse-btn" data-path="${drive.mountpoint}">Browse</button>
        <button class="drive-unmount-btn" data-mountpoint="${drive.mountpoint}">Unmount</button>
      </div>`;
    item.querySelector(".drive-browse-btn")?.addEventListener("click", () => browseDrive(drive.mountpoint));
    item.querySelector(".drive-unmount-btn")?.addEventListener("click", () => unmountDrive(drive.mountpoint));
    list.appendChild(item);
  });

  mountable.forEach(drive => {
    const item = el("div", "drive-item");
    item.innerHTML = `
      <span class="drive-item-icon">${driveIcon(drive)}</span>
      <div class="drive-item-info">
        <div class="drive-item-name">${drive.label || drive.device}</div>
        <div class="drive-item-meta">${formatSize(drive.size)} ${drive.fstype} &middot; not mounted</div>
      </div>
      <div class="drive-item-actions">
        <button class="drive-mount-btn" data-device="${drive.device}">Mount</button>
      </div>`;
    item.querySelector(".drive-mount-btn")?.addEventListener("click", () => mountDrive(drive.device));
    list.appendChild(item);
  });
}

async function mountDrive(device) {
  try {
    const data = await postJSON("/api/drives/mount", {path: device});
    if (data.ok) {
      await loadDrives();
      browseDrive(data.mountpoint);
    } else {
      alert(`Mount failed: ${data.error}`);
    }
  } catch (err) {
    alert(`Mount error: ${err.message}`);
  }
}

async function unmountDrive(mountpoint) {
  try {
    const data = await postJSON("/api/drives/unmount", {path: mountpoint});
    if (data.ok) {
      driveCurrentPath = null;
      driveBreadcrumbs = [];
      driveSelectedPaths.clear();
      document.getElementById("driveBrowser").style.display = "none";
      await loadDrives();
    } else {
      alert(`Unmount failed: ${data.error}`);
    }
  } catch (err) {
    alert(`Unmount error: ${err.message}`);
  }
}

function formatFileTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString([], {month: "short", day: "numeric"});
}

async function browseDrive(path) {
  driveCurrentPath = path;
  driveSelectedPaths.clear();
  document.getElementById("driveSelectedCount").textContent = "0 selected";
  document.getElementById("driveImportBtn").disabled = true;
  const browser = document.getElementById("driveBrowser");
  browser.style.display = "block";
  const fileList = document.getElementById("driveFileList");
  fileList.innerHTML = `<div class="drive-browser-loading">Loading...</div>`;

  try {
    const data = await postJSON("/api/drives/browse", {path});
    renderDriveBrowser(data);
  } catch (err) {
    fileList.innerHTML = "";
    fileList.appendChild(el("div", "compact-output", `Browse error: ${err.message}`));
  }
}

function renderDriveBrowser(data) {
  const breadcrumb = document.getElementById("driveBreadcrumb");
  const fileList = document.getElementById("driveFileList");
  fileList.innerHTML = "";

  // breadcrumbs
  breadcrumb.innerHTML = "";
  const parts = data.path.replace(/^\/+/, "").split("/");
  let accumulated = "";
  const resetBtn = el("button", null, "Drives");
  resetBtn.type = "button";
  resetBtn.onclick = () => { driveCurrentPath = null; document.getElementById("driveBrowser").style.display = "none"; };
  breadcrumb.appendChild(resetBtn);

  parts.forEach((part, index) => {
    accumulated += "/" + part;
    const crumb = el("button", null, part || "/");
    crumb.type = "button";
    crumb.onclick = () => browseDrive(accumulated);
    breadcrumb.appendChild(crumb);
  });

  if (data.parent && data.parent !== data.path) {
    const upBtn = el("button", null, "..");
    upBtn.type = "button";
    upBtn.onclick = () => browseDrive(data.parent);
    breadcrumb.appendChild(upBtn);
  }

  // entries
  const entries = data.entries || [];
  if (!entries.length) {
    fileList.appendChild(el("div", "compact-output", "Empty directory."));
    return;
  }

  entries.forEach(entry => {
    const row = el("div", "drive-file-row");
    if (entry.is_dir) row.classList.add("is-dir");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = driveSelectedPaths.has(entry.path);
    cb.addEventListener("change", () => {
      if (cb.checked) driveSelectedPaths.add(entry.path);
      else driveSelectedPaths.delete(entry.path);
      updateDriveSelection();
    });
    row.appendChild(cb);

    const icon = el("span", "file-icon", entry.is_dir ? "&#128193;" : "&#128196;");
    row.appendChild(icon);

    const nameSpan = el("span", "file-name", entry.name);
    row.appendChild(nameSpan);

    if (!entry.is_dir) {
      const meta = el("span", "file-meta", `${formatSizeText(entry.size)} &middot; ${formatFileTime(entry.modified_ts)}`);
      row.appendChild(meta);
    }

    if (entry.is_dir) {
      row.addEventListener("dblclick", () => browseDrive(entry.path));
    }

    fileList.appendChild(row);
  });
}

function formatSizeText(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unitIdx = 0;
  while (size >= 1024 && unitIdx < units.length - 1) {
    size /= 1024;
    unitIdx += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unitIdx]}`;
}

function updateDriveSelection() {
  const count = driveSelectedPaths.size;
  document.getElementById("driveSelectedCount").textContent = `${count} selected`;
  document.getElementById("driveImportBtn").disabled = count === 0;
}

async function driveImportSelected() {
  const paths = Array.from(driveSelectedPaths);
  if (!paths.length) return;
  const btn = document.getElementById("driveImportBtn");
  const status = document.getElementById("driveImportStatus");
  btn.disabled = true;
  btn.textContent = "Importing...";
  status.textContent = "";
  try {
    const data = await postJSON("/api/drives/import-multi", {paths});
    if (data.ok) {
      const ok = data.results.filter(r => r.ok).length;
      const fail = data.results.filter(r => !r.ok).length;
      status.textContent = `Imported ${ok} items to archive inbox${fail ? `, ${fail} failed` : ""}.`;
      status.style.color = "var(--accent-mint)";
      driveSelectedPaths.clear();
      updateDriveSelection();
      // refresh the current browse view
      if (driveCurrentPath) await browseDrive(driveCurrentPath);
      else await loadDrives();
    } else {
      status.textContent = `Import failed: ${data.error || "unknown error"}`;
      status.style.color = "var(--danger)";
    }
  } catch (err) {
    status.textContent = `Import error: ${err.message}`;
    status.style.color = "var(--danger)";
  }
  btn.disabled = false;
  btn.textContent = "Add to Archive";
}

function startDrivePoll() {
  if (drivePollTimer) return;
  loadDrives();
  drivePollTimer = window.setInterval(loadDrives, 10000);
}

function stopDrivePoll() {
  if (drivePollTimer) {
    clearInterval(drivePollTimer);
    drivePollTimer = null;
  }
}

/* ── End Drive Inbox ────────────────────────────────────── */

function enginePlanText(data = {}) {
  if (data.structured_summary) return data.structured_summary;
  const plan = data.structured_plan || {};
  if (!plan.schema) return "";
  const lines = [
    "Structured engine plan:",
    `- Schema: ${plan.schema}`,
    `- Workspace: ${plan.workspace || "unknown"}`,
    `- Intent: ${plan.intent || "unknown"} | risk: ${plan.risk_level || "unknown"}`
  ];
  if ((plan.likely_files || []).length) lines.push(`- Likely files: ${plan.likely_files.slice(0, 6).join(", ")}`);
  if ((plan.suggested_tools || []).length) lines.push(`- Suggested tools: ${plan.suggested_tools.slice(0, 6).map(tool => tool.id || tool.label).join(", ")}`);
  if (plan.handoff) lines.push(`- Handoff: ${plan.handoff}`);
  return lines.join("\n");
}

function adminPlaceholderReply(prompt) {
  const text = String(prompt || "").toLowerCase();
  if (text.includes("archive controls") || text.includes("restart") || text.includes("stop server") || text.includes("free gpu") || text.includes("gpu")) {
    return "Archive Controls are for runtime care: inspect server/index/model state, free Ollama GPU memory, and request a guarded app restart or stop. Host reboot belongs behind a stronger confirmation layer later.";
  }
  if (text.includes("easy connect") || text.includes("pair") || text.includes("pairing")) {
    return "Easy Connect is the right safety pattern: each machine generates a short-lived code, each machine enters the other machine's code, and only then should remote setup become available. I staged the controls below so the transport can grow from a mutual handshake instead of blind trust.";
  }
  if (text.includes("installer") || text.includes("hardware") || text.includes("profile") || text.includes("models")) {
    return "Installer profile will inspect CPU, RAM, GPU hints, Ollama availability, and installed models, then choose model routes that fit the hardware. It should keep network roots chat-ignored unless a worker can index local-to-data.";
  }
  if (text.includes("network") || text.includes("share")) {
    return "Network-share setup will run as an audited admin workflow: discover target, classify it chat-ignored by default, dry-run reachability, stage credentials handling outside chat logs, then ask for confirmation before saving any source policy.";
  }
  if (text.includes("patch")) {
    return "Patch flow placeholder: future Admin will review the generated patch, summarize touched files and risks, run checks, then require explicit confirmation before applying it to the Archivist app.";
  }
  if (text.includes("worker")) {
    return "Worker-node setup placeholder: future Admin will inspect remote hardware, prefer local-to-data indexing, install a small worker when approved, and sync metadata back without making network roots chat-aware too early.";
  }
  if (text.includes("health") || text.includes("maintenance")) {
    return "Maintenance health check placeholder: future Admin will inspect index state, embeddings, source policies, recent failures, duplicate queues, and model routing, then stage safe repair actions.";
  }
  return "Intelligent Admin placeholder staged this request. The intended pattern is: understand intent, gather evidence, dry-run changes, create an audited action or patch, then ask for confirmation before touching the system.";
}

function renderAdminChat() {
  const log = document.getElementById("adminChatLog");
  if (!log) return;
  if (!state.adminHistory.length) {
    state.adminHistory = [
      {
        role: "admin",
        content: "Intelligent Admin is the built-in ArchivistOS administrator: it plans maintenance, stages patches, runs verified admin tools, and leaves audit trails. Its agentic layer can use the internal Fauxdex Engine or another workflow adapter, but the user-facing surface stays Admin."
      }
    ];
  }
  log.innerHTML = "";
  state.adminHistory.forEach(item => {
    const msg = el("article", `admin-message ${item.role === "user" ? "from-user" : "from-admin"}`);
    msg.appendChild(el("div", "message-meta", item.role === "user" ? "Chuk" : "Intelligent Admin"));
    msg.appendChild(el("div", "message-body", item.content || ""));
    log.appendChild(msg);
  });
  log.scrollTop = log.scrollHeight;
}

function addAdminNote(content) {
  state.adminHistory.push({role: "admin", content: content || ""});
  renderAdminChat();
}

async function sendAdminEngine(prompt, mode = "plan") {
  const clean = String(prompt || "").trim();
  if (!clean) return;
  const runMode = mode === "run";
  state.adminHistory.push({role: "user", content: `${runMode ? "Run" : "Plan"}: ${clean}`});
  renderAdminChat();
  setStatus(runMode ? "Running" : "Thinking");
  try {
    const data = await postJSON(runMode ? "/api/admin/intelligent-admin/run" : "/api/admin/intelligent-admin", {
      task: clean,
      conversation_id: state.adminConversationId,
      mode: "admin"
    });
    if (data.conversation_id) saveAdminConversationId(data.conversation_id);
    const actionIds = [data.operator_action?.id, data.admin_action_id].filter((id, index, ids) => id && ids.indexOf(id) === index);
    const actionNote = actionIds.length ? `\n\nAdmin audit ${actionIds.map(id => `#${id}`).join(", ")} logged for Intelligent Admin.` : "";
    const structured = enginePlanText(data);
    const structureNote = structured ? `\n\n${structured}` : "";
    state.adminSuggestedTools = data.structured_plan?.suggested_tools || [];
    renderAdminSuggestedTools();
    state.adminHistory.push({role: "admin", content: `${data.answer || ""}${structureNote}${actionNote}`});
    await loadConversations();
    await loadAdminDevelopmentTasks().catch(() => {});
    setStatus("Idle");
  } catch (err) {
    const fallback = /404|not found/i.test(err.message || "")
      ? `${adminPlaceholderReply(clean)}\n\nRestart the server when convenient to enable Intelligent Admin ${runMode ? "run actions" : "planning"}.`
      : err.message;
    state.adminHistory.push({role: "admin", content: fallback});
    setStatus("Idle");
  }
  renderAdminChat();
  renderAdminSuggestedTools();
}

function renderAdminEngineTools() {
  const panel = document.getElementById("adminEngineToolList");
  if (!panel) return;
  panel.innerHTML = "";
  const tools = state.adminEngineTools || [];
  if (!tools.length) {
    panel.textContent = "No engine tools reported yet.";
    return;
  }
  tools.forEach(tool => {
    const row = el("article", "admin-tool-row");
    const detail = el("div");
    detail.appendChild(el("div", "admin-tool-title", tool.label || tool.id || "Engine tool"));
    detail.appendChild(el("div", "admin-tool-meta", `${tool.mode || "run"} | ${tool.safety || "safe"} | ${tool.summary || ""}`));
    const button = el("button", "", tool.mode === "plan" ? "Plan" : "Run");
    button.type = "button";
    button.addEventListener("click", () => sendAdminEngine(tool.prompt || tool.label || tool.id || "", tool.mode || "run"));
    row.appendChild(detail);
    row.appendChild(button);
    panel.appendChild(row);
  });
}

function renderAdminSuggestedTools() {
  const panel = document.getElementById("adminSuggestedTools");
  if (!panel) return;
  panel.innerHTML = "";
  const tools = state.adminSuggestedTools || [];
  if (!tools.length) {
    panel.classList.add("is-empty");
    return;
  }
  panel.classList.remove("is-empty");
  panel.appendChild(el("div", "admin-suggested-label", "Engine suggestions"));
  tools.slice(0, 6).forEach(tool => {
    const button = el("button", "", tool.label || tool.id || "Run");
    button.type = "button";
    button.title = tool.id || tool.prompt || "";
    button.addEventListener("click", () => sendAdminEngine(tool.prompt || tool.label || tool.id || "", tool.mode || "run"));
    panel.appendChild(button);
  });
}

async function loadAdminEngineTools() {
  try {
    const data = await getJSON("/api/admin/intelligent-admin/tools");
    state.adminEngineTools = data.tools || [];
  } catch (err) {
    state.adminEngineTools = [];
    const panel = document.getElementById("adminEngineToolList");
    if (panel) panel.textContent = `${err.message}. Restart the server to load the Intelligent Admin tool catalog.`;
    return;
  }
  renderAdminEngineTools();
}

function developmentTaskMeta(task = {}) {
  const parts = [`#${task.id}`, task.status || "queued", task.priority || "medium"];
  if (task.last_action_id) parts.push(`audit #${task.last_action_id}`);
  return parts.join(" | ");
}

function renderAdminDevelopmentTasks(data = {}) {
  const tasks = data.tasks || state.adminDevelopmentTasks || [];
  state.adminDevelopmentTasks = tasks;
  const list = document.getElementById("adminDevTaskList");
  const stateNode = document.getElementById("adminDevTaskState");
  if (stateNode) {
    const summary = data.summary || {};
    const byStatus = summary.by_status || {};
    const active = byStatus.active || 0;
    const queued = byStatus.queued || 0;
    stateNode.textContent = `${formatCount(summary.total || tasks.length)} total | ${formatCount(active + queued)} open`;
  }
  if (!list) return;
  list.innerHTML = "";
  if (!tasks.length) {
    list.appendChild(el("div", "compact-output", "No development tasks yet. Seed the queue to create the next Admin build steps."));
    return;
  }
  tasks.forEach(task => {
    const card = el("article", `admin-dev-task-card status-${task.status || "queued"}`);
    const head = el("div", "admin-dev-task-head");
    const title = el("div");
    title.appendChild(el("div", "admin-dev-task-title", task.title || "Untitled task"));
    title.appendChild(el("div", "admin-dev-task-meta", developmentTaskMeta(task)));
    head.appendChild(title);
    const actions = el("div", "admin-dev-task-actions");
    const workBtn = el("button", "", "Work");
    workBtn.type = "button";
    workBtn.onclick = () => sendAdminEngine(`next development task: ${task.title}`, "run");
    const patchBtn = el("button", "", "Patch");
    patchBtn.type = "button";
    patchBtn.onclick = () => sendAdminEngine(`stage patch proposal for ${task.title}`, "run");
    const checksBtn = el("button", "", "Checks");
    checksBtn.type = "button";
    checksBtn.onclick = () => sendAdminEngine("run admin verification checks", "run");
    actions.appendChild(workBtn);
    actions.appendChild(patchBtn);
    actions.appendChild(checksBtn);
    if (task.status !== "done") {
      const doneBtn = el("button", "", "Done");
      doneBtn.type = "button";
      doneBtn.onclick = () => updateAdminDevelopmentTask(task.id, {status: "done"});
      actions.appendChild(doneBtn);
    }
    head.appendChild(actions);
    card.appendChild(head);
    if (task.description) card.appendChild(el("div", "admin-dev-task-body", task.description));
    const tools = task.recommended_tools || [];
    if (tools.length) {
      const chips = el("div", "admin-dev-task-chips");
      tools.slice(0, 5).forEach(tool => chips.appendChild(el("span", "memory-tag", tool)));
      card.appendChild(chips);
    }
    const verification = task.verification || [];
    if (verification.length) card.appendChild(el("div", "admin-dev-task-note", `Verify: ${verification.slice(0, 2).join(" | ")}`));
    list.appendChild(card);
  });
}

async function loadAdminDevelopmentTasks() {
  const stateNode = document.getElementById("adminDevTaskState");
  if (stateNode) stateNode.textContent = "loading";
  try {
    renderAdminDevelopmentTasks(await getJSON("/api/admin/development-tasks?limit=40"));
  } catch (err) {
    if (stateNode) stateNode.textContent = "pending restart";
    const list = document.getElementById("adminDevTaskList");
    if (list) list.textContent = `${err.message}. Restart the server to load the Admin development queue.`;
  }
}

async function seedAdminDevelopmentTasks() {
  const stateNode = document.getElementById("adminDevTaskState");
  if (stateNode) stateNode.textContent = "seeding";
  try {
    const data = await postJSON("/api/admin/development-tasks/seed", {});
    await loadAdminDevelopmentTasks();
    addAdminNote(`Development queue seeded. Created ${formatCount((data.created || []).length)} task(s); ${formatCount((data.skipped || []).length)} already present.`);
  } catch (err) {
    addAdminNote(err.message);
  }
}

async function createAdminDevelopmentTask() {
  const input = document.getElementById("adminDevTaskTitleInput");
  const priority = document.getElementById("adminDevTaskPriorityInput")?.value || "medium";
  const title = input?.value.trim() || "";
  if (!title) return;
  try {
    const data = await postJSON("/api/admin/development-tasks", {title, priority, status: "queued"});
    if (input) input.value = "";
    await loadAdminDevelopmentTasks();
    addAdminNote(`Development task #${data.task?.id || "?"} queued: ${data.task?.title || title}`);
  } catch (err) {
    addAdminNote(err.message);
  }
}

async function updateAdminDevelopmentTask(taskId, payload = {}) {
  try {
    const data = await postJSON(`/api/admin/development-tasks/${taskId}`, payload);
    await loadAdminDevelopmentTasks();
    addAdminNote(`Development task #${taskId} updated to ${data.task?.status || payload.status || "updated"}.`);
  } catch (err) {
    addAdminNote(err.message);
  }
}

async function runNextAdminDevelopmentTask() {
  try {
    const data = await getJSON("/api/admin/development-tasks/next");
    if (data.task) {
      await sendAdminEngine(`next development task: ${data.task.title}`, "run");
    } else {
      addAdminNote("No active development task yet. Seed the queue first.");
    }
  } catch (err) {
    addAdminNote(err.message);
  }
}

function pctValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

function pctLabel(value) {
  return Number.isFinite(Number(value)) ? `${Math.round(Number(value))}%` : "--%";
}

function setHostRing(id, value) {
  const ring = document.getElementById(id);
  if (!ring) return;
  const radius = Number(ring.getAttribute("r") || 0);
  const circumference = 2 * Math.PI * radius;
  const pct = pctValue(value);
  ring.style.strokeDasharray = `${(circumference * pct) / 100} ${circumference}`;
}

function setHostSettingsInputs(settings = {}) {
  const pairs = [
    ["hostCpuThreshold", settings.cpu_threshold_percent],
    ["hostGpuThreshold", settings.gpu_threshold_percent],
    ["hostRamThreshold", settings.ram_threshold_percent],
    ["hostVramThreshold", settings.vram_threshold_percent],
    ["hostTempThreshold", settings.temperature_threshold_c],
    ["hostPollSeconds", settings.poll_seconds],
    ["hostQuietStart", settings.quiet_start || ""],
    ["hostQuietEnd", settings.quiet_end || ""]
  ];
  pairs.forEach(([id, value]) => {
    const input = document.getElementById(id);
    if (input && value !== undefined && value !== null) input.value = value;
  });
  const schedule = document.getElementById("hostScheduleEnabled");
  if (schedule) schedule.checked = settings.schedule_enabled !== false;
}

function hostSettingsPayload() {
  return {
    cpu_threshold_percent: Number(document.getElementById("hostCpuThreshold")?.value || 85),
    gpu_threshold_percent: Number(document.getElementById("hostGpuThreshold")?.value || 85),
    ram_threshold_percent: Number(document.getElementById("hostRamThreshold")?.value || 85),
    vram_threshold_percent: Number(document.getElementById("hostVramThreshold")?.value || 85),
    temperature_threshold_c: Number(document.getElementById("hostTempThreshold")?.value || 82),
    poll_seconds: Number(document.getElementById("hostPollSeconds")?.value || 10),
    schedule_enabled: Boolean(document.getElementById("hostScheduleEnabled")?.checked),
    quiet_start: document.getElementById("hostQuietStart")?.value || "",
    quiet_end: document.getElementById("hostQuietEnd")?.value || ""
  };
}

function renderHostRingLegend(rows) {
  const panel = document.getElementById("hostRingLegend");
  if (!panel) return;
  panel.innerHTML = "";
  rows.forEach(row => {
    const item = el("div", `host-ring-item ${row.warn ? "is-warn" : ""}`);
    item.appendChild(el("span", `host-ring-swatch ${row.key}`));
    item.appendChild(el("span", "host-ring-label", row.label));
    item.appendChild(el("span", "host-ring-value", row.value));
    panel.appendChild(item);
  });
}

function renderTemperatureGauges(data = {}) {
}

function renderHostStats(data = {}) {
  state.hostStats = data;
  const settings = data.settings || {};
  const cpu = data.cpu || {};
  const memory = data.memory || {};
  const gpu = data.gpu || {};
  const stateNode = document.getElementById("hostStatsState");
  const summary = document.getElementById("hostStatsSummary");
  const primary = document.getElementById("hostStatsPrimary");
  const temperature = (data.temperatures || [])[0];
  const tempValue = temperature?.temperature_c;
  if (stateNode) stateNode.textContent = (data.thresholds && Object.values(data.thresholds).some(Boolean)) ? "host threshold" : "host normal";
  if (summary) {
    const host = data.host || {};
    const gpuName = (gpu.cards || [])[0]?.name || (gpu.available ? "GPU detected" : "GPU unavailable");
    const tempText = tempValue !== undefined && tempValue !== null ? ` | GPU ${Math.round(Number(tempValue))}C` : "";
    summary.textContent = `${data.summary || "Host telemetry loaded."} ${host.hostname || "Host"} | ${host.cpu_count || "?"} CPU threads | ${gpuName}${tempText}`;
  }
  if (primary) primary.textContent = tempValue !== undefined && tempValue !== null ? `${Math.round(Number(tempValue))}C` : "--C";
  setHostRing("hostCpuRing", cpu.usage_percent);
  setHostRing("hostGpuRing", gpu.usage_percent);
  setHostRing("hostVramRing", gpu.vram_percent);
  setHostRing("hostRamRing", memory.usage_percent);
  renderHostRingLegend([
    {key: "cpu", label: "CPU usage", value: pctLabel(cpu.usage_percent), warn: cpu.threshold},
    {key: "gpu", label: "GPU usage", value: pctLabel(gpu.usage_percent), warn: data.thresholds?.gpu},
    {key: "vram", label: "GPU VRAM", value: gpu.vram_total_mb ? `${pctLabel(gpu.vram_percent)} (${formatBytes(Number(gpu.vram_used_mb || 0) * 1024 * 1024)} / ${formatBytes(Number(gpu.vram_total_mb || 0) * 1024 * 1024)})` : "--", warn: data.thresholds?.vram},
    {key: "ram", label: "System RAM", value: memory.total_bytes ? `${pctLabel(memory.usage_percent)} (${formatBytes(memory.used_bytes)} / ${formatBytes(memory.total_bytes)})` : "--", warn: memory.threshold}
  ]);
  renderTemperatureGauges(data);
  setHostSettingsInputs(settings);
  scheduleHostStatsPoll(settings);
}

function scheduleHostStatsPoll(settings = {}) {
  if (state.hostStatsTimer) {
    clearTimeout(state.hostStatsTimer);
    state.hostStatsTimer = null;
  }
  if (state.activeView !== "maintenance" || settings.schedule_enabled === false) return;
  const seconds = Math.max(5, Math.min(300, Number(settings.poll_seconds || 10)));
  state.hostStatsTimer = window.setTimeout(() => loadHostStats({quiet: true}), seconds * 1000);
}

async function loadHostStats(options = {}) {
  const stateNode = document.getElementById("hostStatsState");
  if (stateNode && !options.quiet) stateNode.textContent = "loading";
  try {
    renderHostStats(await getJSON("/api/admin/host-stats"));
  } catch (err) {
    if (stateNode) stateNode.textContent = "pending restart";
    const summary = document.getElementById("hostStatsSummary");
    if (summary) summary.textContent = `${err.message}. Host stats routes will be available after the next server restart.`;
  }
}

async function saveHostStatsSettings() {
  const stateNode = document.getElementById("hostStatsState");
  if (stateNode) stateNode.textContent = "saving";
  try {
    renderHostStats(await postJSON("/api/admin/host-stats/settings", hostSettingsPayload()));
  } catch (err) {
    if (stateNode) stateNode.textContent = "error";
    const summary = document.getElementById("hostStatsSummary");
    if (summary) summary.textContent = err.message;
  }
}

function summarizeRunningModels(ollama = {}) {
  const models = ollama.running_models || [];
  if (!models.length) return ollama.available ? "No running Ollama models." : (ollama.error || "Ollama unavailable.");
  return models.join(", ");
}

function summarizeGpu(gpu = {}) {
  if (!gpu.available) return gpu.error || "GPU telemetry unavailable.";
  const cards = gpu.gpus || [];
  if (!cards.length) return "No NVIDIA GPU rows returned.";
  return cards.map(item => {
    const used = item.memory_used_mb !== null && item.memory_used_mb !== undefined ? formatBytes(Number(item.memory_used_mb) * 1024 * 1024) : "?";
    const total = item.memory_total_mb !== null && item.memory_total_mb !== undefined ? formatBytes(Number(item.memory_total_mb) * 1024 * 1024) : "?";
    const util = item.utilization_percent !== null && item.utilization_percent !== undefined ? `${item.utilization_percent}%` : "?";
    const power = item.power_watts !== null && item.power_watts !== undefined ? `${item.power_watts} W` : "?";
    return `${item.name}: ${used} / ${total}, ${util}, ${power}`;
  }).join(" | ");
}

function renderAdminControl(data = {}) {
  state.adminControl = data;
  const stateNode = document.getElementById("adminControlState");
  const statusNode = document.getElementById("adminControlStatus");
  const detail = document.getElementById("adminControlDetail");
  if (!stateNode || !statusNode || !detail) return;
  const server = data.server || {};
  const archive = data.archive || {};
  const index = archive.index || {};
  const embeddings = archive.embeddings || {};
  const preDedupe = archive.pre_dedupe || {};
  stateNode.textContent = archive.busy ? "busy" : "ready";
  const uptime = server.uptime_seconds !== undefined ? formatDuration(server.uptime_seconds) : "unknown";
  statusNode.textContent = data.summary || `PID ${server.pid || "?"} | uptime ${uptime} | ${server.launcher_managed ? "launcher restart enabled" : "manual restart mode"}`;
  detail.innerHTML = "";
  detail.appendChild(dashboardLine("Server", `${server.host || "0.0.0.0"}:${server.port || "8000"} | PID ${server.pid || "?"}`));
  detail.appendChild(dashboardLine("Launcher", server.launcher_managed ? "Start_Archivist.bat will auto-restart app requests." : "Restart request will stop this server unless launched by Start_Archivist.bat."));
  detail.appendChild(dashboardLine("Index", index.running || index.building_queue ? `${index.run_status || "running"} | ${formatCount(index.total_seen || 0)} seen` : `${index.run_status || "idle"} | ${formatCount(index.indexed_count || 0)} indexed`));
  detail.appendChild(dashboardLine("Embeddings", embeddings.running ? `running | ${formatCount(embeddings.processed || 0)} / ${formatCount(embeddings.total || 0)}` : "idle"));
  detail.appendChild(dashboardLine("Pre-dedupe", preDedupe.running ? `running | ${formatCount(preDedupe.total_seen || 0)} seen` : "idle"));
  detail.appendChild(dashboardLine("Ollama", summarizeRunningModels(data.ollama || {})));
  detail.appendChild(dashboardLine("GPU", summarizeGpu(data.gpu || {})));
  detail.appendChild(dashboardLine("Archive root", archive.archive_root || "unknown"));
}

async function loadAdminControlStatus() {
  const statusNode = document.getElementById("adminControlStatus");
  if (statusNode) statusNode.textContent = "Loading archive runtime status...";
  try {
    renderAdminControl(await getJSON("/api/admin/archive-control"));
  } catch (err) {
    renderAdminControl({summary: `${err.message}. Archive control routes will be available after the next server restart.`});
  }
}

async function freeAdminGpu() {
  const confirmed = window.confirm("Ask Ollama to stop currently loaded models and free GPU memory?");
  if (!confirmed) return;
  const statusNode = document.getElementById("adminControlStatus");
  if (statusNode) statusNode.textContent = "Requesting Ollama model unload...";
  try {
    const data = await postJSON("/api/admin/archive-control/free-gpu", {});
    await loadAdminControlStatus();
    state.adminHistory.push({role: "admin", content: data.summary || "GPU release requested."});
    renderAdminChat();
  } catch (err) {
    renderAdminControl({...state.adminControl, summary: err.message});
  }
}

async function requestAdminServerAction(action) {
  const actionLabel = action === "restart" ? "restart the Archivist server" : "stop the Archivist server";
  const confirmed = confirmWithNumber(`This will ${actionLabel}. Active browser requests may disconnect.`);
  if (!confirmed) return;
  try {
    const data = await postJSON(`/api/admin/archive-control/${action}`, {force: false});
    renderAdminControl({...state.adminControl, summary: data.summary || `${actionLabel} requested.`});
    state.adminHistory.push({role: "admin", content: data.summary || `${actionLabel} requested.`});
    renderAdminChat();
  } catch (err) {
    renderAdminControl({...state.adminControl, summary: err.message});
  }
}

function renderAdminConnect(data = {}) {
  state.adminConnect = data;
  const stateNode = document.getElementById("adminConnectState");
  const codeNode = document.getElementById("adminLocalPairCode");
  const statusNode = document.getElementById("adminConnectStatus");
  const copyButton = document.getElementById("adminCopyPairCodeBtn");
  if (stateNode) stateNode.textContent = data.status || "idle";
  if (codeNode) codeNode.textContent = data.local_code || "------";
  if (copyButton) copyButton.disabled = !data.local_code;
  if (statusNode) {
    const remote = data.remote_code_received ? " Remote code received." : "";
    const timer = data.seconds_remaining ? ` Expires in ${Math.ceil(data.seconds_remaining / 60)} min.` : "";
    statusNode.textContent = `${data.summary || "Easy Connect is idle."}${remote}${timer}`;
  }
}

async function loadAdminConnect() {
  try {
    renderAdminConnect(await getJSON("/api/admin/easy-connect"));
  } catch (err) {
    renderAdminConnect({status: "pending restart", summary: "Easy Connect routes will be available after the next server restart."});
  }
}

async function startAdminConnect() {
  try {
    const data = await postJSON("/api/admin/easy-connect/start", {});
    renderAdminConnect(data);
    addAdminNote("Easy Connect code generated. Waiting for the other machine's code.");
  } catch (err) {
    renderAdminConnect({status: "error", summary: err.message});
  }
}

async function verifyAdminConnect() {
  const input = document.getElementById("adminRemoteCodeInput");
  const remoteCode = input?.value.trim() || "";
  if (!remoteCode) {
    renderAdminConnect({...state.adminConnect, summary: "Enter the other machine's six-digit code first."});
    return;
  }
  try {
    const data = await postJSON("/api/admin/easy-connect/verify", {remote_code: remoteCode});
    if (input) input.value = "";
    renderAdminConnect(data);
    addAdminNote("Remote pair code accepted on this machine. The other machine still needs this machine's code before transport opens.");
  } catch (err) {
    renderAdminConnect({...state.adminConnect, status: "verify failed", summary: err.message});
  }
}

async function resetAdminConnect() {
  try {
    renderAdminConnect(await postJSON("/api/admin/easy-connect/reset", {}));
  } catch (err) {
    renderAdminConnect({status: "error", summary: err.message});
  }
}

function installerPlanText(data = state.installerProfile || {}) {
  const hardware = data.hardware || {};
  const lines = [
    `Installer profile: ${data.profile_label || data.profile || "unknown"}`,
    `Host: ${hardware.hostname || "unknown"}`,
    `Platform: ${hardware.platform || "unknown"}`,
    `CPU threads: ${hardware.cpu_count || "unknown"}`,
    `Memory: ${hardware.memory_gb || "unknown"} GB`,
    `GPUs: ${(hardware.gpus || []).map(gpu => `${gpu.name} (${Math.round((gpu.memory_mb || 0) / 1024)} GB)`).join(", ") || "none detected"}`,
    "",
    "Recommended model routes:"
  ];
  (data.recommended_env || []).forEach(route => {
    lines.push(`${route.env}=${route.model} # ${route.reason || ""}`);
  });
  if ((data.pull_commands || []).length) {
    lines.push("", "Pull missing models:");
    data.pull_commands.forEach(command => lines.push(command));
  }
  if ((data.installer_plan || []).length) {
    lines.push("", "Installer guardrails:");
    data.installer_plan.forEach(step => lines.push(`- ${step}`));
  }
  return lines.join("\n");
}

function renderInstallerProfile(data = {}) {
  state.installerProfile = data;
  const panel = document.getElementById("adminInstallerProfile");
  const status = document.getElementById("adminHardwareStatus");
  if (!panel || !status) return;
  panel.innerHTML = "";
  if (!data.profile) {
    status.textContent = data.summary || "Hardware profile not detected.";
    return;
  }
  const hardware = data.hardware || {};
  const gpuText = (hardware.gpus || []).map(gpu => `${gpu.name} (${Math.round((gpu.memory_mb || 0) / 1024)} GB)`).join(", ") || "none detected";
  status.textContent = `${data.profile_label || data.profile} | ${hardware.memory_gb || "?"} GB RAM | ${hardware.cpu_count || "?"} CPU threads | GPU: ${gpuText}`;
  panel.appendChild(dashboardLine("Ollama", hardware.ollama_available ? `${formatCount((hardware.installed_ollama_models || []).length)} models installed` : "Ollama not detected on PATH"));
  if ((data.missing_models || []).length) {
    panel.appendChild(dashboardLine("Missing pulls", data.missing_models.join(", ")));
  } else {
    panel.appendChild(dashboardLine("Missing pulls", "Recommended models appear installed or Ollama is unavailable to inspect."));
  }
  const routes = el("div", "installer-env-list");
  (data.recommended_env || []).forEach(route => {
    const item = el("div", "installer-env-item");
    item.appendChild(el("div", "installer-env-name", route.env || "ENV"));
    item.appendChild(el("div", "installer-env-model", route.model || "not configured"));
    item.appendChild(el("div", "installer-env-reason", route.reason || ""));
    routes.appendChild(item);
  });
  panel.appendChild(routes);
}

async function loadInstallerProfile() {
  const status = document.getElementById("adminHardwareStatus");
  if (status) status.textContent = "Detecting hardware...";
  try {
    const data = await getJSON("/api/admin/installer-profile");
    renderInstallerProfile(data);
    addAdminNote(`Installer hardware profile detected: ${data.profile_label || data.profile}.`);
  } catch (err) {
    renderInstallerProfile({summary: `${err.message}. Hardware detection will be available after the next server restart.`});
  }
}

function renderFaceReviewMetrics(overview = {}) {
  const metrics = document.getElementById("faceReviewMetrics");
  if (!metrics) return;
  const counts = overview.counts || {};
  metrics.innerHTML = "";
  [
    ["People", counts.people || 0],
    ["Faces", counts.face_observations || 0],
    ["Links", counts.person_face_links || 0],
    ["Events", counts.timeline_events || 0],
    ["Evidence", counts.timeline_event_evidence || 0],
    ["Event people", counts.timeline_event_people || 0]
  ].forEach(([label, value]) => {
    const item = el("div", "face-review-metric");
    item.appendChild(el("div", "face-review-metric-value", formatCount(value)));
    item.appendChild(el("div", "face-review-metric-label", label));
    metrics.appendChild(item);
  });
}

function renderFaceDetectorStatus(status = {}) {
  state.faceDetectorStatus = status;
  const node = document.getElementById("faceDetectorStatus");
  if (!node) return;
  const opencv = status.opencv || {};
  const ffmpeg = status.ffmpeg || {};
  const settings = status.settings || {};
  const detectorText = opencv.available ? "Image detector ready" : `Image detector unavailable: ${opencv.error || "not configured"}`;
  const videoText = ffmpeg.ready ? "video sampling ready" : "video sampling needs FFmpeg";
  const imageAuto = settings.auto_scan_images ? "image ingestion on" : "image ingestion off";
  const videoAuto = settings.auto_scan_videos ? "video ingestion on" : "video ingestion off";
  node.textContent = `${detectorText}; ${videoText}; ${imageAuto}; ${videoAuto}.`;
}

function personLabel(person = {}) {
  const aliases = (person.aliases || []).length ? ` (${person.aliases.join(", ")})` : "";
  return `${person.display_name || "Unnamed"}${aliases}`;
}

function renderFacePeople(people = []) {
  state.timelinePeople = people;
  const list = document.getElementById("facePersonList");
  const select = document.getElementById("faceLinkPersonSelect");
  if (select) {
    select.innerHTML = "";
    if (!people.length) {
      const option = el("option", null, "No people yet");
      option.value = "";
      select.appendChild(option);
    } else {
      people.forEach(person => {
        const option = el("option", null, personLabel(person));
        option.value = person.id;
        select.appendChild(option);
      });
    }
  }
  if (!list) return;
  list.innerHTML = "";
  if (!people.length) {
    list.appendChild(el("div", "compact-output", "No people tagged yet. Add a person to begin identity review."));
    return;
  }
  people.forEach(person => {
    const item = el("article", "face-person-item");
    item.appendChild(el("div", "face-person-name", personLabel(person)));
    item.appendChild(el("div", "face-person-meta", `${person.sensitivity || "normal"} | ${formatCount(person.face_link_count || 0)} face link(s) | ${formatCount(person.event_count || 0)} event(s)`));
    if (person.notes) item.appendChild(el("div", "face-person-notes", person.notes));
    list.appendChild(item);
  });
}

function renderFaceObservations(observations = []) {
  state.faceObservations = observations;
  const list = document.getElementById("faceObservationList");
  const selected = observations.find(item => Number(item.id) === Number(state.selectedFaceObservationId));
  const status = document.getElementById("selectedFaceStatus");
  if (status) {
    status.textContent = selected
      ? `Selected face #${selected.id}${selected.cluster_id ? ` | cluster ${selected.cluster_id}` : ""}`
      : "No face observation selected.";
  }
  if (!list) return;
  list.innerHTML = "";
  if (!observations.length) {
    list.appendChild(el("div", "compact-output", "No face observations yet. Detect faces from a file or add a manual observation."));
    return;
  }
  observations.forEach(face => {
    const item = el("article", `face-observation-item ${Number(face.id) === Number(state.selectedFaceObservationId) ? "selected" : ""}`);
    if (face.crop_path) {
      const img = el("img", "face-observation-crop");
      img.src = `/api/preview?path=${encodeURIComponent(face.crop_path)}`;
      img.alt = `Face observation ${face.id}`;
      item.appendChild(img);
    }
    const body = el("div", "face-observation-body");
    body.appendChild(el("div", "face-observation-title", `Face #${face.id} | ${face.media_type || "image"}`));
    const when = face.frame_seconds !== null && face.frame_seconds !== undefined ? ` @ ${formatDuration(Number(face.frame_seconds || 0))}` : "";
    const source = face.source ? ` | ${face.source}` : "";
    body.appendChild(el("div", "face-observation-meta", `${face.cluster_id || "no cluster"}${when}${source}`));
    body.appendChild(el("div", "face-observation-path", face.path || ""));
    const selectBtn = el("button", null, "Select");
    selectBtn.type = "button";
    selectBtn.onclick = () => {
      state.selectedFaceObservationId = face.id;
      renderFaceObservations(state.faceObservations);
    };
    body.appendChild(selectBtn);
    item.appendChild(body);
    list.appendChild(item);
  });
}

function renderFaceReview({overview = state.timelineOverview, people = state.timelinePeople, faces = state.faceObservations, detector = state.faceDetectorStatus, error = ""} = {}) {
  state.timelineOverview = overview || {};
  const stateNode = document.getElementById("faceReviewState");
  const statusNode = document.getElementById("faceReviewStatus");
  if (stateNode) stateNode.textContent = error ? "needs restart" : "ready";
  if (statusNode) {
    statusNode.textContent = error || "People, detected faces, manual observations, and review links are ready.";
  }
  renderFaceDetectorStatus(detector || {});
  renderFaceReviewMetrics(state.timelineOverview || {});
  renderFacePeople(people || []);
  renderFaceObservations(faces || []);
}

async function loadFaceReview() {
  const statusNode = document.getElementById("faceReviewStatus");
  if (statusNode) statusNode.textContent = "Loading timeline and face review state...";
  try {
    const [overview, people, faces, detector] = await Promise.all([
      getJSON("/api/timeline/overview"),
      getJSON("/api/timeline/people"),
      getJSON("/api/timeline/faces"),
      getJSON("/api/timeline/faces/detector-status")
    ]);
    renderFaceReview({
      overview,
      people: people.people || [],
      faces: faces.face_observations || [],
      detector
    });
  } catch (err) {
    renderFaceReview({error: `${err.message}. Timeline routes will be available after the next server restart.`});
  }
}

async function createFacePerson() {
  const nameInput = document.getElementById("facePersonNameInput");
  const aliasesInput = document.getElementById("facePersonAliasesInput");
  const sensitivityInput = document.getElementById("facePersonSensitivityInput");
  const notesInput = document.getElementById("facePersonNotesInput");
  const displayName = nameInput?.value.trim() || "";
  if (!displayName) {
    renderFaceReview({...state, error: "Enter a person name first."});
    return;
  }
  const payload = {
    display_name: displayName,
    aliases: splitList(aliasesInput?.value || ""),
    sensitivity: sensitivityInput?.value || "normal",
    notes: notesInput?.value || ""
  };
  await postJSON("/api/timeline/people", payload);
  if (nameInput) nameInput.value = "";
  if (aliasesInput) aliasesInput.value = "";
  if (notesInput) notesInput.value = "";
  await loadFaceReview();
}

async function createFaceObservation() {
  const pathInput = document.getElementById("faceObservationPathInput");
  const fileIdInput = document.getElementById("faceObservationFileIdInput");
  const clusterInput = document.getElementById("faceObservationClusterInput");
  const mediaTypeInput = document.getElementById("faceObservationMediaTypeInput");
  const frameInput = document.getElementById("faceObservationFrameInput");
  const path = pathInput?.value.trim() || "";
  if (!path) {
    const statusNode = document.getElementById("faceReviewStatus");
    if (statusNode) statusNode.textContent = "Add an image/video path for the observation first.";
    return;
  }
  const payload = {
    path,
    media_type: mediaTypeInput?.value || "image",
    cluster_id: clusterInput?.value.trim() || null,
    file_id: fileIdInput?.value ? Number(fileIdInput.value) : null,
    frame_seconds: frameInput?.value ? Number(frameInput.value) : null
  };
  const face = await postJSON("/api/timeline/faces", payload);
  state.selectedFaceObservationId = face.id;
  if (pathInput) pathInput.value = "";
  if (fileIdInput) fileIdInput.value = "";
  if (clusterInput) clusterInput.value = "";
  if (frameInput) frameInput.value = "";
  await loadFaceReview();
}

function faceDetectionPayload() {
  const path = document.getElementById("faceObservationPathInput")?.value.trim() || "";
  const fileId = document.getElementById("faceObservationFileIdInput")?.value;
  if (fileId) return {file_id: Number(fileId)};
  if (path) return {path};
  throw new Error("Enter an indexed file id or image/video path first.");
}

async function detectFaceFile() {
  const statusNode = document.getElementById("faceReviewStatus");
  try {
    const payload = faceDetectionPayload();
    if (statusNode) statusNode.textContent = "Detecting faces and refreshing auto tags...";
    const data = await postJSON("/api/timeline/faces/detect", payload);
    const scan = data.face_scan || {};
    const tags = (data.auto_tags || {}).tags || [];
    const detail = scan.error ? ` ${scan.error}` : "";
    if (statusNode) statusNode.textContent = `Detected ${formatCount(scan.face_count || 0)} face(s). Auto tags: ${tags.join(", ") || "none"}.${detail}`;
    await loadFaceReview();
  } catch (err) {
    if (statusNode) statusNode.textContent = err.message;
  }
}

async function detectObjectFile() {
  const statusNode = document.getElementById("faceReviewStatus");
  try {
    const payload = faceDetectionPayload();
    payload.update_index = true;
    if (statusNode) statusNode.textContent = "Running local vision object tagging...";
    const data = await postJSON("/api/media/vision/analyze", payload);
    const analysis = data.analysis || {};
    const objects = (analysis.objects || []).slice(0, 12).join(", ");
    const caption = analysis.caption ? `${analysis.caption} ` : "";
    const tags = data.tags?.tags || [];
    if (statusNode) statusNode.textContent = `${caption}Objects: ${objects || "none"}. Tags: ${tags.slice(0, 10).join(", ") || "none"}.`;
    await loadFaceReview();
  } catch (err) {
    if (statusNode) statusNode.textContent = err.message;
  }
}

async function backfillFaces() {
  const statusNode = document.getElementById("faceReviewStatus");
  try {
    if (statusNode) statusNode.textContent = "Scanning recent indexed images and videos for faces...";
    const data = await postJSON("/api/timeline/faces/backfill", {limit: 40, include_video: true, force: false});
    if (statusNode) statusNode.textContent = `Scanned ${formatCount(data.scanned || 0)} media file(s); found ${formatCount(data.face_count || 0)} face(s).`;
    await loadFaceReview();
  } catch (err) {
    if (statusNode) statusNode.textContent = err.message;
  }
}

async function linkSelectedFacePerson() {
  const personSelect = document.getElementById("faceLinkPersonSelect");
  const statusSelect = document.getElementById("faceLinkStatusSelect");
  const confidenceInput = document.getElementById("faceLinkConfidenceInput");
  const statusNode = document.getElementById("faceReviewStatus");
  const faceId = state.selectedFaceObservationId;
  const personId = personSelect?.value ? Number(personSelect.value) : 0;
  if (!faceId || !personId) {
    if (statusNode) statusNode.textContent = "Select a face observation and a person before linking.";
    return;
  }
  await postJSON("/api/timeline/face-links", {
    person_id: personId,
    face_observation_id: Number(faceId),
    status: statusSelect?.value || "confirmed",
    confidence: confidenceInput?.value ? Number(confidenceInput.value) : 1,
    source: "user"
  });
  if (statusNode) statusNode.textContent = `Linked face #${faceId} to selected person.`;
  await loadFaceReview();
}

function videoInputPayload() {
  const raw = document.getElementById("videoPathInput")?.value.trim() || "";
  if (!raw) throw new Error("Paste/drop a video path or enter an indexed file id first.");
  if (/^\d+$/.test(raw)) return {file_id: Number(raw)};
  return {path: raw};
}

function splitList(value) {
  return String(value || "")
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
}

function segmentTimeLabel(segment = {}) {
  const start = formatDuration(Number(segment.start_seconds || 0));
  const end = segment.end_seconds !== null && segment.end_seconds !== undefined ? formatDuration(Number(segment.end_seconds || 0)) : "";
  return end ? `${start} - ${end}` : start;
}

function renderVideoFfmpegStatus(data = {}) {
  state.videoFfmpeg = data;
  const stateNode = document.getElementById("videoFfmpegState");
  const statusNode = document.getElementById("videoStatus");
  if (stateNode) stateNode.textContent = data.ready ? "ffmpeg ready" : "ffmpeg missing";
  if (statusNode && !state.videoContext) {
    statusNode.textContent = data.ready
      ? "FFmpeg and ffprobe are available. Load a video path or indexed file id."
      : (data.hint || "FFmpeg/ffprobe are not available yet.");
  }
}

function renderMediaAiStatus({vision = null, transcription = null} = {}) {
  if (vision) state.visionStatus = vision;
  if (transcription) state.transcriptionStatus = transcription;
  const stateNode = document.getElementById("videoFfmpegState");
  if (!stateNode || !state.videoFfmpeg) return;
  const bits = [state.videoFfmpeg.ready ? "ffmpeg ready" : "ffmpeg missing"];
  bits.push(state.visionStatus?.ready ? "vision ready" : "vision optional");
  bits.push(state.transcriptionStatus?.ready ? "ASR ready" : "ASR optional");
  stateNode.textContent = bits.join(" | ");
}

function renderVideoPresets(data = {}) {
  const presets = data.presets || [];
  state.videoPresets = presets;
  const select = document.getElementById("videoPresetSelect");
  if (!select || !presets.length) return;
  const current = select.value || "standard_survey";
  select.innerHTML = "";
  presets.forEach(preset => {
    const option = document.createElement("option");
    option.value = preset.id;
    option.textContent = preset.label || preset.id;
    option.title = preset.description || "";
    select.appendChild(option);
  });
  select.value = presets.some(preset => preset.id === current) ? current : "standard_survey";
  applyVideoPreset(select.value, false);
}

function applyVideoPreset(presetId, announce = true) {
  const preset = state.videoPresets.find(item => item.id === presetId);
  if (!preset) return;
  const interval = document.getElementById("videoIntervalInput");
  const frames = document.getElementById("videoMaxFramesInput");
  if (interval) interval.value = preset.interval_seconds || 60;
  if (frames) frames.value = preset.max_frames || 48;
  if (announce) {
    const statusNode = document.getElementById("videoStatus");
    if (statusNode) statusNode.textContent = preset.description || `${preset.label} preset selected.`;
  }
}

async function loadVideoToolStatus() {
  try {
    const [status, presets, vision, transcription] = await Promise.all([
      getJSON("/api/media/ffmpeg/status"),
      getJSON("/api/media/video/presets"),
      getJSON("/api/media/vision/status"),
      getJSON("/api/media/transcription/status")
    ]);
    renderVideoFfmpegStatus(status);
    renderMediaAiStatus({vision, transcription});
    renderVideoPresets(presets);
    const scanJob = await loadVideoArchiveScanStatus();
    if (scanJob?.running && !state.videoScanPollTimer) {
      state.videoScanPollTimer = setTimeout(pollVideoArchiveScan, 2000);
    }
  } catch (err) {
    renderVideoFfmpegStatus({ready: false, hint: `${err.message}. Restart the server after adding FFmpeg support.`});
  }
}

function renderVideoScanSummary(context = {}) {
  const panel = document.getElementById("videoScanSummary");
  if (!panel) return;
  panel.innerHTML = "";
  const summary = context.scan_summary || {};
  if (!context.target?.path) return;
  const chips = [
    ["Duration", summary.duration_label || formatDuration(summary.duration_seconds || 0)],
    ["Frames", formatCount(summary.storyboard_frames || 0)],
    ["Chapters", formatCount(summary.chapters || 0)],
    ["Subtitles", summary.subtitles_extracted ? "extracted" : `${formatCount(summary.subtitle_streams || 0)} stream(s)`],
    ["Transcript", `${formatCount(summary.transcript_segments || 0)} segment(s)`],
    ["Objects", `${formatCount(summary.object_frames || 0)} frame(s)`],
    ["Video streams", formatCount(summary.streams?.video || 0)],
    ["Audio streams", formatCount(summary.streams?.audio || 0)]
  ];
  chips.forEach(([label, value]) => {
    const chip = el("div", "video-summary-chip");
    chip.appendChild(el("span", null, label));
    chip.appendChild(el("strong", null, value));
    panel.appendChild(chip);
  });
  const sheet = summary.contact_sheet || context.artifacts?.contact_sheet;
  if (sheet) {
    const link = el("a", "button-link", "Open contact sheet");
    link.href = `/api/file?path=${encodeURIComponent(sheet)}`;
    link.target = "_blank";
    panel.appendChild(link);
  }
}

function renderVideoArchiveScanStatus(job = {}) {
  const panel = document.getElementById("videoArchiveScanStatus");
  if (!panel) return;
  const total = Number(job.total || 0);
  const processed = Number(job.processed || 0);
  const succeeded = Number(job.succeeded || 0);
  const failed = Number(job.failed || 0);
  const skipped = Number(job.skipped || 0);
  const pending = Number(job.pending_candidates || 0);
  const pct = total ? Math.round((processed / total) * 100) : 0;
  const current = job.current_path ? ` Current ${compactMiddle(job.current_path, 90)}.` : "";
  const error = job.last_error ? ` Last issue: ${job.last_error}` : "";
  if (job.running) {
    panel.textContent = `Scanning archive videos with ${job.preset || "quick_skim"}: ${formatCount(processed)} of ${formatCount(total)} (${pct}%). Indexed ${formatCount(succeeded)}, skipped ${formatCount(skipped)}, failed ${formatCount(failed)}.${current}${error}`;
    return;
  }
  if (job.done) {
    panel.textContent = `Archive video scan complete. Indexed ${formatCount(succeeded)} of ${formatCount(total)} video(s), skipped ${formatCount(skipped)}, failed ${formatCount(failed)}.${error}`;
    return;
  }
  if (job.stop_requested) {
    panel.textContent = `Archive video scan stopped at ${formatCount(processed)} of ${formatCount(total)} video(s).`;
    return;
  }
  panel.textContent = pending
    ? `${formatCount(pending)} active archive video(s) still need FFmpeg context.`
    : "All active archive videos have FFmpeg context, or no videos are indexed yet.";
}

async function loadVideoArchiveScanStatus() {
  try {
    const job = await getJSON("/api/media/video/scan-status");
    renderVideoArchiveScanStatus(job);
    return job;
  } catch (err) {
    const panel = document.getElementById("videoArchiveScanStatus");
    if (panel) panel.textContent = err.message;
    return null;
  }
}

async function pollVideoArchiveScan() {
  state.videoScanPollTimer = null;
  const job = await loadVideoArchiveScanStatus();
  if (job?.running) state.videoScanPollTimer = setTimeout(pollVideoArchiveScan, 2500);
}

async function startVideoArchiveScan() {
  const payload = {
    preset: document.getElementById("videoPresetSelect")?.value || "quick_skim",
    update_index: Boolean(document.getElementById("videoUpdateIndexToggle")?.checked),
    rescan_existing: Boolean(document.getElementById("videoRescanExistingToggle")?.checked),
    detect_faces: Boolean(document.getElementById("videoDetectFacesToggle")?.checked),
    detect_objects: Boolean(document.getElementById("videoDetectObjectsToggle")?.checked),
    include_delete_queue: false
  };
  const statusNode = document.getElementById("videoArchiveScanStatus");
  if (statusNode) statusNode.textContent = "Starting archive video scan...";
  try {
    const data = await postJSON("/api/media/video/scan-all", payload);
    renderVideoArchiveScanStatus(data.job || {});
    if (!state.videoScanPollTimer) state.videoScanPollTimer = setTimeout(pollVideoArchiveScan, 1200);
  } catch (err) {
    if (statusNode) statusNode.textContent = err.message;
  }
}

async function stopVideoArchiveScan() {
  try {
    const data = await postJSON("/api/media/video/scan-stop");
    renderVideoArchiveScanStatus(data.job || {});
  } catch (err) {
    const statusNode = document.getElementById("videoArchiveScanStatus");
    if (statusNode) statusNode.textContent = err.message;
  }
}

function renderVideoStage(context = {}) {
  const stage = document.getElementById("videoStage");
  if (!stage) return;
  stage.innerHTML = "";
  const target = context.target || {};
  const segments = context.segments || [];
  const firstThumb = context.scan_summary?.contact_sheet || context.artifacts?.contact_sheet || segments.find(segment => segment.thumb_path)?.thumb_path;
  if (firstThumb) {
    const img = el("img", "preview-img");
    img.src = `/api/preview?path=${encodeURIComponent(firstThumb)}`;
    img.alt = target.name || "Video context preview";
    stage.appendChild(img);
  } else {
    stage.appendChild(el("div", "video-stage-empty", target.path ? "No storyboard frames extracted yet." : "Load a video to build a searchable context timeline."));
  }
}

function renderVideoStoryboard(segments = []) {
  const board = document.getElementById("videoStoryboard");
  if (!board) return;
  board.innerHTML = "";
  if (!segments.length) {
    board.appendChild(el("div", "compact-output", "No timeline segments yet."));
    return;
  }
  segments.forEach(segment => {
    const card = el("article", "video-frame-card");
    if (segment.thumb_path) {
      const img = el("img");
      img.src = `/api/preview?path=${encodeURIComponent(segment.thumb_path)}`;
      img.alt = segment.title || "Video frame";
      card.appendChild(img);
    }
    card.appendChild(el("div", "video-frame-time", segmentTimeLabel(segment)));
    card.appendChild(el("div", "video-frame-summary", segment.summary || segment.title || "Video segment"));
    const actions = el("div", "row-actions");
    const use = el("button", null, "Use");
    use.type = "button";
    use.onclick = () => {
      document.getElementById("videoSegmentStartInput").value = Number(segment.start_seconds || 0).toFixed(1);
      document.getElementById("videoSegmentEndInput").value = segment.end_seconds !== null && segment.end_seconds !== undefined ? Number(segment.end_seconds).toFixed(1) : "";
      document.getElementById("videoSegmentTitleInput").value = segment.title || "";
      document.getElementById("videoSegmentTimelineInput").value = segment.timeline || "";
      document.getElementById("videoSegmentTagsInput").value = (segment.tags || []).join(", ");
      document.getElementById("videoSegmentAssociationsInput").value = (segment.associations || []).join(", ");
      document.getElementById("videoSegmentSummaryInput").focus();
    };
    actions.appendChild(use);
    if (segment.thumb_path) {
      const open = el("a", "button-link", "Open");
      open.href = `/api/file?path=${encodeURIComponent(segment.thumb_path)}`;
      open.target = "_blank";
      actions.appendChild(open);
    }
    card.appendChild(actions);
    board.appendChild(card);
  });
}

function renderVideoContext(context = {}) {
  state.videoContext = context;
  const statusNode = document.getElementById("videoStatus");
  const target = context.target || {};
  const probe = context.probe || {};
  if (statusNode) {
    statusNode.textContent = target.path
      ? `${target.name || "Video"} | ${probe.summary || "Context loaded."} | ${formatCount((context.segments || []).length)} segment(s)`
      : "No video loaded.";
  }
  if (target.path && document.getElementById("videoPathInput")) {
    document.getElementById("videoPathInput").value = target.file_id || target.path;
  }
  renderVideoScanSummary(context);
  renderVideoStage(context);
  renderVideoStoryboard(context.segments || []);
}

async function loadVideoContext() {
  try {
    const payload = videoInputPayload();
    const params = new URLSearchParams();
    if (payload.file_id) params.set("file_id", payload.file_id);
    if (payload.path) params.set("path", payload.path);
    renderVideoContext(await getJSON(`/api/media/video/context?${params.toString()}`));
  } catch (err) {
    const statusNode = document.getElementById("videoStatus");
    if (statusNode) statusNode.textContent = err.message;
  }
}

async function analyzeVideoContext() {
  try {
    const payload = {
      ...videoInputPayload(),
      preset: document.getElementById("videoPresetSelect")?.value || "standard_survey",
      interval_seconds: Number(document.getElementById("videoIntervalInput")?.value || 60),
      max_frames: Number(document.getElementById("videoMaxFramesInput")?.value || 24),
      update_index: Boolean(document.getElementById("videoUpdateIndexToggle")?.checked),
      detect_faces: Boolean(document.getElementById("videoDetectFacesToggle")?.checked),
      detect_objects: Boolean(document.getElementById("videoDetectObjectsToggle")?.checked)
    };
    const statusNode = document.getElementById("videoStatus");
    const objectText = payload.detect_objects ? ", object tags" : "";
    const faceText = payload.detect_faces ? ", face scan" : "";
    if (statusNode) statusNode.textContent = `Running FFmpeg video triage: probe, storyboard, chapters, subtitles${faceText}${objectText}...`;
    const data = await postJSON("/api/media/video/analyze", payload);
    renderVideoContext(data);
    appendMessage("assistant", `Video context updated for ${data.target?.path || "video"}. Created ${formatCount(data.created_segment_ids?.length || 0)} searchable segment(s).`);
  } catch (err) {
    const statusNode = document.getElementById("videoStatus");
    if (statusNode) statusNode.textContent = err.message;
  }
}

async function transcribeVideoContext() {
  try {
    const payload = {
      ...videoInputPayload(),
      update_index: Boolean(document.getElementById("videoUpdateIndexToggle")?.checked),
      prefer_subtitles: true
    };
    const statusNode = document.getElementById("videoStatus");
    if (statusNode) {
      const asr = state.transcriptionStatus?.ready ? `ASR ${state.transcriptionStatus.engine || ""}` : "embedded subtitles first";
      statusNode.textContent = `Transcribing video speech (${asr})...`;
    }
    const data = await postJSON("/api/media/video/transcribe", payload);
    renderVideoContext(data);
    appendMessage("assistant", `Video transcript updated for ${data.target?.path || "video"}. Created ${formatCount(data.created_segment_ids?.length || 0)} transcript segment(s).`);
  } catch (err) {
    const statusNode = document.getElementById("videoStatus");
    if (statusNode) statusNode.textContent = err.message;
  }
}

function renderVideoSearchResults(data = {}) {
  const panel = document.getElementById("videoResults");
  if (!panel) return;
  panel.innerHTML = "";
  const segments = data.segments || [];
  const files = data.files || [];
  if (!segments.length && !files.length) {
    panel.appendChild(el("div", "compact-output", "No video context matches."));
    return;
  }
  segments.forEach(segment => {
    const card = el("article", "video-result-card");
    card.appendChild(el("div", "video-result-meta", `${segmentTimeLabel(segment)} | ${segment.timeline || "timeline"}`));
    card.appendChild(el("div", "video-result-body", `${segment.title || "Segment"}\n${segment.summary || ""}\n${segment.path || ""}`));
    const actions = el("div", "row-actions");
    const open = el("a", "button-link", "Open video");
    open.href = `/api/file?path=${encodeURIComponent(segment.path)}`;
    open.target = "_blank";
    actions.appendChild(open);
    card.appendChild(actions);
    panel.appendChild(card);
  });
  files.forEach(file => {
    const card = el("article", "video-result-card");
    card.appendChild(el("div", "video-result-meta", "Indexed video"));
    card.appendChild(el("div", "video-result-body", `${file.name || "Video"}\n${file.summary || ""}\n${file.path || ""}`));
    const actions = el("div", "row-actions");
    const load = el("button", null, "Load");
    load.type = "button";
    load.onclick = () => {
      document.getElementById("videoPathInput").value = file.id || file.path;
      loadVideoContext();
    };
    const open = el("a", "button-link", "Open");
    open.href = `/api/file?path=${encodeURIComponent(file.path)}`;
    open.target = "_blank";
    actions.appendChild(load);
    actions.appendChild(open);
    card.appendChild(actions);
    panel.appendChild(card);
  });
}

async function searchVideoContext() {
  const q = document.getElementById("videoSearchInput")?.value.trim() || "";
  if (!q) {
    renderVideoSearchResults({});
    return;
  }
  try {
    renderVideoSearchResults(await getJSON(`/api/media/video/search?q=${encodeURIComponent(q)}`));
  } catch (err) {
    const panel = document.getElementById("videoResults");
    if (panel) {
      panel.innerHTML = "";
      panel.appendChild(el("div", "compact-output", err.message));
    }
  }
}

async function saveVideoSegment() {
  try {
    const context = state.videoContext || {};
    const payload = {
      ...(context.target?.file_id ? {file_id: context.target.file_id} : videoInputPayload()),
      start_seconds: Number(document.getElementById("videoSegmentStartInput")?.value || 0),
      end_seconds: document.getElementById("videoSegmentEndInput")?.value ? Number(document.getElementById("videoSegmentEndInput").value) : null,
      title: document.getElementById("videoSegmentTitleInput")?.value || "",
      summary: document.getElementById("videoSegmentSummaryInput")?.value || "",
      timeline: document.getElementById("videoSegmentTimelineInput")?.value || "",
      tags: splitList(document.getElementById("videoSegmentTagsInput")?.value || ""),
      associations: splitList(document.getElementById("videoSegmentAssociationsInput")?.value || "")
    };
    const data = await postJSON("/api/media/video/segments", payload);
    const nextContext = {
      ...(state.videoContext || {}),
      segments: data.segments || [],
      target: state.videoContext?.target || {}
    };
    renderVideoContext(nextContext);
    appendMessage("assistant", `Saved video segment #${data.segment_id}. Indexed context ${data.sync?.synced ? "updated" : "not updated"} for search.`);
  } catch (err) {
    const statusNode = document.getElementById("videoStatus");
    if (statusNode) statusNode.textContent = err.message;
  }
}

function wireVideoPathDrop(node) {
  if (!node) return;
  node.addEventListener("dragover", event => {
    event.preventDefault();
    node.classList.add("is-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", event => {
    event.preventDefault();
    node.classList.remove("is-over");
    const path = extractDroppedPath(event.dataTransfer);
    if (path) {
      node.value = path;
      loadVideoContext();
      return;
    }
    const files = Array.from(event.dataTransfer.files || []);
    if (files[0]?.path) {
      node.value = files[0].path;
      loadVideoContext();
    }
  });
}

async function copyTextToSystem(text) {
  const value = String(text || "");
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    setStatus("Copied");
    window.setTimeout(() => setStatus("Idle"), 900);
  } catch {
    appendDroppedTextToChat(value);
    appendMessage("assistant", "I could not write to the system clipboard, so I staged the text in chat.");
  }
}

function clipboardText(item) {
  return item?.content || item?.file_path || item?.original_name || "";
}

function renderClipboard(items = []) {
  const list = document.getElementById("clipboardList");
  if (!list) return;
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(el("div", "compact-output", "Clipboard is quiet."));
    return;
  }
  items.forEach(item => {
    const card = el("article", `clipboard-item clipboard-${item.kind || "text"}`);
    const title = item.original_name || titleFromText(item.content || item.file_path || "Clipboard item");
    card.appendChild(el("div", "clipboard-title", title));
    card.appendChild(el("div", "clipboard-meta", `${item.kind || "text"} - ${shortTime(item.created_ts)}`));
    const body = el("div", "clipboard-body", compactMiddle(clipboardText(item), 140));
    card.appendChild(body);
    const actions = el("div", "clipboard-actions");
    const copyBtn = el("button", null, "Copy");
    copyBtn.type = "button";
    copyBtn.onclick = () => copyTextToSystem(clipboardText(item));
    actions.appendChild(copyBtn);
    const chatBtn = el("button", null, "Chat");
    chatBtn.type = "button";
    chatBtn.onclick = () => appendDroppedTextToChat(clipboardText(item));
    actions.appendChild(chatBtn);
    if (item.file_path) {
      const openLink = el("a", "button-link", "Open");
      openLink.href = `/api/file?path=${encodeURIComponent(item.file_path)}`;
      openLink.target = "_blank";
      actions.appendChild(openLink);
    }
    const notesBtn = el("button", null, "Notes");
    notesBtn.type = "button";
    notesBtn.onclick = () => setView("notes");
    actions.appendChild(notesBtn);
    card.appendChild(actions);
    list.appendChild(card);
  });
}

function titleFromText(text) {
  const clean = String(text || "").trim().replace(/\s+/g, " ");
  return clean ? compactMiddle(clean, 62) : "Untitled";
}

async function loadClipboard() {
  try {
    const data = await getJSON("/api/clipboard?limit=12");
    renderClipboard(data.items || []);
  } catch (err) {
    const list = document.getElementById("clipboardList");
    if (list) {
      list.innerHTML = "";
      list.appendChild(el("div", "compact-output", "Clipboard routes will be available after the next server restart."));
    }
  }
}

async function saveClipboardText(content, source = "manual") {
  const clean = String(content || "").trim();
  if (!clean) return;
  const data = await postJSON("/api/clipboard/text", {content: clean, source});
  renderClipboard(data.items || []);
  if (data.notes) renderNotes(data.notes || []);
  const input = document.getElementById("clipboardInput");
  if (input && ["manual", "paste"].includes(source)) input.value = "";
}

async function uploadClipboardFile(file) {
  const form = new FormData();
  form.append("file", file);
  const data = await readJSON(await fetch("/api/clipboard/file", {method: "POST", body: form}));
  renderClipboard(data.items || []);
  if (data.notes) renderNotes(data.notes || []);
}

async function pasteClipboardText() {
  try {
    const text = await navigator.clipboard.readText();
    if (text.trim()) await saveClipboardText(text, "system_clipboard");
  } catch (err) {
    appendMessage("assistant", "Browser clipboard access was blocked. Paste into the Clipboard box and press Save.");
  }
}

async function clearClipboard() {
  const confirmed = window.confirm("Clear the clipboard list? Notes created from clipboard items will stay in Notes.");
  if (!confirmed) return;
  await postURL("/api/clipboard/clear");
  await loadClipboard();
}

function scrollClipboard(direction = 1) {
  const list = document.getElementById("clipboardList");
  if (!list) return;
  list.scrollBy({top: direction * 130, behavior: "smooth"});
}

function wireClipboardDropTarget(node) {
  if (!node) return;
  node.addEventListener("dragover", event => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    node.classList.add("is-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", async event => {
    event.preventDefault();
    node.classList.remove("is-over");
    const files = Array.from(event.dataTransfer.files || []);
    if (files.length) {
      for (const file of files) await uploadClipboardFile(file);
      return;
    }
    const path = extractDroppedPath(event.dataTransfer);
    const text = path || event.dataTransfer.getData("text/plain") || event.dataTransfer.getData("text/uri-list");
    if (text) await saveClipboardText(text, "drop");
  });
  node.addEventListener("paste", async event => {
    const files = Array.from(event.clipboardData?.files || []);
    if (files.length) {
      event.preventDefault();
      for (const file of files) await uploadClipboardFile(file);
      return;
    }
    const text = event.clipboardData?.getData("text/plain");
    if (text) {
      event.preventDefault();
      await saveClipboardText(text, "paste");
    }
  });
}

function wireClipboardInputPaste(node) {
  if (!node) return;
  node.addEventListener("paste", event => {
    const files = Array.from(event.clipboardData?.files || []);
    if (files.length) {
      event.preventDefault();
      files.forEach(file => uploadClipboardFile(file));
      return;
    }
    const text = event.clipboardData?.getData("text/plain");
    if (!text) return;
    window.setTimeout(() => {
      const value = node.value.trim();
      if (value) saveClipboardText(value, "paste").catch(err => appendMessage("assistant", err.message));
    }, 0);
  });
}

function noteText(note) {
  return note?.content || note?.file_path || "";
}

function noteMedia(note) {
  if (!note.file_path) return null;
  if (note.kind === "image") {
    const img = el("img", "note-media");
    img.src = `/api/file?path=${encodeURIComponent(note.file_path)}`;
    img.alt = note.original_name || note.title || "Note image";
    return img;
  }
  if (note.kind === "video") {
    const video = el("video", "note-media");
    video.controls = true;
    const source = el("source");
    source.src = `/api/file?path=${encodeURIComponent(note.file_path)}`;
    video.appendChild(source);
    return video;
  }
  if (note.kind === "audio") {
    const audio = el("audio", "note-audio");
    audio.controls = true;
    const source = el("source");
    source.src = `/api/file?path=${encodeURIComponent(note.file_path)}`;
    audio.appendChild(source);
    return audio;
  }
  const link = el("a", "button-link", note.original_name || "Open file");
  link.href = `/api/file?path=${encodeURIComponent(note.file_path)}`;
  link.target = "_blank";
  return link;
}

function scheduleNoteSave(noteId, payload) {
  window.clearTimeout(state.noteSaveTimers[noteId]);
  state.noteSaveTimers[noteId] = window.setTimeout(() => {
    postJSON(`/api/notes/${noteId}`, payload).catch(err => appendMessage("assistant", err.message));
  }, 650);
}

function renderNotes(notes = []) {
  const grid = document.getElementById("notesGrid");
  if (!grid) return;
  grid.innerHTML = "";
  if (!notes.length) {
    grid.appendChild(el("div", "notes-empty", "No active notes yet."));
    return;
  }
  notes.forEach(note => {
    const card = el("article", `note-card note-${note.kind || "text"}`);
    card.dataset.noteId = String(note.id);

    const title = el("input", "note-title-input");
    title.value = note.title || "";
    title.placeholder = "Untitled";
    title.addEventListener("input", () => scheduleNoteSave(note.id, {title: title.value}));
    card.appendChild(title);

    const media = noteMedia(note);
    if (media) card.appendChild(media);

    const text = el("textarea", "note-content-input");
    text.value = note.content || "";
    text.placeholder = "Write, paste, or drop here";
    text.addEventListener("input", () => scheduleNoteSave(note.id, {content: text.value}));
    card.appendChild(text);

    const meta = el("div", "note-meta", `${note.kind || "text"} - ${shortTime(note.updated_ts)}`);
    card.appendChild(meta);

    const actions = el("div", "note-actions");
    const copyBtn = el("button", null, "Copy");
    copyBtn.type = "button";
    copyBtn.onclick = () => copyTextToSystem(noteText({...note, content: text.value}));
    actions.appendChild(copyBtn);
    const chatBtn = el("button", null, "Chat");
    chatBtn.type = "button";
    chatBtn.onclick = () => appendDroppedTextToChat(noteText({...note, content: text.value}));
    actions.appendChild(chatBtn);
    const doneBtn = el("button", null, "Done");
    doneBtn.type = "button";
    doneBtn.onclick = async () => {
      await postJSON(`/api/notes/${note.id}`, {status: "done"});
      await loadNotes();
    };
    actions.appendChild(doneBtn);
    const deleteBtn = el("button", "danger-button", "Delete");
    deleteBtn.type = "button";
    deleteBtn.onclick = async () => {
      const confirmed = window.confirm("Remove this note card from the active workspace?");
      if (!confirmed) return;
      await postJSON(`/api/notes/${note.id}`, {status: "deleted"});
      await loadNotes();
    };
    actions.appendChild(deleteBtn);
    card.appendChild(actions);

    wireNoteCardDrop(card, note.id);
    grid.appendChild(card);
  });
}

async function loadNotes() {
  try {
    const data = await getJSON("/api/notes?status=active&limit=120");
    renderNotes(data.notes || []);
  } catch (err) {
    const grid = document.getElementById("notesGrid");
    if (grid) {
      grid.innerHTML = "";
      grid.appendChild(el("div", "notes-empty", "Notes routes will be available after the next server restart."));
    }
  }
}

async function createBlankNote() {
  const data = await postJSON("/api/notes", {title: "New note", content: "", kind: "text"});
  await loadNotes();
  return data.note;
}

async function createTextNote(content) {
  const clean = String(content || "").trim();
  if (!clean) return;
  await postJSON("/api/notes", {title: titleFromText(clean), content: clean, kind: "text"});
  await loadNotes();
}

async function uploadNoteFile(file) {
  const form = new FormData();
  form.append("file", file);
  await readJSON(await fetch("/api/notes/file", {method: "POST", body: form}));
  await loadNotes();
}

function wireNotesDropTarget(node) {
  if (!node) return;
  node.addEventListener("dragover", event => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    node.classList.add("is-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", async event => {
    event.preventDefault();
    node.classList.remove("is-over");
    const files = Array.from(event.dataTransfer.files || []);
    if (files.length) {
      for (const file of files) await uploadNoteFile(file);
      return;
    }
    const path = extractDroppedPath(event.dataTransfer);
    const text = path || event.dataTransfer.getData("text/plain") || event.dataTransfer.getData("text/uri-list");
    if (text) await createTextNote(text);
  });
  node.addEventListener("paste", async event => {
    const files = Array.from(event.clipboardData?.files || []);
    if (files.length) {
      event.preventDefault();
      for (const file of files) await uploadNoteFile(file);
      return;
    }
    const text = event.clipboardData?.getData("text/plain");
    if (text) {
      event.preventDefault();
      await createTextNote(text);
    }
  });
}

function wireNoteCardDrop(card, noteId) {
  card.addEventListener("dragover", event => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    card.classList.add("is-over");
  });
  card.addEventListener("dragleave", () => card.classList.remove("is-over"));
  card.addEventListener("drop", async event => {
    event.preventDefault();
    card.classList.remove("is-over");
    const files = Array.from(event.dataTransfer.files || []);
    if (files.length) {
      for (const file of files) await uploadNoteFile(file);
      return;
    }
    const text = extractDroppedPath(event.dataTransfer) || event.dataTransfer.getData("text/plain") || "";
    if (text) {
      const textarea = card.querySelector(".note-content-input");
      const next = `${textarea.value.trim()}\n\n${text.trim()}`.trim();
      textarea.value = next;
      await postJSON(`/api/notes/${noteId}`, {content: next});
    }
  });
}

function closePreview() {
  const preview = document.getElementById("preview");
  if (!preview) return;
  preview.innerHTML = "";
  preview.textContent = "No preview.";
  state.previewPath = null;
  state.previewFileId = null;
  const queueBtn = document.getElementById("queuePreviewDeleteBtn");
  if (queueBtn) queueBtn.disabled = true;
}

function showPreview(pathOrFile) {
  const preview = document.getElementById("preview");
  if (!preview) return;
  preview.innerHTML = "";
  const path = typeof pathOrFile === "string" ? pathOrFile : pathOrFile?.preview_path || pathOrFile?.thumb_path || pathOrFile?.path;
  state.previewPath = typeof pathOrFile === "string" ? pathOrFile : pathOrFile?.path || path;
  state.previewFileId = typeof pathOrFile === "string" ? null : pathOrFile?.id || null;
  const queueBtn = document.getElementById("queuePreviewDeleteBtn");
  if (queueBtn) queueBtn.disabled = !state.previewPath;
  if (!path) {
    closePreview();
    return;
  }

  const lower = path.toLowerCase();
  if ([".jpg", ".jpeg", ".png", ".gif", ".webp"].some(ext => lower.endsWith(ext))) {
    const img = el("img", "preview-img");
    img.src = `/api/preview?path=${encodeURIComponent(path)}`;
    img.alt = "Preview";
    preview.appendChild(img);
    return;
  }

  if ([".mp4", ".webm", ".mov"].some(ext => lower.endsWith(ext))) {
    const video = el("video", "preview-video");
    video.controls = true;
    const source = el("source");
    source.src = `/api/file?path=${encodeURIComponent(path)}`;
    video.appendChild(source);
    preview.appendChild(video);
    return;
  }

  const link = el("a", "text-link", "Open file");
  link.href = `/api/file?path=${encodeURIComponent(path)}`;
  link.target = "_blank";
  preview.appendChild(link);
}

function normalizedFileHits(data) {
  const hits = [
    ...(data.keyword_hits || []),
    ...((data.semantic_hits || []).map(x => ({
      path: x.metadata?.path || "",
      name: x.metadata?.name || "(semantic result)",
      summary: x.metadata?.summary || "",
      preview_path: null,
      thumb_path: null
    })))
  ];
  const seen = new Set();
  return hits.filter(hit => {
    const key = hit.path || hit.name;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderEvidence(data) {
  const results = document.getElementById("results");
  if (!results) return;
  results.innerHTML = "";

  const memories = data.memory_hits || [];
  const files = normalizedFileHits(data);

  if (!memories.length && !files.length) {
    results.appendChild(el("div", "compact-output", "No evidence returned."));
    return;
  }

  memories.forEach(memory => {
    const item = el("div", "evidence-item");
    item.appendChild(el("div", "evidence-kind", `Memory / ${memory.status || "retrieved"}`));
    item.appendChild(el("div", "evidence-title", memory.content || ""));
    results.appendChild(item);
  });

  files.forEach(hit => {
    const item = el("div", "evidence-item");
    if (hit.path) {
      item.draggable = true;
      item.addEventListener("dragstart", event => {
        event.dataTransfer.setData("text/plain", hit.path);
        event.dataTransfer.setData("application/x-archivist-path", hit.path);
      });
    }
    item.appendChild(el("div", "evidence-kind", "File"));
    item.appendChild(el("div", "evidence-title", hit.name || "(unnamed)"));
    item.appendChild(el("div", "evidence-path", hit.path || ""));
    if (hit.summary) item.appendChild(el("div", "evidence-summary", hit.summary));

    const actions = el("div", "evidence-actions");
    const previewBtn = el("button", null, "Preview");
    previewBtn.type = "button";
    previewBtn.onclick = () => showPreview(hit);
    actions.appendChild(previewBtn);

    if (hit.path) {
      const link = el("a", "button-link", "Open");
      link.href = `/api/file?path=${encodeURIComponent(hit.path)}`;
      link.target = "_blank";
      actions.appendChild(link);
    }
    item.appendChild(actions);
    results.appendChild(item);
  });
}

function selectedFileIds() {
  return Array.from(state.selectedFileIds);
}

function activeFileFilter() {
  return document.getElementById("fileFilter")?.value || "";
}

function fileRowForId(id) {
  return document.querySelector(`#fileTableBody tr[data-file-id="${Number(id)}"]`);
}

function removeFileRows(ids) {
  ids.forEach(id => {
    const row = fileRowForId(id);
    if (row) row.remove();
    state.selectedFileIds.delete(Number(id));
  });
  document.getElementById("selectAllFiles").checked = false;
}

function markFileRowsQueued(ids, queued = true) {
  ids.forEach(id => {
    const row = fileRowForId(id);
    if (!row) return;
    row.classList.toggle("is-delete-candidate", queued);
    row.classList.remove("is-selected");
    const checkbox = row.querySelector("input[type='checkbox']");
    if (checkbox) checkbox.checked = false;
    const queueBtn = row.querySelector("[data-queue-delete-btn]");
    if (queueBtn) {
      queueBtn.textContent = queued ? "Queued" : "Queue delete";
      queueBtn.disabled = queued;
    }
    state.selectedFileIds.delete(Number(id));
  });
  document.getElementById("selectAllFiles").checked = false;
}

async function loadStats() {
  const stats = await getJSON("/api/maintenance/stats");
  renderStats(stats);
}

async function refreshFileMaintenance({files = true, duplicates = true, stats = true} = {}) {
  const jobs = [];
  if (stats) jobs.push(loadStats());
  if (files) jobs.push(loadFiles());
  if (duplicates) jobs.push(loadDuplicates());
  await Promise.all(jobs);
}

function setMaintenanceNotice(message) {
  const stats = document.getElementById("statsGrid");
  stats.innerHTML = "";
  const card = el("div", "stat-card");
  card.appendChild(el("div", "stat-label", "Maintenance"));
  card.appendChild(el("div", "stat-detail", message));
  stats.appendChild(card);
}

function renderModelRoutes(data = {}) {
  const grid = document.getElementById("modelRouteGrid");
  const status = document.getElementById("modelRoutingStatus");
  const badge = document.getElementById("activeModelBadge");
  if (!grid) return;
  grid.innerHTML = "";
  const routes = data.routes || [];
  if (!routes.length) {
    grid.appendChild(el("div", "compact-output", "No model routes returned."));
    if (status) status.textContent = "Model routing endpoint returned no routes.";
    if (badge) badge.textContent = "Archivist route unavailable";
    return;
  }
  const archivistRoute = routes.find(route => route.task === "archivist_chat" || route.label === "Archivist chat") || routes[0];
  if (badge) badge.textContent = `${archivistRoute.label || "Archivist"}: ${archivistRoute.model || "not configured"}`;
  routes.forEach(route => {
    const card = el("div", "model-route-card");
    card.appendChild(el("div", "model-route-task", route.label || route.task || "Model"));
    card.appendChild(el("div", "model-route-model", route.model || "not configured"));
    card.appendChild(el("div", "model-route-meta", `${route.kind || "chat"} | ${route.env || ""}`));
    if (route.fallback_model) {
      card.appendChild(el("div", "model-route-meta", `fallback: ${route.fallback_model}`));
    }
    if (route.voice) card.appendChild(el("div", "model-route-meta", route.voice));
    if (route.use) card.appendChild(el("div", "model-route-meta", route.use));
    grid.appendChild(card);
  });
  if (status) {
    status.textContent = "Routes are read from environment variables at server startup. Restart after changing model env vars.";
  }
}

async function loadModels() {
  try {
    const data = await getJSON("/api/models");
    renderModelRoutes(data);
  } catch (err) {
    const status = document.getElementById("modelRoutingStatus");
    if (status) status.textContent = "Model routes will be available after the next server restart.";
    const badge = document.getElementById("activeModelBadge");
    if (badge) badge.textContent = "Archivist route pending restart";
  }
}

function renderStats(stats) {
  const grid = document.getElementById("statsGrid");
  if (!grid) return;
  grid.innerHTML = "";
  const disk = stats.disk_usage || {};
  const diskWarning = disk.error
    ? disk.error
    : `${formatBytes(disk.free)} free of ${formatBytes(disk.total)} (${Math.round(Number(disk.percent_used || 0))}% used)`;
  const cards = [
    ["Active files", formatCount(stats.active_file_count || stats.file_count), stats.archive_root || ""],
    ["Active size", formatBytes(stats.active_bytes || stats.total_bytes), `${formatCount(stats.categories?.length || 0)} active categories`],
    ["Host disk", disk.error ? "Unavailable" : `${Math.round(Number(disk.percent_used || 0))}% used`, diskWarning, disk],
    ["Duplicate groups", formatCount(stats.duplicate_groups), `${formatBytes(stats.duplicate_reclaimable_bytes)} reclaimable`],
    ["Deletion queue", formatCount(stats.delete_queue_count), `${formatCount(stats.file_count || 0)} total indexed rows`],
    ["Index issues", formatCount(stats.index_failure_count), "Unresolved failures recorded after the maintenance update"]
  ];
  cards.forEach(([label, value, detail, diskData]) => {
    const card = el("div", "stat-card");
    card.appendChild(el("div", "stat-label", label));
    card.appendChild(el("div", "stat-value", value));
    if (detail) card.appendChild(el("div", "stat-detail", detail));
    if (diskData && !diskData.error) {
      const bar = el("div", "disk-usage-track");
      const fill = el("div", "disk-usage-fill");
      const percent = Math.max(0, Math.min(100, Number(diskData.percent_used || 0)));
      fill.style.width = `${percent}%`;
      fill.classList.toggle("is-warning", percent >= 85);
      bar.appendChild(fill);
      card.appendChild(bar);
    }
    grid.appendChild(card);
  });
  renderFileTypeDonut(stats.categories || []);
}

const LOCATION_SLOT_INPUTS = {
  archive_root: "awareArchiveRootInput",
  knowledgebase_root: "knowledgebaseRootInput",
  network_root: "awareNetworkRootInput",
  ignored_archive_root: "ignoredArchiveRootInput",
  ignored_network_root: "ignoredNetworkRootInput",
  external_usb_root: "externalUsbRootInput",
  scanner_inbox: "scannerInboxInput",
  printer_network_root: "printerNetworkInput"
};

const LOCATION_SLOT_META = {
  archive_root: "awareArchiveRootMeta",
  knowledgebase_root: "knowledgebaseRootMeta",
  network_root: "awareNetworkRootMeta",
  ignored_archive_root: "ignoredArchiveRootMeta",
  ignored_network_root: "ignoredNetworkRootMeta",
  external_usb_root: "externalUsbRootMeta",
  scanner_inbox: "scannerInboxMeta",
  printer_network_root: "printerNetworkMeta"
};

function locationSlots(data = {}) {
  if (data.chat_aware || data.chat_ignored) {
    return [...(data.chat_aware || []), ...(data.chat_ignored || []), ...(data.external_sources || [])];
  }
  return [
    {key: "archive_root", path: data.configured_archive_root || data.active_archive_root || "", active_path: data.active_archive_root, restart_applies: true, restart_required: Boolean(data.restart_required)},
    {key: "knowledgebase_root", path: data.configured_knowledgebase_root || "", active_path: data.active_knowledgebase_root, restart_applies: true, restart_required: Boolean(data.restart_required)}
  ];
}

function renderArchiveLocations(data = {}) {
  locationSlots(data).forEach(slot => {
    const input = document.getElementById(LOCATION_SLOT_INPUTS[slot.key]);
    if (input && document.activeElement !== input) input.value = slot.path || "";
    const meta = document.getElementById(LOCATION_SLOT_META[slot.key]);
    if (!meta) return;
    meta.innerHTML = "";
    if ((slot.badges || []).length) {
      const badges = el("div", "source-badges");
      (slot.badges || []).forEach(label => {
        const className = `source-badge source-badge-${String(label).toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
        badges.appendChild(el("span", className, label));
      });
      meta.appendChild(badges);
    }
    const bits = [];
    if (slot.active_path) bits.push(`active: ${slot.active_path}`);
    if (slot.path && slot.exists === false) bits.push("not currently reachable");
    if (slot.restart_required) bits.push("restart needed");
    if (slot.policy_reason) bits.push(slot.policy_reason);
    if (!slot.path) bits.push("empty");
    if (bits.length) meta.appendChild(el("div", "source-slot-detail", bits.join(" | ")));
  });

  const status = document.getElementById("archiveLocationStatus");
  if (data.policy_notice) {
    status.textContent = data.policy_notice;
  } else if (data.restart_required) {
    status.textContent = "Chat-aware archive or knowledgebase roots changed and will take effect after the server restarts. Chat-ignored slots are staged for future archival workflows.";
  } else {
    status.textContent = "Location panes are current. Non-local roots are chat-ignored by default; full chat-aware indexing stays local-first.";
  }
}

function renderLocationBrowser(data = {}) {
  const browser = document.getElementById("archiveLocationBrowser");
  browser.innerHTML = "";
  browser.classList.add("is-open");
  state.locationBrowserPath = data.current_path || null;

  const head = el("div", "location-browser-head");
  head.appendChild(el("div", "file-path", data.current_path || "Folder browser"));
  const headActions = el("div", "row-actions");
  const upBtn = el("button", null, "Up");
  upBtn.type = "button";
  upBtn.disabled = !data.parent_path;
  upBtn.onclick = () => loadLocationBrowser(data.parent_path);
  headActions.appendChild(upBtn);
  const selectCurrentBtn = el("button", null, "Select current");
  selectCurrentBtn.type = "button";
  selectCurrentBtn.onclick = () => setLocationTarget(data.current_path || "");
  headActions.appendChild(selectCurrentBtn);
  const closeBtn = el("button", null, "Close");
  closeBtn.type = "button";
  closeBtn.onclick = () => browser.classList.remove("is-open");
  headActions.appendChild(closeBtn);
  head.appendChild(headActions);
  browser.appendChild(head);

  if ((data.drives || []).length) {
    const driveActions = el("div", "row-actions");
    data.drives.forEach(drive => {
      const btn = el("button", null, drive.name);
      btn.type = "button";
      btn.onclick = () => loadLocationBrowser(drive.path);
      driveActions.appendChild(btn);
    });
    browser.appendChild(driveActions);
  }

  const list = el("div", "directory-list");
  const dirs = data.directories || [];
  if (!dirs.length) {
    list.appendChild(el("div", "compact-output", "No accessible child folders here."));
  }
  dirs.forEach(item => {
    const row = el("div", "directory-item");
    row.appendChild(el("div", "file-path", item.path || item.name || ""));
    const openBtn = el("button", null, "Open");
    openBtn.type = "button";
    openBtn.onclick = () => loadLocationBrowser(item.path);
    row.appendChild(openBtn);
    const selectBtn = el("button", null, "Select");
    selectBtn.type = "button";
    selectBtn.onclick = () => setLocationTarget(item.path || "");
    row.appendChild(selectBtn);
    list.appendChild(row);
  });
  browser.appendChild(list);
}

async function loadArchiveLocations() {
  const data = await getJSON("/api/archive-locations");
  renderArchiveLocations(data);
}

async function loadLocationBrowser(path = null, targetInputId = null) {
  if (targetInputId) state.locationBrowseTargetInput = targetInputId;
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  const data = await getJSON(`/api/archive-locations/browse?${params.toString()}`);
  renderLocationBrowser(data);
}

function setLocationTarget(path) {
  const targetId = state.locationBrowseTargetInput || "awareArchiveRootInput";
  const input = document.getElementById(targetId);
  if (input) input.value = path || "";
}

async function saveLocationSlot(slot, inputId) {
  const input = document.getElementById(inputId);
  const path = input?.value.trim() || "";
  if (!path) return;
  if (["archive_root", "knowledgebase_root"].includes(slot)) {
    const confirmed = window.confirm("Save this chat-aware root? It will take effect after the server restarts.");
    if (!confirmed) return;
  }
  try {
    const data = await postJSON("/api/archive-locations/source", {slot, path});
    renderArchiveLocations(data);
  } catch (err) {
    document.getElementById("archiveLocationStatus").textContent = err.message;
  }
}

function discoveryPositions(nodes = []) {
  const core = nodes.find(node => node.id === "core-archivist");
  const primaryGroups = new Set(["archive", "knowledgebase", "review", "tag", "memory", "note", "clipboard", "conversation", "action", "source"]);
  const primary = nodes.filter(node => node.id !== "core-archivist" && primaryGroups.has(node.group));
  const secondary = nodes.filter(node => node.id !== "core-archivist" && !primaryGroups.has(node.group));
  const placed = [];
  if (core) placed.push({node: core, x: 50, y: 50});

  const placeRing = (items, radiusX, radiusY, startDeg) => {
    const total = Math.max(items.length, 1);
    items.forEach((node, index) => {
      const angle = ((startDeg + (360 / total) * index) * Math.PI) / 180;
      placed.push({
        node,
        x: 50 + Math.cos(angle) * radiusX,
        y: 50 + Math.sin(angle) * radiusY
      });
    });
  };

  placeRing(primary, 24, 20, -84);
  placeRing(secondary, 39, 34, -96);
  nodes.forEach(node => {
    if (!placed.some(item => item.node.id === node.id)) placed.push({node, x: 50, y: 50});
  });
  return placed;
}

function discoveryNodeClass(node = {}) {
  const group = String(node.group || "source").replace(/[^a-z0-9-]/gi, "-").toLowerCase();
  const health = String(node.health_status || "unknown").replace(/[^a-z0-9-]/gi, "-").toLowerCase();
  const policy = String(node.chat_policy || "planned").replace(/[^a-z0-9-]/gi, "-").toLowerCase();
  return `discovery-node discovery-${group} discovery-${health} discovery-${policy}`;
}

function discoveryBadges(node = {}) {
  const wrap = el("div", "source-badges");
  (node.badges || []).forEach(label => {
    const className = `source-badge source-badge-${String(label).toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    wrap.appendChild(el("span", className, label));
  });
  return wrap;
}

function renderDiscovery(data = {}) {
  state.discoveryData = data;
  const nodes = data.nodes || [];
  const links = data.links || [];
  const summary = data.summary || {};
  const summaryNode = document.getElementById("discoverySummary");
  if (summaryNode) {
    if (summary.files !== undefined) {
      summaryNode.textContent = `${formatCount(summary.nodes || nodes.length)} nodes | ${formatCount(summary.links || links.length)} links | ${formatCount(summary.active_files || 0)} active files | ${formatCount(summary.memories || 0)} memories | ${formatCount(summary.notes || 0)} notes`;
    } else {
      summaryNode.textContent = `${formatCount(summary.nodes || nodes.length)} nodes | ${formatCount(summary.configured || 0)} configured | ${formatCount(summary.drives || 0)} drive candidates | ${formatCount(summary.planned || 0)} planned`;
    }
  }
  const subtitle = document.getElementById("discoverySubtitle");
  if (subtitle) subtitle.textContent = `Last scan ${shortTime(data.generated_ts)}`;

  const placed = discoveryPositions(nodes);
  const selectedStillExists = nodes.some(node => node.id === state.selectedDiscoveryNodeId);
  if (!state.selectedDiscoveryNodeId || !selectedStillExists) {
    state.selectedDiscoveryNodeId = nodes.find(node => node.id === "core-archivist")?.id || nodes[0]?.id || null;
  }
  const byId = new Map(placed.map(item => [item.node.id, item]));
  const svg = document.getElementById("discoveryLinks");
  const nodeWrap = document.getElementById("discoveryNodes");
  if (!svg || !nodeWrap) return;
  svg.innerHTML = "";
  nodeWrap.innerHTML = "";

  links.forEach(link => {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", source.x);
    line.setAttribute("y1", source.y);
    line.setAttribute("x2", target.x);
    line.setAttribute("y2", target.y);
    line.setAttribute("class", `discovery-link discovery-link-${String(link.chat_policy || "planned").replace(/[^a-z0-9-]/gi, "-").toLowerCase()}`);
    if (link.count !== undefined) {
      const width = Math.min(2.2, 0.45 + Math.log10(Number(link.count || 1) + 1) * 0.23);
      line.style.strokeWidth = String(width);
    }
    svg.appendChild(line);
  });

  placed.forEach(({node, x, y}) => {
    const button = el("button", discoveryNodeClass(node), "");
    button.type = "button";
    button.style.left = `${x}%`;
    button.style.top = `${y}%`;
    button.dataset.discoveryNodeId = node.id;
    button.title = node.path || node.label || "Source";
    button.classList.toggle("is-selected", node.id === state.selectedDiscoveryNodeId);
    button.appendChild(el("span", "discovery-node-dot"));
    button.appendChild(el("span", "discovery-node-label", node.label || "Source"));
    button.onclick = () => selectDiscoveryNode(node.id);
    nodeWrap.appendChild(button);
  });

  renderDiscoveryDetail();
}

function selectedConstellationCardNode() {
  return (state.discoveryData?.nodes || []).find(node => node.id === state.selectedConstellationCardNodeId) || null;
}

function renderConstellationCardDetail() {
  const panel = document.getElementById("constellationCardDetail");
  if (!panel) return;
  panel.innerHTML = "";
  const node = selectedConstellationCardNode();
  if (!node) {
    panel.appendChild(dashboardLine("Focus", "Select a node in the card."));
    panel.appendChild(dashboardLine("Scope", "Files, memories, notes, clipboard, conversations, actions, sources."));
    return;
  }
  panel.appendChild(dashboardLine("Node", node.label || "Source"));
  panel.appendChild(dashboardLine("Kind", node.source_kind_label || node.group || "source"));
  panel.appendChild(dashboardLine("Chat", node.chat_policy_label || node.chat_policy || "planned"));
  if (node.metrics?.count !== undefined) panel.appendChild(dashboardLine("Count", formatCount(node.metrics.count)));
  if (node.metrics?.size_bytes !== undefined) panel.appendChild(dashboardLine("Size", formatBytes(node.metrics.size_bytes)));
  if (node.path) panel.appendChild(dashboardLine("Path", compactMiddle(node.path, 96)));
}

function selectConstellationCardNode(nodeId) {
  state.selectedConstellationCardNodeId = nodeId;
  document.querySelectorAll("#constellationMiniNodes .discovery-node").forEach(node => {
    node.classList.toggle("is-selected", node.dataset.constellationNodeId === nodeId);
  });
  renderConstellationCardDetail();
}

function renderConstellationCard(data = {}) {
  state.discoveryData = data;
  const nodes = data.nodes || [];
  const links = data.links || [];
  const summary = data.summary || {};
  const summaryNode = document.getElementById("constellationCardSummary");
  if (summaryNode) {
    summaryNode.textContent = `${formatCount(summary.nodes || nodes.length)} nodes | ${formatCount(summary.links || links.length)} links | ${formatCount(summary.active_files || 0)} active files | ${formatCount(summary.memories || 0)} memories | ${formatCount(summary.notes || 0)} notes`;
  }
  const selectedStillExists = nodes.some(node => node.id === state.selectedConstellationCardNodeId);
  if (!state.selectedConstellationCardNodeId || !selectedStillExists) {
    state.selectedConstellationCardNodeId = nodes.find(node => node.id === "core-archivist")?.id || nodes[0]?.id || null;
  }
  const placed = discoveryPositions(nodes);
  const byId = new Map(placed.map(item => [item.node.id, item]));
  const svg = document.getElementById("constellationMiniLinks");
  const nodeWrap = document.getElementById("constellationMiniNodes");
  if (!svg || !nodeWrap) return;
  svg.innerHTML = "";
  nodeWrap.innerHTML = "";
  links.forEach(link => {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target) return;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", source.x);
    line.setAttribute("y1", source.y);
    line.setAttribute("x2", target.x);
    line.setAttribute("y2", target.y);
    line.setAttribute("class", `discovery-link discovery-link-${String(link.chat_policy || "planned").replace(/[^a-z0-9-]/gi, "-").toLowerCase()}`);
    svg.appendChild(line);
  });
  placed.forEach(({node, x, y}) => {
    const button = el("button", `${discoveryNodeClass(node)} constellation-mini-node`, "");
    button.type = "button";
    button.style.left = `${x}%`;
    button.style.top = `${y}%`;
    button.dataset.constellationNodeId = node.id;
    button.title = node.path || node.label || "Source";
    button.classList.toggle("is-selected", node.id === state.selectedConstellationCardNodeId);
    button.appendChild(el("span", "discovery-node-dot"));
    button.appendChild(el("span", "discovery-node-label", node.label || "Source"));
    button.onclick = () => selectConstellationCardNode(node.id);
    nodeWrap.appendChild(button);
  });
  renderConstellationCardDetail();
}

async function loadConstellationCard() {
  try {
    const data = await getJSON("/api/constellation");
    renderConstellationCard(data);
  } catch (err) {
    const summary = document.getElementById("constellationCardSummary");
    const detail = document.getElementById("constellationCardDetail");
    if (summary) summary.textContent = "Constellation data unavailable.";
    if (detail) {
      detail.innerHTML = "";
      detail.appendChild(el("div", "compact-output", err.message));
    }
  }
}

function selectedDiscoveryNode() {
  return (state.discoveryData?.nodes || []).find(node => node.id === state.selectedDiscoveryNodeId) || null;
}

function selectDiscoveryNode(nodeId) {
  state.selectedDiscoveryNodeId = nodeId;
  document.querySelectorAll(".discovery-node").forEach(node => {
    node.classList.toggle("is-selected", node.dataset.discoveryNodeId === nodeId);
  });
  renderDiscoveryDetail();
}

function renderDiscoveryDetail() {
  const node = selectedDiscoveryNode();
  const title = document.getElementById("discoveryDetailTitle");
  const panel = document.getElementById("discoveryDetail");
  if (!title || !panel) return;
  panel.innerHTML = "";
  if (!node) {
    title.textContent = "Node Detail";
    panel.appendChild(el("div", "compact-output", "Select a node."));
    return;
  }
  title.textContent = node.label || "Source";
  if ((node.badges || []).length) panel.appendChild(discoveryBadges(node));
  const rows = [
    ["Path", node.path || "not applicable"],
    ["Health", node.health_label || node.health_status || "unknown"],
    ["Kind", node.source_kind_label || node.group || "source"],
    ["Chat", node.chat_policy_label || node.chat_policy || "planned"],
    ["Index", node.index_policy_label || node.index_policy || "planned"]
  ];
  rows.forEach(([label, value]) => panel.appendChild(dashboardLine(label, value)));
  if (node.metrics?.count !== undefined) panel.appendChild(dashboardLine("Count", formatCount(node.metrics.count)));
  if (node.metrics?.size_bytes !== undefined) panel.appendChild(dashboardLine("Size", formatBytes(node.metrics.size_bytes)));
  if (node.policy_reason) panel.appendChild(el("div", "compact-output", node.policy_reason));
  const actions = el("div", "discovery-actions");
  if (node.path) {
    const askBtn = el("button", null, "Ask chat");
    askBtn.type = "button";
    askBtn.onclick = () => {
      const input = document.getElementById("chatInput");
      if (input) {
        input.value = `Look at this constellation node and recommend what I should do with it: ${node.path}`;
        input.focus();
      }
    };
    actions.appendChild(askBtn);
  }
  (node.actions || []).forEach(action => {
    const button = el("button", null, action.label || action.key);
    button.type = "button";
    button.disabled = action.key === "planned";
    button.onclick = () => runDiscoveryAction(action, node);
    actions.appendChild(button);
  });
  if (actions.children.length) panel.appendChild(actions);
}

async function runDiscoveryAction(action, node) {
  if (!node?.path || action.key === "planned") return;
  const path = node.path;
  let message = "Save this source?";
  let request = null;
  if (action.key === "set_archive_root") {
    message = `Set archive root to ${path}? This takes effect after server restart.`;
    request = () => postJSON("/api/archive-locations/root", {path});
  } else if (action.key === "set_knowledgebase_root") {
    message = `Set knowledgebase root to ${path}? This takes effect after server restart.`;
    request = () => postJSON("/api/archive-locations/source", {slot: "knowledgebase_root", path});
  } else if (action.key === "save_chat_ignored") {
    message = `Save ${path} as a chat-ignored source?`;
    request = () => postJSON("/api/archive-locations/source", {slot: action.slot || "ignored_archive_root", path});
  }
  if (!request || !window.confirm(message)) return;
  try {
    await request();
    await loadArchiveLocations().catch(() => {});
    await loadDiscovery();
    appendMessage("assistant", `Constellation saved source setting for:\n${path}`);
  } catch (err) {
    const panel = document.getElementById("discoveryDetail");
    if (panel) panel.appendChild(el("div", "compact-output", err.message));
  }
}

async function loadDiscovery() {
  const data = await getJSON("/api/constellation");
  renderDiscovery(data);
}

function indexProgressGradient(progress) {
  const pct = Math.max(0, Math.min(100, Number(progress || 0)));
  if (pct <= 0) return "conic-gradient(var(--chart-empty) 0% 100%)";
  const stops = [`var(--type-1) 0% ${Math.min(pct, 34)}%`];
  if (pct > 34) stops.push(`var(--type-4) 34% ${Math.min(pct, 58)}%`);
  if (pct > 58) stops.push(`var(--type-2) 58% ${Math.min(pct, 82)}%`);
  if (pct > 82) stops.push(`var(--type-3) 82% ${pct}%`);
  stops.push(`var(--chart-empty) ${pct}% 100%`);
  return `conic-gradient(${stops.join(", ")})`;
}

function renderFileTypeDonut(categories) {
  const donut = document.getElementById("filetypeDonut");
  const legend = document.getElementById("filetypeLegend");
  if (!donut) return;
  const palette = [
    "var(--type-1)",
    "var(--type-2)",
    "var(--type-3)",
    "var(--type-4)",
    "var(--type-5)",
    "var(--type-6)",
    "var(--type-7)",
    "var(--type-8)"
  ];
  const total = categories.reduce((sum, item) => sum + Number(item.count || 0), 0);
  if (legend) legend.innerHTML = "";
  if (!total) {
    donut.style.background = "var(--chart-empty)";
    if (legend) legend.appendChild(el("div", "compact-output", "No file type data yet."));
    return;
  }
  let cursor = 0;
  const topCategories = categories.slice(0, 7);
  const stops = topCategories.map((item, index) => {
    const start = cursor;
    const end = cursor + (Number(item.count || 0) / total) * 100;
    cursor = end;
    return `${palette[index % palette.length]} ${start}% ${end}%`;
  });
  if (cursor < 100) stops.push(`var(--type-other) ${cursor}% 100%`);
  donut.style.background = `conic-gradient(${stops.join(", ")})`;
  if (!legend) return;
  topCategories.forEach((item, index) => {
    const count = Number(item.count || 0);
    const pct = total ? Math.round((count / total) * 100) : 0;
    const row = el("div", "legend-item");
    const swatch = el("span", "legend-swatch");
    swatch.style.background = palette[index % palette.length];
    row.appendChild(swatch);
    row.appendChild(el("span", "legend-label", item.category || "uncategorized"));
    row.appendChild(el("span", "legend-value", `${formatCount(count)} / ${pct}%`));
    legend.appendChild(row);
  });
  if (categories.length > topCategories.length) {
    const otherCount = categories.slice(topCategories.length).reduce((sum, item) => sum + Number(item.count || 0), 0);
    const row = el("div", "legend-item");
    const swatch = el("span", "legend-swatch");
    swatch.style.background = "var(--type-other)";
    row.appendChild(swatch);
    row.appendChild(el("span", "legend-label", "remaining"));
    row.appendChild(el("span", "legend-value", `${formatCount(otherCount)} / ${Math.round((otherCount / total) * 100)}%`));
    legend.appendChild(row);
  }
}

function renderTagOptions(tags) {
  state.tags = tags || [];
  const options = document.getElementById("tagOptions");
  options.innerHTML = "";
  state.tags.forEach(tag => {
    const option = el("option");
    option.value = tag.name;
    options.appendChild(option);
  });
}

function fileQueryParams() {
  const params = new URLSearchParams();
  const search = document.getElementById("fileSearch").value.trim();
  const category = document.getElementById("fileCategory").value;
  const filter = document.getElementById("fileFilter").value;
  const sort = document.getElementById("fileSort").value;
  if (search) params.set("q", search);
  if (category) params.set("category", category);
  if (filter === "duplicates") params.set("duplicates", "true");
  if (filter === "delete_queue") params.set("delete_queue", "true");
  params.set("sort", sort || "indexed_desc");
  params.set("limit", String(state.fileLimit));
  params.set("offset", String(state.fileOffset));
  return params;
}

function updateFilePager() {
  const start = state.fileTotal ? state.fileOffset + 1 : 0;
  const end = Math.min(state.fileOffset + state.fileLimit, state.fileTotal);
  document.getElementById("fileCount").textContent = `${formatCount(state.fileTotal)} files`;
  document.getElementById("filePageStatus").textContent = `${formatCount(start)}-${formatCount(end)} of ${formatCount(state.fileTotal)}`;
  document.getElementById("prevFilesBtn").disabled = state.fileOffset <= 0;
  document.getElementById("nextFilesBtn").disabled = state.fileOffset + state.fileLimit >= state.fileTotal;
}

function renderFiles(data) {
  const body = document.getElementById("fileTableBody");
  body.innerHTML = "";
  state.fileTotal = data.total || 0;
  state.selectedFileIds.clear();
  document.getElementById("selectAllFiles").checked = false;

  if (!(data.files || []).length) {
    const row = el("tr");
    const cell = el("td", null, "No files match the current view.");
    cell.colSpan = 6;
    row.appendChild(cell);
    body.appendChild(row);
    updateFilePager();
    return;
  }

  data.files.forEach(file => {
    const row = el("tr");
    row.draggable = true;
    row.dataset.fileId = String(file.id);
    if (file.deleted_candidate) row.classList.add("is-delete-candidate");
    row.addEventListener("dragstart", event => {
      event.dataTransfer.setData("text/plain", `file:${file.id}`);
      event.dataTransfer.setData("application/x-archivist-path", file.path || "");
    });

    const selectCell = el("td");
    const checkbox = el("input");
    checkbox.type = "checkbox";
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedFileIds.add(file.id);
      else state.selectedFileIds.delete(file.id);
      row.classList.toggle("is-selected", checkbox.checked);
    });
    selectCell.appendChild(checkbox);

    const nameCell = el("td");
    nameCell.appendChild(el("div", "file-name", file.name || "(unnamed)"));
    nameCell.appendChild(el("div", "file-path", file.display_path || file.path || ""));
    if (file.summary) nameCell.appendChild(el("div", "evidence-summary", file.summary));

    const categoryCell = el("td", null, file.category || "");
    const sizeCell = el("td", null, formatBytes(file.size_bytes));
    const tagsCell = el("td");
    const tagList = el("div", "tag-list");
    (file.tags || []).forEach(tag => tagList.appendChild(el("span", "tag-pill", tag)));
    tagsCell.appendChild(tagList);

    const actionsCell = el("td");
    const actions = el("div", "row-actions");
    const previewBtn = el("button", null, "Preview");
    previewBtn.type = "button";
    previewBtn.onclick = () => showPreview(file);
    actions.appendChild(previewBtn);
    const openLink = el("a", "button-link", "Open");
    openLink.href = `/api/file?path=${encodeURIComponent(file.path)}`;
    openLink.target = "_blank";
    actions.appendChild(openLink);

    const queueBtn = el("button", "danger-button", file.deleted_candidate ? "Queued" : "Queue delete");
    queueBtn.type = "button";
    queueBtn.dataset.queueDeleteBtn = "true";
    queueBtn.disabled = Boolean(file.deleted_candidate);
    queueBtn.onclick = () => queueDeletion([file.id], "Queued from maintenance file row");
    actions.appendChild(queueBtn);
    actionsCell.appendChild(actions);

    row.appendChild(selectCell);
    row.appendChild(nameCell);
    row.appendChild(categoryCell);
    row.appendChild(sizeCell);
    row.appendChild(tagsCell);
    row.appendChild(actionsCell);
    body.appendChild(row);
  });
  updateFilePager();
}

async function loadFiles() {
  const data = await getJSON(`/api/maintenance/files?${fileQueryParams().toString()}`);
  renderFiles(data);
}

function renderDuplicates(data) {
  const list = document.getElementById("duplicateList");
  list.innerHTML = "";
  document.getElementById("duplicateCount").textContent = `${formatCount(data.total || 0)} groups`;
  if (!(data.groups || []).length) {
    list.appendChild(el("div", "compact-output", "No exact duplicate groups in the current index."));
    return;
  }
  data.groups.forEach(group => {
    const card = el("div", "duplicate-group");
    const head = el("div", "duplicate-head");
    head.appendChild(el("div", "file-name", `${group.count} copies - ${formatBytes(group.reclaimable_bytes)} reclaimable`));
    const queueExtras = el("button", null, "Queue extras");
    queueExtras.type = "button";
    queueExtras.onclick = async () => {
      const extras = (group.files || []).slice(1).map(file => file.id);
      if (extras.length) await queueDeletion(extras, "Exact duplicate; queued from duplicate group");
    };
    head.appendChild(queueExtras);
    card.appendChild(head);

    const files = el("div", "duplicate-files");
    (group.files || []).forEach((file, index) => {
      const item = el("div", "duplicate-file");
      item.appendChild(el("div", null, `${index === 0 ? "Keep candidate" : "Duplicate"}: ${file.display_path || file.path}`));
      const preview = el("button", null, "Preview");
      preview.type = "button";
      preview.onclick = () => showPreview(file);
      item.appendChild(preview);
      files.appendChild(item);
    });
    card.appendChild(files);
    list.appendChild(card);
  });
}

async function loadDuplicates() {
  const data = await getJSON("/api/maintenance/duplicates?limit=20");
  renderDuplicates(data);
}

function renderFailures(data) {
  const list = document.getElementById("failureList");
  list.innerHTML = "";
  if (!(data.failures || []).length) {
    list.appendChild(el("div", "compact-output", "No recorded unresolved indexing issues."));
    return;
  }
  data.failures.forEach(failure => {
    const item = el("div", "failure-item");
    item.appendChild(el("div", "file-name", failure.display_path || failure.path || ""));
    item.appendChild(el("div", "evidence-summary", failure.error || ""));
    list.appendChild(item);
  });
}

async function loadFailures() {
  const data = await getJSON("/api/maintenance/failures?limit=20");
  renderFailures(data);
}

function renderPreDedupeStatus(job = {}) {
  const target = document.getElementById("preindexDedupeStatus");
  if (!target) return;
  if (!job.running && !job.done) {
    target.textContent = "Pre-index dedupe is idle.";
    return;
  }
  const elapsed = job.started_ts ? formatDuration(Math.max(0, (Date.now() / 1000) - job.started_ts)) : "";
  const stateText = job.running ? "Scanning" : "Scan complete";
  const current = job.current_path ? ` Current ${compactMiddle(job.current_path, 100)}.` : "";
  const issue = job.last_error ? ` Last issue: ${job.last_error}` : "";
  target.title = job.current_path || "";
  target.textContent = `${stateText}. Seen ${formatCount(job.total_seen)}. Unique ${formatCount(job.unique_count)}, duplicates ${formatCount(job.duplicate_count)}, queued ${formatCount(job.queued_count)}, reclaimable ${formatBytes(job.reclaimable_bytes)}, failed ${formatCount(job.failed_count)}.${elapsed ? ` Elapsed ${elapsed}.` : ""}${current}${issue}`;
}

async function pollPreDedupeStatus(refreshOnDone = true) {
  try {
    const job = await getJSON("/api/maintenance/dedupe/preindex-status");
    renderPreDedupeStatus(job);
    if (job.running) {
      state.preDedupePollTimer = setTimeout(pollPreDedupeStatus, 1500);
    } else {
      state.preDedupePollTimer = null;
      if (refreshOnDone && state.activeView === "maintenance") await loadMaintenance();
    }
  } catch (err) {
    renderPreDedupeStatus({done: true, last_error: err.message});
    state.preDedupePollTimer = null;
  }
}

async function startPreindexDedupe() {
  const confirmed = window.confirm("Run an exact SHA-256 scan before indexing? It only queues exact duplicates for review and does not delete files.");
  if (!confirmed) return;
  setStatus("Scanning");
  try {
    const data = await postURL("/api/maintenance/dedupe/preindex");
    renderPreDedupeStatus(data.job || {});
    if (!state.preDedupePollTimer) state.preDedupePollTimer = setTimeout(pollPreDedupeStatus, 500);
  } catch (err) {
    appendMessage("assistant", err.message);
    renderPreDedupeStatus({done: true, last_error: err.message});
  } finally {
    setStatus("Idle");
  }
}

async function loadMaintenance() {
  try {
    const [tags, models] = await Promise.all([
      getJSON("/api/maintenance/tags"),
      getJSON("/api/models").catch(() => null)
    ]);
    await loadStats();
    renderTagOptions(tags.tags || []);
    if (models) renderModelRoutes(models);
    await Promise.all([
      loadAdminControlStatus(),
      loadAdminConnect(),
      loadAdminEngineTools(),
      loadAdminDevelopmentTasks(),
      loadHostStats(),
      loadFaceReview(),
      loadArchiveLocations().catch(err => {
        document.getElementById("archiveLocationStatus").textContent = `${err.message}. Archive location controls will be available after the next server restart.`;
      }),
      loadFiles(),
      loadDuplicates(),
      loadFailures()
    ]);
    const preDedupe = await getJSON("/api/maintenance/dedupe/preindex-status").catch(() => null);
    if (preDedupe) renderPreDedupeStatus(preDedupe);
  } catch (err) {
    setMaintenanceNotice(`${err.message}. If indexing is still running on the older server process, these maintenance routes will appear after the next server restart.`);
  }
}

function explorerStateLabel(item) {
  const bits = [];
  if (item.kind === "directory") bits.push("folder");
  else bits.push(item.indexed ? "indexed" : "not indexed");
  if (item.deleted_candidate) bits.push("delete queue");
  if (item.duplicate_of) bits.push("duplicate");
  return bits.join(", ");
}

function renderExplorer(data) {
  state.explorerPath = data.path || null;
  state.explorerParent = data.parent || null;
  state.explorerRoot = data.archive_root || state.explorerRoot;
  document.getElementById("explorerPathInput").value = data.path || "";
  document.getElementById("explorerStatus").textContent = `${data.rel_path || data.path || "Archive root"} - ${formatCount((data.items || []).length)} shown of ${formatCount(data.total || 0)}`;
  document.getElementById("explorerUpBtn").disabled = !data.parent;

  const body = document.getElementById("explorerTableBody");
  body.innerHTML = "";
  if (!(data.items || []).length) {
    const row = el("tr");
    const cell = el("td", null, "This folder is empty.");
    cell.colSpan = 6;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  data.items.forEach(item => {
    const row = el("tr");
    row.draggable = true;
    row.dataset.path = item.path || "";
    row.classList.toggle("is-delete-candidate", Boolean(item.deleted_candidate));
    row.addEventListener("dragstart", event => {
      event.dataTransfer.setData("text/plain", item.path || "");
      event.dataTransfer.setData("application/x-archivist-path", item.path || "");
    });
    row.addEventListener("dblclick", () => {
      if (item.kind === "directory") loadExplorer(item.path);
      else showPreview(item);
    });

    const nameCell = el("td");
    nameCell.appendChild(el("div", "file-name", `${item.kind === "directory" ? "[DIR] " : ""}${item.name || "(unnamed)"}`));
    nameCell.appendChild(el("div", "file-path", item.rel_path || item.path || ""));

    const typeCell = el("td", null, item.category || item.kind || "");
    const sizeCell = el("td", null, item.kind === "directory" ? "" : formatBytes(item.size_bytes));
    const modifiedCell = el("td", null, shortTime(item.modified_ts));
    const stateCell = el("td", null, explorerStateLabel(item));
    const actionsCell = el("td");
    const actions = el("div", "row-actions");

    if (item.kind === "directory") {
      const openBtn = el("button", null, "Open");
      openBtn.type = "button";
      openBtn.onclick = () => loadExplorer(item.path);
      actions.appendChild(openBtn);
    } else {
      const previewBtn = el("button", null, "Preview");
      previewBtn.type = "button";
      previewBtn.onclick = () => showPreview(item);
      actions.appendChild(previewBtn);

      const loadBtn = el("button", null, "Write");
      loadBtn.type = "button";
      loadBtn.onclick = () => loadCowriterFromPath(item.path);
      actions.appendChild(loadBtn);

      const openLink = el("a", "button-link", "Open");
      openLink.href = `/api/file?path=${encodeURIComponent(item.path)}`;
      openLink.target = "_blank";
      actions.appendChild(openLink);

      const queueBtn = el("button", "danger-button", "Queue");
      queueBtn.type = "button";
      queueBtn.onclick = async () => {
        const confirmed = window.confirm("Queue this file for deletion review? This will not delete it from disk.");
        if (!confirmed) return;
        await postJSON("/api/maintenance/delete-queue-path", {path: item.path, reason: "Queued from file explorer"});
        await loadExplorer(state.explorerPath);
      };
      actions.appendChild(queueBtn);
    }

    actionsCell.appendChild(actions);
    row.appendChild(nameCell);
    row.appendChild(typeCell);
    row.appendChild(sizeCell);
    row.appendChild(modifiedCell);
    row.appendChild(stateCell);
    row.appendChild(actionsCell);
    body.appendChild(row);
  });
}

async function loadExplorer(path = null) {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  try {
    const data = await getJSON(`/api/explorer?${params.toString()}`);
    renderExplorer(data);
  } catch (err) {
    document.getElementById("explorerStatus").textContent = `${err.message}. File Explorer routes will be available after the next server restart.`;
  }
}

async function applyTagToSelection(remove = false) {
  const ids = selectedFileIds();
  const tag = document.getElementById("tagInput").value.trim();
  if (!ids.length || !tag) return;
  const url = remove ? "/api/maintenance/tags/remove" : "/api/maintenance/tags/apply";
  await postJSON(url, {file_ids: ids, tag});
  await refreshFileMaintenance({duplicates: false});
}

async function queueDeletion(ids = selectedFileIds(), reason = "Queued from maintenance workbench") {
  if (!ids.length) return;
  const confirmed = window.confirm(`Queue ${ids.length} file(s) for deletion review? This does not permanently delete files.`);
  if (!confirmed) return;
  const result = await postJSON("/api/maintenance/delete-queue", {file_ids: ids, reason});
  markFileRowsQueued(ids, true);
  if (activeFileFilter() === "delete_queue") removeFileRows(ids);
  appendMessage("assistant", `Queued ${formatCount(result.queued ?? ids.length)} file(s) for deletion review.`);
  await refreshFileMaintenance({files: true, duplicates: true, stats: true});
}

async function queuePreviewDeletion() {
  if (!state.previewPath) return;
  const confirmed = window.confirm("Queue the currently previewed file for deletion review? This will not delete it from disk.");
  if (!confirmed) return;
  const queuedIds = state.previewFileId ? [state.previewFileId] : [];
  if (state.previewFileId) {
    await postJSON("/api/maintenance/delete-queue", {file_ids: [state.previewFileId], reason: "Queued from preview pane"});
  } else {
    await postJSON("/api/maintenance/delete-queue-path", {path: state.previewPath, reason: "Queued from preview pane"});
  }
  if (queuedIds.length) markFileRowsQueued(queuedIds, true);
  const queueBtn = document.getElementById("queuePreviewDeleteBtn");
  if (queueBtn) {
    queueBtn.textContent = "Queued";
    queueBtn.disabled = true;
  }
  appendMessage("assistant", `Queued for deletion review:\n${state.previewPath}`);
  if (state.activeView === "maintenance") await refreshFileMaintenance({files: true, duplicates: true, stats: true});
}

async function clearDeletionQueue() {
  const ids = selectedFileIds();
  if (!ids.length) return;
  const result = await postJSON("/api/maintenance/delete-unqueue", {file_ids: ids});
  if (activeFileFilter() === "delete_queue") removeFileRows(ids);
  else markFileRowsQueued(ids, false);
  appendMessage("assistant", `Cleared ${formatCount(result.cleared ?? ids.length)} file(s) from deletion review.`);
  await refreshFileMaintenance({files: true, duplicates: true, stats: true});
}

async function queueExactDuplicates() {
  const confirmed = window.confirm("Queue all exact SHA-256 duplicate copies for deletion review? This will keep one copy per exact content hash and will not delete files from disk.");
  if (!confirmed) return;
  const result = await postJSON("/api/maintenance/dedupe/queue-exact");
  appendMessage("assistant", `Queued ${result.queued || 0} exact duplicate files across ${result.groups || 0} groups for review. Potential review size: ${formatBytes(result.reclaimable_bytes)}.`);
  await refreshFileMaintenance({files: true, duplicates: true, stats: true});
}

async function moveQueuedDuplicates() {
  const confirmed = window.confirm("Move queued exact duplicates into the archive review folder and remove empty source folders? This moves files but does not permanently delete them.");
  if (!confirmed) return;
  try {
    const result = await postJSON("/api/maintenance/dedupe/move-queued", {dry_run: false, remove_empty_folders: true});
    appendMessage("assistant", `Moved ${formatCount(result.moved || 0)} queued duplicate files into review.\nReview folder: ${result.review_dir}\nEmpty folders removed: ${formatCount(result.empty_folders_removed || 0)}\nMoved size: ${formatBytes(result.reclaimable_bytes)}.`);
    await refreshFileMaintenance({files: true, duplicates: true, stats: true});
  } catch (err) {
    appendMessage("assistant", err.message);
  }
}

function contextualQueryForView(view, query) {
  const context = {
    audio: "Archive > Audio context: answer as an audio-aware Archivist assistant for listening, recording, transcript, clipping, and audio note workflows.",
    video: "Archive > Video context: answer as a video-aware Archivist assistant for playback, light editing, captions, media creation, and scene notes.",
    forensics: "Archive forensics context: answer as a file forensics Archivist assistant for OCR, metadata, identity review, duplicate evidence, and cautious confidence levels.",
    tools: "Archive tools context: answer as an admin-oriented Archivist assistant for local and remote systems, recovery, network shares, worker nodes, and audited actions."
  }[view];
  return context ? `${context}\n\nUser request: ${query}` : query;
}

async function sendChat(query, displayQuery = query) {
  setStatus("Thinking");
  appendMessage("user", displayQuery);
  try {
    const data = await postJSON("/api/chat", {query, conversation_id: state.conversationId});
    saveConversationId(data.conversation_id);
    appendMessage("assistant", data.answer || "", data.thinking);
    speakEffect();
    renderEvidence(data);
    await loadConversations();
    await loadMemories();
    await loadDashboard();
    setStatus("Idle");
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
}

function renderIndexStatus(job) {
  const status = document.getElementById("indexStatus");
  const bar = document.getElementById("indexProgressBar");
  if (!status || !bar) return;
  const track = bar.parentElement;
  const seen = job.total_seen || 0;
  const queuedTotal = job.total_files || 0;
  const indexed = job.indexed_count || 0;
  const duplicates = job.duplicate_count || 0;
  const skipped = job.skipped_count || 0;
  const failed = job.failed_count || 0;
  const pending = job.pending_count || 0;

  const elapsed = job.started_ts ? Math.max(0, (Date.now() / 1000) - job.started_ts) : 0;
  const estimate = queuedTotal || Math.max(state.indexEstimate, seen || 0);
  const progress = estimate ? Math.min(100, (seen / estimate) * 100) : 0;
  const etaSeconds = job.running && seen > 0 ? Math.max(0, (elapsed / seen) * (estimate - seen)) : 0;
  const activelyWorking = Boolean(job.running || job.building_queue || job.pause_requested || job.throttle_active);
  track.classList.toggle("is-running", activelyWorking);
  bar.style.width = activelyWorking || job.done || job.paused ? `${progress}%` : "0";
  const chart = document.getElementById("telemetryChart");
  const donut = document.getElementById("indexDonut");
  const percent = document.getElementById("indexPercent");
  const progressDeg = (progress / 100) * 360;
  if (chart) {
    chart.classList.toggle("is-indexing", activelyWorking);
    chart.style.setProperty("--progress-deg", `${progressDeg}deg`);
    chart.style.setProperty("--progress-neg", `${-progressDeg}deg`);
  }
  if (donut) {
    donut.style.background = indexProgressGradient(progress);
  }
  if (percent) percent.textContent = `${Math.round(progress)}%`;
  renderSchedulerStatus(job.scheduler || {});

  if (!activelyWorking && !job.done && !job.paused) {
    status.textContent = "No index running.";
    return;
  }

  let stateText = "Index complete";
  if (job.building_queue) stateText = "Snapshotting queue";
  else if (job.pause_requested) stateText = "Pausing at next checkpoint";
  else if (job.paused) stateText = "Paused";
  else if (job.throttle_active) stateText = "Waiting for chat idle";
  else if (job.running) stateText = "Indexing";
  const current = job.current_path ? ` Current ${compactMiddle(job.current_path, 110)}.` : "";
  const error = job.last_error ? ` Last issue: ${job.last_error}` : "";
  const totalPart = queuedTotal ? ` of ${formatCount(queuedTotal)}` : "";
  status.title = job.current_path || "";
  status.textContent = `${stateText}. Seen ${formatCount(seen)}${totalPart}. Pending ${formatCount(pending)}. Indexed ${formatCount(indexed)}, duplicates ${formatCount(duplicates)}, skipped ${formatCount(skipped)}, failed ${formatCount(failed)}.${current}${error}`;
  const eta = document.getElementById("indexEta");
  if (eta) {
    if (job.throttle_active && job.scheduler?.seconds_until_full_speed) {
      eta.textContent = `Index will resume full speed after ${formatDuration(job.scheduler.seconds_until_full_speed)} without chat activity.`;
    } else if (job.running && etaSeconds) {
      eta.textContent = `Approx ETA ${formatDuration(etaSeconds)}. Estimate uses ${formatCount(estimate)} expected files.`;
    } else if (job.paused) {
      eta.textContent = "Paused. Resume continues from the persisted queue.";
    } else if (job.building_queue) {
      eta.textContent = "Building a durable queue snapshot before model work starts.";
    } else {
      eta.textContent = "ETA unavailable.";
    }
  }
}

function renderSchedulerStatus(scheduler = {}) {
  const toggle = document.getElementById("throttleIndexToggle");
  const minutes = document.getElementById("chatIdleMinutes");
  const status = document.getElementById("indexSchedulerStatus");
  if (!toggle || !minutes || !status) return;
  if (!Object.prototype.hasOwnProperty.call(scheduler, "throttle_enabled")) {
    status.textContent = "Chat priority controls will activate after the server restarts onto the updated backend.";
    return;
  }
  if (typeof scheduler.throttle_enabled === "boolean") toggle.checked = scheduler.throttle_enabled;
  if (scheduler.chat_idle_seconds && document.activeElement !== minutes) {
    minutes.value = Math.max(1, Math.round(Number(scheduler.chat_idle_seconds) / 60));
  }
  if (!scheduler.throttle_enabled) {
    status.textContent = "Chat priority is off. Indexing will run whenever it is active.";
    return;
  }
  if (scheduler.throttle_active) {
    status.textContent = `Chat priority active. Full-speed indexing resumes in ${formatDuration(scheduler.seconds_until_full_speed || 0)}.`;
    return;
  }
  status.textContent = `Chat priority is on. Indexing waits after chat for ${Math.max(1, Math.round(Number(scheduler.chat_idle_seconds || 180) / 60))} minute(s).`;
}

async function saveIndexScheduler() {
  const enabled = document.getElementById("throttleIndexToggle").checked;
  const minutes = Math.max(1, Number(document.getElementById("chatIdleMinutes").value || 3));
  try {
    const scheduler = await postJSON("/api/index-scheduler", {
      throttle_enabled: enabled,
      chat_idle_seconds: Math.round(minutes * 60)
    });
    renderSchedulerStatus(scheduler);
  } catch (err) {
    appendMessage("assistant", err.message);
  }
}

async function recategorizeArchiveTypes() {
  setStatus("Fixing types");
  try {
    const result = await postJSON("/api/maintenance/recategorize");
    await loadMaintenance();
    appendMessage("assistant", `Archive type pass complete. Scanned ${formatCount(result.scanned || 0)} rows, changed ${formatCount(result.category_changed || 0)} categories, and repaired ${formatCount(result.ext_changed || 0)} extension labels.`);
    setStatus("Idle");
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
}

function formatDuration(seconds) {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (hours > 24) return `${Math.round(hours / 24)}d ${hours % 24}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

async function pollIndexStatus() {
  try {
    const job = await getJSON("/api/index-status");
    renderIndexStatus(job);
    if (job.running || job.building_queue || job.pause_requested || job.throttle_active) {
      setStatus(job.throttle_active ? "Indexing paused for chat" : "Indexing");
      state.indexPollTimer = setTimeout(pollIndexStatus, 1500);
    } else {
      setStatus("Idle");
      state.indexPollTimer = null;
    }
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
    state.indexPollTimer = null;
  }
}

async function pauseIndex() {
  setStatus("Indexing");
  try {
    const data = await postURL("/api/index-pause");
    renderIndexStatus(data.job || {});
    if (!state.indexPollTimer) state.indexPollTimer = setTimeout(pollIndexStatus, 500);
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
}

async function resumeIndex() {
  setStatus("Starting index");
  try {
    const data = await postURL("/api/index-resume");
    renderIndexStatus(data.job || {});
    if (!state.indexPollTimer) state.indexPollTimer = setTimeout(pollIndexStatus, 500);
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  setStatus("Ingesting");
  try {
    const res = await fetch("/api/upload", {method: "POST", body: form});
    const data = await readJSON(res);
    const out = document.getElementById("uploadResult");
    out.innerHTML = "";
    appendField(out, "Uploaded", data.uploaded_to);
    appendField(out, "Folder", data.suggested_folder);
    if (data.face_scan) appendField(out, "Faces", `${formatCount(data.face_scan.face_count || 0)} detected`);
    if (data.auto_tags?.tags?.length) appendField(out, "Tags", data.auto_tags.tags.join(", "));

    const accept = el("button", null, "Accept");
    accept.type = "button";
    accept.onclick = async () => {
      try {
        const saved = await postURL(`/api/accept-upload-placement?temp_path=${encodeURIComponent(data.uploaded_to)}&rel_folder=${encodeURIComponent(data.suggested_folder)}`);
        appendField(out, "Saved", saved.saved_to);
        if (saved.record?.face_scan) appendField(out, "Saved faces", `${formatCount(saved.record.face_scan.face_count || 0)} detected`);
        if (saved.record?.auto_tags?.tags?.length) appendField(out, "Saved tags", saved.record.auto_tags.tags.join(", "));
      } catch (err) {
        appendField(out, "Issue", err.message);
      }
    };

    const reject = el("button", null, "Review");
    reject.type = "button";
    reject.onclick = async () => {
      try {
        const moved = await postURL(`/api/reject-upload-placement?temp_path=${encodeURIComponent(data.uploaded_to)}`);
        appendField(out, "Review", moved.moved_to_review);
      } catch (err) {
        appendField(out, "Issue", err.message);
      }
    };

    out.appendChild(accept);
    out.appendChild(reject);
    if (data.preview_path) showPreview(data.preview_path);
    const input = document.getElementById("chatInput");
    if (input) {
      input.value = `${input.value.trim()}\n\nAttached file: ${data.uploaded_to}\nSummary: ${data.summary || ""}`.trim();
    }
    setStatus("Idle");
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
}

function renderIngestQueueStatus(current = null) {
  const out = document.getElementById("uploadResult");
  if (!out) return;
  out.innerHTML = "";
  const total = state.ingestQueueTotal || state.ingestQueue.length;
  const done = state.ingestQueueDone || 0;
  appendField(out, "Ingest queue", `${formatCount(done)} of ${formatCount(total)} processed`);
  if (current) appendField(out, "Current", current.name);
}

function enqueueUploads(files) {
  const incoming = Array.from(files || []);
  if (!incoming.length) return;
  state.ingestQueue.push(...incoming);
  state.ingestQueueTotal = (state.ingestQueueTotal || 0) + incoming.length;
  renderIngestQueueStatus();
  processIngestQueue();
}

async function processIngestQueue() {
  if (state.ingestRunning) return;
  state.ingestRunning = true;
  state.ingestQueueDone = state.ingestQueueDone || 0;
  try {
    while (state.ingestQueue.length) {
      const file = state.ingestQueue.shift();
      renderIngestQueueStatus(file);
      await uploadFile(file);
      state.ingestQueueDone += 1;
      renderIngestQueueStatus();
    }
    if (state.activeView === "maintenance") await loadMaintenance();
  } finally {
    state.ingestRunning = false;
    state.ingestQueueTotal = 0;
    state.ingestQueueDone = 0;
  }
}

function appendDroppedPathToChat(path) {
  const input = document.getElementById("chatInput");
  if (!input || !path) return;
  input.value = `${input.value.trim()}\n\nAttached archive file: ${path}`.trim();
  input.focus();
}

function appendDroppedTextToChat(text) {
  const input = document.getElementById("chatInput");
  const cleanText = String(text || "").trim();
  if (!input || !cleanText) return;
  input.value = `${input.value.trim()}\n\n${cleanText}`.trim();
  input.focus();
}

function wireDropTarget(node, options = {}) {
  if (!node) return;
  node.addEventListener("dragover", event => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    node.classList.add("is-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", async event => {
    event.preventDefault();
    node.classList.remove("is-over");
    if (event.dataTransfer.files.length) {
      enqueueUploads(event.dataTransfer.files);
      return;
    }
    if (options.pathToChat) {
      const path = extractDroppedPath(event.dataTransfer);
      if (path) appendDroppedPathToChat(path);
      else appendDroppedTextToChat(event.dataTransfer.getData("text/plain") || event.dataTransfer.getData("text/uri-list"));
    }
  });
}

function wireDeleteDropTarget(node) {
  if (!node) return;
  node.addEventListener("dragover", event => {
    event.preventDefault();
    const types = Array.from(event.dataTransfer.types || []);
    event.dataTransfer.dropEffect = types.includes("Files") ? "copy" : "move";
    node.classList.add("is-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", async event => {
    event.preventDefault();
    node.classList.remove("is-over");
    if (event.dataTransfer.files.length) {
      enqueueUploads(event.dataTransfer.files);
      return;
    }
    const data = event.dataTransfer.getData("text/plain") || "";
    if (!data.startsWith("file:")) return;
    const id = Number(data.slice(5));
    if (Number.isFinite(id)) await queueDeletion([id], "Dragged to deletion review");
  });
}

function extractDroppedPath(dataTransfer) {
  const archivistPath = dataTransfer.getData("application/x-archivist-path");
  if (archivistPath) return archivistPath;
  const text = dataTransfer.getData("text/plain") || dataTransfer.getData("text/uri-list") || "";
  const match = text.match(/[A-Za-z]:\\[^\n\r]+/);
  if (match) return match[0].trim();
  try {
    const url = new URL(text.trim(), window.location.href);
    const path = url.searchParams.get("path");
    if (path) return path;
  } catch {
    return "";
  }
  return "";
}

function wireCowriterEditorDrop(node) {
  if (!node) return;
  node.addEventListener("dragover", event => {
    event.preventDefault();
    node.classList.add("is-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("is-over"));
  node.addEventListener("drop", async event => {
    event.preventDefault();
    node.classList.remove("is-over");
    if (event.dataTransfer.files.length) {
      await importCowriterDroppedFile(event.dataTransfer.files[0]);
      return;
    }
    const path = extractDroppedPath(event.dataTransfer);
    if (path) await loadCowriterFromPath(path);
  });
}

document.getElementById("chatForm").addEventListener("submit", async event => {
  event.preventDefault();
  const input = document.getElementById("chatInput");
  const query = input.value.trim();
  if (!query) return;
  if (state.activeView === "chat") {
    await askCowriter("ask");
  } else {
    input.value = "";
    if (maybeNavigateFromChat(query)) return;
    await sendChat(contextualQueryForView(state.activeView, query), query);
  }
});

document.getElementById("newChatBtn").onclick = newConversation;
document.getElementById("toggleThreadsBtn").onclick = () => {
  const section = document.getElementById("threadsSection");
  const isCollapsed = section.classList.toggle("is-collapsed");
  document.getElementById("toggleThreadsBtn").textContent = isCollapsed ? "Show" : "Hide";
};
document.getElementById("openDraftBtn").onclick = loadCowriterDocument;
document.getElementById("saveDraftBtn").onclick = () => saveCowriterDocument(false);
document.getElementById("saveVersionBtn").onclick = saveCowriterVersion;
document.getElementById("refreshTimelineBtn").onclick = loadCowriterTimeline;
document.getElementById("askCowriterBtn").onclick = () => askCowriter("ask");
document.getElementById("editSelectionBtn").onclick = () => askCowriter("edit");
document.getElementById("askSelectionBtn").onclick = () => askCowriter("selection");
document.getElementById("helpWriteBtn").onclick = () => askCowriter("help");
document.getElementById("previewDraftBtn").onclick = () => askCowriter("preview");
document.getElementById("clearCowriterChatBtn").onclick = () => {
  newConversation();
};
document.getElementById("cowriterEditor").addEventListener("input", () => {
  window.clearTimeout(state.cowriterAutosaveTimer);
  state.cowriterAutosaveTimer = window.setTimeout(() => saveCowriterDocument(true).catch(() => {}), 2000);
});

document.getElementById("indexAllBtn").onclick = async () => {
  const force = document.getElementById("forceIndex").checked;
  setStatus("Starting index");
  try {
    const data = await postJSON(`/api/index-all?force=${force ? "true" : "false"}`);
    renderIndexStatus(data.job);
    if (!state.indexPollTimer) state.indexPollTimer = setTimeout(pollIndexStatus, 500);
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
};

document.getElementById("pauseIndexBtn").onclick = pauseIndex;
document.getElementById("resumeIndexBtn").onclick = resumeIndex;
document.getElementById("saveSchedulerBtn").onclick = saveIndexScheduler;
document.getElementById("recategorizeBtn").onclick = recategorizeArchiveTypes;

document.getElementById("wipeIndexBtn").onclick = async () => {
  const confirmed = confirmWithNumber(
    "Wipe the archive file index and archive embeddings? Chat threads, notes, clipboard items, and memories will be preserved."
  );
  if (!confirmed) return;
  setStatus("Wiping index");
  try {
    const data = await postJSON("/api/index-wipe");
    renderIndexStatus(data.job);
    renderEvidence({});
    const snapshot = data.snapshot || {};
    const snapshotText = snapshot.manifest_path
      ? `\nSnapshot manifest: ${snapshot.manifest_path}\nSnapshot folder: ${snapshot.snapshot_dir}`
      : "\nSnapshot was requested, but no snapshot path was returned by the server.";
    appendMessage("assistant", `Archive index snapshot saved before wipe.${snapshotText}\n\nArchive index wiped. Removed ${data.cleared.files || 0} file rows and reset archive embeddings.`);
    setStatus("Idle");
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
};

document.getElementById("uploadBtn").onclick = async () => {
  const input = document.getElementById("fileInput");
  if (input.files.length) {
    enqueueUploads(input.files);
    input.value = "";
  }
};

document.querySelectorAll(".mode-tab").forEach(button => {
  button.addEventListener("click", () => {
    const view = button.dataset.view || "home";
    setView(view, {topView: view});
  });
});

document.querySelectorAll(".subtab").forEach(button => {
  button.addEventListener("click", () => {
    if (button.disabled) return;
    const group = button.closest(".subtab-group");
    setView(button.dataset.view || "home", {
      topView: group?.dataset.subtabsFor || topNavViewFor(button.dataset.view || "home"),
      scrollCard: button.dataset.scrollCard || ""
    });
  });
});

document.querySelectorAll(".jumpViewBtn").forEach(button => {
  button.addEventListener("click", () => setView(button.dataset.jumpView || "home"));
});

let fileSearchTimer = null;
document.getElementById("fileSearch").addEventListener("input", () => {
  window.clearTimeout(fileSearchTimer);
  fileSearchTimer = window.setTimeout(() => {
    state.fileOffset = 0;
    loadFiles();
  }, 250);
});

["fileCategory", "fileFilter", "fileSort"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => {
    state.fileOffset = 0;
    loadFiles();
  });
});

document.getElementById("selectAllFiles").addEventListener("change", event => {
  const checked = event.target.checked;
  state.selectedFileIds.clear();
  document.querySelectorAll("#fileTableBody tr").forEach(row => {
    const id = Number(row.dataset.fileId);
    const checkbox = row.querySelector("input[type='checkbox']");
    if (!checkbox || !Number.isFinite(id)) return;
    checkbox.checked = checked;
    row.classList.toggle("is-selected", checked);
    if (checked) state.selectedFileIds.add(id);
  });
});

document.getElementById("prevFilesBtn").onclick = () => {
  state.fileOffset = Math.max(0, state.fileOffset - state.fileLimit);
  loadFiles();
};

document.getElementById("nextFilesBtn").onclick = () => {
  if (state.fileOffset + state.fileLimit < state.fileTotal) {
    state.fileOffset += state.fileLimit;
    loadFiles();
  }
};

document.getElementById("maintenanceRefreshBtn").onclick = loadMaintenance;
document.getElementById("themeToggleBtn").onclick = toggleTheme;
document.getElementById("clipboardPasteBtn").onclick = pasteClipboardText;
document.getElementById("clipboardSaveBtn").onclick = () => saveClipboardText(document.getElementById("clipboardInput").value, "manual");
document.getElementById("clipboardClearBtn").onclick = clearClipboard;
document.getElementById("clipboardScrollUpBtn").onclick = () => scrollClipboard(-1);
document.getElementById("clipboardScrollDownBtn").onclick = () => scrollClipboard(1);
document.getElementById("clipboardInput").addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    saveClipboardText(event.target.value, "manual");
  }
});
document.getElementById("newNoteBtn").onclick = createBlankNote;
document.getElementById("refreshNotesBtn").onclick = loadNotes;
document.getElementById("refreshModelsBtn").onclick = loadModels;
document.getElementById("refreshLocationsBtn").onclick = loadArchiveLocations;
document.getElementById("refreshDashboardBtn").onclick = loadDashboard;
document.getElementById("refreshDrivesBtn").onclick = loadDrives;
document.getElementById("driveImportBtn").onclick = driveImportSelected;
window.setTimeout(startDrivePoll, 500);
document.getElementById("refreshConstellationCardBtn").onclick = loadConstellationCard;
document.getElementById("discoveryRefreshBtn").onclick = loadDiscovery;
document.getElementById("adminChatForm").addEventListener("submit", event => {
  event.preventDefault();
  const input = document.getElementById("adminChatInput");
  const prompt = input.value.trim();
  if (!prompt) return;
  input.value = "";
  sendAdminEngine(prompt, "plan");
});
document.getElementById("adminRunBtn").onclick = () => {
  const input = document.getElementById("adminChatInput");
  const prompt = input.value.trim();
  if (!prompt) return;
  input.value = "";
  sendAdminEngine(prompt, "run");
};
document.querySelectorAll(".adminQuickBtn").forEach(button => {
  button.addEventListener("click", () => sendAdminEngine(button.dataset.adminPrompt || button.textContent || "", button.dataset.adminMode || "plan"));
});
document.getElementById("adminRefreshControlBtn").onclick = loadAdminControlStatus;
document.getElementById("refreshAdminToolsBtn").onclick = loadAdminEngineTools;
document.getElementById("adminFreeGpuBtn").onclick = freeAdminGpu;
document.getElementById("adminRestartServerBtn").onclick = () => requestAdminServerAction("restart");
document.getElementById("adminStopServerBtn").onclick = () => requestAdminServerAction("stop");
document.getElementById("adminGeneratePairCodeBtn").onclick = startAdminConnect;
document.getElementById("adminCopyPairCodeBtn").onclick = () => copyTextToSystem(state.adminConnect?.local_code || "");
document.getElementById("adminResetPairCodeBtn").onclick = resetAdminConnect;
document.getElementById("adminVerifyPairCodeBtn").onclick = verifyAdminConnect;
document.getElementById("adminRemoteCodeInput").addEventListener("keydown", event => {
  if (event.key === "Enter") verifyAdminConnect();
});
document.getElementById("adminDetectHardwareBtn").onclick = loadInstallerProfile;
document.getElementById("adminCopyInstallerPlanBtn").onclick = () => copyTextToSystem(installerPlanText());
document.getElementById("adminDevRefreshBtn").onclick = loadAdminDevelopmentTasks;
document.getElementById("adminDevSeedBtn").onclick = seedAdminDevelopmentTasks;
document.getElementById("adminDevNextBtn").onclick = runNextAdminDevelopmentTask;
document.getElementById("adminDevTaskAddBtn").onclick = createAdminDevelopmentTask;
document.getElementById("adminDevTaskTitleInput").addEventListener("keydown", event => {
  if (event.key === "Enter") createAdminDevelopmentTask();
});
document.getElementById("hostStatsRefreshBtn").onclick = () => loadHostStats();
document.getElementById("hostStatsSaveBtn").onclick = saveHostStatsSettings;
document.getElementById("refreshFaceReviewBtn").onclick = loadFaceReview;
document.getElementById("backfillFacesBtn").onclick = backfillFaces;
document.getElementById("createFacePersonBtn").onclick = createFacePerson;
document.getElementById("createFaceObservationBtn").onclick = createFaceObservation;
document.getElementById("detectFaceFileBtn").onclick = detectFaceFile;
document.getElementById("detectObjectFileBtn").onclick = detectObjectFile;
document.getElementById("linkFacePersonBtn").onclick = linkSelectedFacePerson;
document.getElementById("facePersonNameInput").addEventListener("keydown", event => {
  if (event.key === "Enter") createFacePerson();
});
document.getElementById("faceObservationPathInput").addEventListener("keydown", event => {
  if (event.key === "Enter") createFaceObservation();
});
document.getElementById("videoProbeBtn").onclick = loadVideoContext;
document.getElementById("videoLoadContextBtn").onclick = loadVideoContext;
document.getElementById("videoAnalyzeBtn").onclick = analyzeVideoContext;
document.getElementById("videoTranscribeBtn").onclick = transcribeVideoContext;
document.getElementById("videoScanArchiveBtn").onclick = startVideoArchiveScan;
document.getElementById("videoStopScanBtn").onclick = stopVideoArchiveScan;
document.getElementById("videoSearchBtn").onclick = searchVideoContext;
document.getElementById("videoSearchSubmitBtn").onclick = searchVideoContext;
document.getElementById("videoSaveSegmentBtn").onclick = saveVideoSegment;
document.getElementById("videoPathInput").addEventListener("keydown", event => {
  if (event.key === "Enter") loadVideoContext();
});
document.getElementById("videoSearchInput").addEventListener("keydown", event => {
  if (event.key === "Enter") searchVideoContext();
});
document.getElementById("videoPresetSelect").addEventListener("change", event => {
  applyVideoPreset(event.target.value);
});
document.querySelectorAll(".browseLocationBtn").forEach(button => {
  button.addEventListener("click", () => {
    const inputId = button.dataset.targetInput;
    const value = document.getElementById(inputId)?.value.trim() || "";
    loadLocationBrowser(value || null, inputId);
  });
});
document.querySelectorAll(".saveLocationSlotBtn").forEach(button => {
  button.addEventListener("click", () => saveLocationSlot(button.dataset.locationSlot, button.dataset.targetInput));
});
document.querySelectorAll("input[data-location-slot]").forEach(input => {
  input.addEventListener("keydown", event => {
    if (event.key === "Enter") saveLocationSlot(input.dataset.locationSlot, input.id);
  });
});
document.getElementById("explorerRefreshBtn").onclick = () => loadExplorer(state.explorerPath);
document.getElementById("explorerRootBtn").onclick = () => loadExplorer(null);
document.getElementById("explorerUpBtn").onclick = () => loadExplorer(state.explorerParent);
document.getElementById("explorerGoBtn").onclick = () => loadExplorer(document.getElementById("explorerPathInput").value.trim());
document.getElementById("explorerPathInput").addEventListener("keydown", event => {
  if (event.key === "Enter") loadExplorer(event.target.value.trim());
});
document.getElementById("applyTagBtn").onclick = () => applyTagToSelection(false);
document.getElementById("removeTagBtn").onclick = () => applyTagToSelection(true);
document.getElementById("queueDeleteBtn").onclick = () => queueDeletion();
document.getElementById("clearDeleteBtn").onclick = clearDeletionQueue;
document.getElementById("preindexDedupeBtn").onclick = startPreindexDedupe;
document.getElementById("moveQueuedDupesBtn").onclick = moveQueuedDuplicates;
document.getElementById("queueExactDupesBtn").onclick = queueExactDuplicates;
document.getElementById("queuePreviewDeleteBtn").onclick = queuePreviewDeletion;
document.getElementById("closePreviewBtn").onclick = closePreview;

wireDropTarget(document.getElementById("avatarStage"));
wireDropTarget(document.getElementById("maintenanceDropzone"));
wireDeleteDropTarget(document.getElementById("deleteDropzone"));
wireDropTarget(document.getElementById("chatForm"), {pathToChat: true});
wireCowriterEditorDrop(document.getElementById("cowriterEditor"));
wireVideoPathDrop(document.getElementById("videoPathInput"));
wireClipboardDropTarget(document.getElementById("clipboardDropzone"));
wireClipboardInputPaste(document.getElementById("clipboardInput"));
wireNotesDropTarget(document.getElementById("notesDropzone"));
wireMaintenanceCardReordering();
wireHomeCardReordering();
wireLeftRailCardReordering();
applyTheme(savedTheme());

(async function boot() {
  try {
    closePreview();
    await loadConversations();
    if (state.conversationId) await loadConversation(state.conversationId);
    else renderMessages([]);
    await loadMemories();
    await loadDashboard();
    await loadConstellationCard();
    await loadModels();
    await loadClipboard();
    await loadCowriterDocument();
    await loadCowriterTimeline();
    if (state.activeView === "maintenance") await loadMaintenance();
    if (state.activeView === "discovery") await loadDiscovery();
    if (state.activeView === "notes") await loadNotes();
    renderAdminChat();
    await pollIndexStatus();
  } catch (err) {
    appendMessage("assistant", err.message);
    setStatus("Idle");
  }
})();
