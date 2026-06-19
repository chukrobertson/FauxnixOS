const state = {
  route: "home",
  back: [],
  forward: [],
  pointer: null,
  user: "chvk",
  apiOk: false,
  lastEventId: 0,
};

const API_BASE = "http://127.0.0.1:8756/api";

const routeNames = {
  home: "Home",
  weather: "Weather",
  status: "Status",
  calendar: "Calendar",
  telemetry: "Telemetry",
  threads: "Threads",
};

const shell = document.getElementById("shell");
const routeLabel = document.getElementById("routeLabel");
const backButton = document.getElementById("backButton");
const forwardButton = document.getElementById("forwardButton");
const homeButton = document.getElementById("homeButton");
const gestureRing = document.getElementById("gestureRing");

async function apiGet(path) {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Fauxd ${response.status}`);
  }
  return response.json();
}

async function apiPost(path, payload) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Fauxd ${response.status}`);
  }
  return data;
}

async function nativeAction(action) {
  try {
    await apiPost("/action", { action });
    return;
  } catch (error) {
    console.warn("fauxd action fallback", error);
  }
  if (window.webkit?.messageHandlers?.fauxshell) {
    window.webkit.messageHandlers.fauxshell.postMessage(action);
    return;
  }
  console.info("fauxshell action", action);
}

function setRoute(route, options = {}) {
  if (!routeNames[route]) {
    route = "home";
  }
  if (route === state.route && !options.force) {
    return;
  }
  if (!options.replace) {
    state.back.push(state.route);
    state.forward = [];
  }
  state.route = route;
  renderRoute();
}

function renderRoute() {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("active", view.dataset.view === state.route);
  });
  routeLabel.textContent = routeNames[state.route] || "Home";
  backButton.disabled = state.back.length === 0;
  forwardButton.disabled = state.forward.length === 0;
}

function goHome() {
  setRoute("home");
}

function goBack() {
  if (state.back.length === 0) {
    return;
  }
  state.forward.push(state.route);
  state.route = state.back.pop();
  renderRoute();
}

function goForward() {
  if (state.forward.length === 0) {
    return;
  }
  state.back.push(state.route);
  state.route = state.forward.pop();
  renderRoute();
}

function updateClock() {
  const now = new Date();
  const greeting = document.getElementById("greeting");
  const clockLine = document.getElementById("clockLine");
  const hour = now.getHours();
  const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
  greeting.textContent = `Good ${part}, ${state.user}.`;
  clockLine.textContent = now.toLocaleString([], {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function setGauge(id, value, labelId) {
  const gauge = document.getElementById(id);
  const numeric = typeof value === "number" && Number.isFinite(value);
  const percent = numeric ? Math.max(0, Math.min(100, value)) : 0;
  if (gauge) {
    gauge.style.setProperty("--value", String(Math.round(percent)));
  }
  if (labelId) {
    setText(labelId, numeric ? `${Math.round(percent)}%` : "--");
  }
}

function formatAge(seconds) {
  if (!seconds) {
    return "";
  }
  const delta = Math.max(0, Math.floor(Date.now() / 1000) - seconds);
  if (delta < 60) {
    return "now";
  }
  if (delta < 3600) {
    return `${Math.floor(delta / 60)}m`;
  }
  if (delta < 86400) {
    return `${Math.floor(delta / 3600)}h`;
  }
  return `${Math.floor(delta / 86400)}d`;
}

function makeButton(className, text, action) {
  const button = document.createElement("button");
  button.className = className;
  button.textContent = text;
  if (action) {
    button.dataset.action = action;
  }
  return button;
}

function renderSessions(data) {
  const target = document.getElementById("sessionsList");
  if (!target) {
    return;
  }
  target.textContent = "";
  const sessions = data?.recent || [];
  if (!sessions.length) {
    target.appendChild(makeButton("session-row", "Open Fennix local assistant", "thread:fennix"));
    return;
  }
  for (const session of sessions) {
    const suffix = formatAge(session.updated_at);
    target.appendChild(makeButton("session-row", `${session.title}${suffix ? `  -  ${suffix}` : ""}`, session.action));
  }
}

function renderNotes(data) {
  const count = data?.count || 0;
  const notes = data?.recent || [];
  setText("notesSummary", count ? `${count} saved note${count === 1 ? "" : "s"}` : "No saved notes yet");
  const target = document.getElementById("notesList");
  if (!target) {
    return;
  }
  target.textContent = "";
  for (const note of notes) {
    const suffix = formatAge(note.updated_at);
    target.appendChild(makeButton("session-row", `${note.title}${suffix ? `  -  ${suffix}` : ""}`, "notes"));
  }
}

function renderThreads(threads) {
  const target = document.getElementById("threadsGrid");
  if (!target || !Array.isArray(threads)) {
    return;
  }
  target.textContent = "";
  for (const thread of threads) {
    target.appendChild(makeButton("", thread.label, thread.action));
  }
}

function renderWeather(weather) {
  const configured = Boolean(weather?.configured);
  const symbol = weather?.symbol || "--";
  const summary = weather?.summary || "Set weather location";
  const location = weather?.location || "";
  setText("weatherSymbol", configured ? symbol : "--");
  setText("weatherSummary", summary);
  setText("weatherDetailSummary", summary);
  setText("weatherDetailLocation", location ? `Location: ${location}` : "Location not set");
}

function renderSummary(summary) {
  state.apiOk = true;
  state.user = summary.user || state.user;
  const telemetry = summary.telemetry || {};
  setText("netState", telemetry.network_text || "n/a");
  setText("audioState", telemetry.audio_text || "n/a");
  setText("powerState", telemetry.battery_text || "n/a");
  setText("telemetryDetails", `Network ${telemetry.network_text || "n/a"}  Audio ${telemetry.audio_text || "n/a"}  RAM ${telemetry.memory_text || "n/a"}`);
  setGauge("cpuGauge", telemetry.cpu_percent, "cpuValue");
  setGauge("ramGauge", telemetry.memory_percent, "ramValue");
  setGauge("loadGauge", telemetry.load_percent, "loadValue");
  setGauge("detailCpuGauge", telemetry.cpu_percent, "detailCpuValue");
  setGauge("detailRamGauge", telemetry.memory_percent, "detailRamValue");
  setGauge("detailBatteryGauge", telemetry.battery_percent, "detailBatteryValue");
  setGauge("detailLoadGauge", telemetry.load_percent, "detailLoadValue");
  renderWeather(summary.weather);
  renderSessions(summary.sessions);
  renderNotes(summary.notes);
  renderThreads(summary.threads);
  updateClock();
}

async function refreshSummary() {
  try {
    const summary = await apiGet("/summary");
    if (summary.ok) {
      renderSummary(summary);
    }
  } catch (error) {
    state.apiOk = false;
    setText("netState", "fauxd offline");
    setText("audioState", "n/a");
    setText("powerState", "n/a");
    setText("telemetryDetails", "Waiting for Fauxd");
    setText("weatherSymbol", "--");
    setText("weatherSummary", "Weather unavailable");
    console.warn("fauxd summary unavailable", error);
  }
}

function applyShellEvent(eventName) {
  if (eventName === "nav:back") {
    goBack();
  } else if (eventName === "nav:forward") {
    goForward();
  } else if (eventName === "nav:home") {
    goHome();
  } else if (eventName === "nav:threads") {
    setRoute("threads");
  }
}

async function pollEvents() {
  try {
    const data = await apiGet(`/events?since=${state.lastEventId}`);
    if (!data.ok || !Array.isArray(data.events)) {
      return;
    }
    for (const event of data.events) {
      state.lastEventId = Math.max(state.lastEventId, Number(event.id) || 0);
      if (event.type === "shell") {
        applyShellEvent(event.payload?.event);
      }
    }
  } catch (error) {
    console.warn("fauxd events unavailable", error);
  }
}

function buildCalendar(targetId) {
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }
  target.textContent = "";
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const first = new Date(year, month, 1);
  const start = first.getDay();
  const days = new Date(year, month + 1, 0).getDate();
  for (const label of ["S", "M", "T", "W", "T", "F", "S"]) {
    const cell = document.createElement("span");
    cell.textContent = label;
    target.appendChild(cell);
  }
  for (let i = 0; i < start; i += 1) {
    target.appendChild(document.createElement("span"));
  }
  for (let day = 1; day <= days; day += 1) {
    const cell = document.createElement("span");
    cell.textContent = String(day);
    if (day === now.getDate()) {
      cell.classList.add("today");
    }
    target.appendChild(cell);
  }
}

function gestureStart(event) {
  const isMouseGesture = event.pointerType === "mouse" && event.button === 2;
  const isTouchGesture = event.pointerType === "touch" || event.pointerType === "pen";
  if (!isMouseGesture && !isTouchGesture) {
    return;
  }
  state.pointer = {
    id: event.pointerId,
    type: event.pointerType,
    x: event.clientX,
    y: event.clientY,
    time: performance.now(),
  };
  shell.setPointerCapture?.(event.pointerId);
  gestureRing.style.left = `${event.clientX}px`;
  gestureRing.style.top = `${event.clientY}px`;
  gestureRing.classList.add("active");
  event.preventDefault();
}

function gestureMove(event) {
  if (!state.pointer || state.pointer.id !== event.pointerId) {
    return;
  }
  gestureRing.style.left = `${event.clientX}px`;
  gestureRing.style.top = `${event.clientY}px`;
}

function gestureEnd(event) {
  if (!state.pointer || state.pointer.id !== event.pointerId) {
    return;
  }
  const dx = event.clientX - state.pointer.x;
  const dy = event.clientY - state.pointer.y;
  const elapsed = performance.now() - state.pointer.time;
  state.pointer = null;
  gestureRing.classList.remove("active");

  const absX = Math.abs(dx);
  const absY = Math.abs(dy);
  if (elapsed > 900 || Math.max(absX, absY) < 82) {
    return;
  }
  if (absX > absY * 1.4) {
    if (dx > 0) {
      goBack();
    } else {
      goForward();
    }
  } else if (dy > 0 && absY > absX * 1.4) {
    goHome();
  }
  event.preventDefault();
}

document.addEventListener("contextmenu", (event) => {
  if (state.pointer) {
    event.preventDefault();
  }
});

document.addEventListener("click", (event) => {
  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    nativeAction(actionButton.dataset.action);
    return;
  }

  const routeButton = event.target.closest("[data-route-target]");
  if (routeButton) {
    setRoute(routeButton.dataset.routeTarget);
    return;
  }

  const routeCard = event.target.closest("[data-route]");
  if (routeCard) {
    setRoute(routeCard.dataset.route);
  }
});

backButton.addEventListener("click", goBack);
forwardButton.addEventListener("click", goForward);
homeButton.addEventListener("click", goHome);
shell.addEventListener("pointerdown", gestureStart);
shell.addEventListener("pointermove", gestureMove);
shell.addEventListener("pointerup", gestureEnd);
shell.addEventListener("pointercancel", () => {
  state.pointer = null;
  gestureRing.classList.remove("active");
});

updateClock();
buildCalendar("calendarGrid");
buildCalendar("largeCalendar");
renderRoute();
refreshSummary();
setInterval(updateClock, 15000);
setInterval(refreshSummary, 3000);
setInterval(pollEvents, 250);
