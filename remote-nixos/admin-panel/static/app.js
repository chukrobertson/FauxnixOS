const state = {
  lastStatus: null,
};

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes || 0);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function serviceClass(value) {
  return value === "active" ? "ok" : "bad";
}

function setText(id, value, className = "") {
  const node = document.getElementById(id);
  node.textContent = value;
  node.className = className;
}

function renderUrls(status) {
  const urls = document.getElementById("urls");
  const all = [status.loopbackUrl, ...(status.lanUrls || [])].filter(Boolean);
  urls.innerHTML = "";
  if (all.length === 0) {
    urls.textContent = "No network URLs reported yet.";
    return;
  }
  for (const url of all) {
    const a = document.createElement("a");
    a.href = url;
    a.textContent = url;
    urls.appendChild(a);
  }

  const archivistUrls = document.getElementById("archivist-urls");
  const archivist = status.archivist || {};
  const archivistAll = [archivist.loopbackUrl, ...(archivist.lanUrls || [])].filter(Boolean);
  archivistUrls.innerHTML = "";
  if (archivistAll.length) {
    const label = document.createElement("span");
    label.textContent = "Archivist:";
    archivistUrls.appendChild(label);
    for (const url of archivistAll) {
      const a = document.createElement("a");
      a.href = url;
      a.textContent = url;
      archivistUrls.appendChild(a);
    }
  }
}

function updateArchivistLink() {
  const link = document.getElementById("archivist-link");
  const host = window.location.hostname || "127.0.0.1";
  link.href = `http://${host}:8776/`;
}

function renderProcesses(status) {
  const chunks = [];
  for (const [name, lines] of Object.entries(status.processes || {})) {
    chunks.push(`${name}:`);
    if (!lines.length) {
      chunks.push("  not running");
    } else {
      for (const line of lines) chunks.push(`  ${line}`);
    }
  }
  document.getElementById("processes").textContent = chunks.join("\n");
}

function render(status) {
  state.lastStatus = status;
  setText("host", status.hostname || "Fauxnix Node");
  setText("system", status.currentSystem || "No current system path reported.");
  setText("display", status.services["display-manager"], serviceClass(status.services["display-manager"]));
  setText("node-service", status.services["fauxnix-admin-panel"], serviceClass(status.services["fauxnix-admin-panel"]));
  setText("archivist-service", status.services["fauxnix-archivist-web"], serviceClass(status.services["fauxnix-archivist-web"]));
  setText("ollama", status.services.ollama, serviceClass(status.services.ollama));
  setText("tailscale", status.services.tailscaled, serviceClass(status.services.tailscaled));
  setText("uptime", status.systemUptime || `${status.serverUptimeSeconds}s server uptime`);
  setText("disk", `${formatBytes(status.disk.used)} used of ${formatBytes(status.disk.total)} (${status.disk.percent}%)`);
  updateArchivistLink();
  renderUrls(status);
  renderProcesses(status);
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    render(await response.json());
  } catch (error) {
    setText("system", `Status request failed: ${error.message}`, "bad");
  }
}

async function launch(action) {
  const result = document.getElementById("action-result");
  result.textContent = `Launching ${action}...`;
  try {
    const response = await fetch(`/api/actions/${action}`, { method: "POST" });
    const payload = await response.json();
    result.textContent = payload.ok ? `Launched ${action}.` : payload.error;
    result.className = payload.ok ? "subtle ok" : "subtle bad";
    if (payload.ok && payload.url) {
      window.location.href = payload.url;
    }
  } catch (error) {
    result.textContent = error.message;
    result.className = "subtle bad";
  }
}

/* ── Wall Display Admin ── */

function wallUrl(path) {
  const host = window.location.hostname || '127.0.0.1';
  return `http://${host}:8780${path}`;
}

async function wallFetch(path, options) {
  const resp = await fetch(wallUrl(path), { cache: 'no-store', ...options });
  return resp.json();
}

async function loadWallSettings() {
  try {
    const data = await wallFetch('/api/settings');
    document.getElementById('wall-zipcode').value = data.zipcode || '';
    document.getElementById('wall-cal-url').value = data.calendar_ics_url || '';
    document.getElementById('wall-status').textContent =
      data.sync_status === 'ok' ? 'synced' : data.sync_status || 'no sync';
    if (data.last_sync) {
      const ago = Math.round((Date.now() - new Date(data.last_sync).getTime()) / 60000);
      document.getElementById('wall-status').textContent += ` (${ago}m ago)`;
    }
  } catch {
    document.getElementById('wall-status').textContent = 'offline';
  }
}

async function saveWallSetting(key, value) {
  const result = document.getElementById('wall-result');
  result.textContent = `Saving ${key}...`;
  try {
    const data = await wallFetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value }),
    });
    result.textContent = data.ok ? `${key} saved.` : data.error;
    result.className = data.ok ? 'subtle ok' : 'subtle bad';
  } catch (err) {
    result.textContent = err.message;
    result.className = 'subtle bad';
  }
}

async function syncCalendar() {
  const result = document.getElementById('wall-result');
  result.textContent = 'Syncing calendar...';
  result.className = 'subtle';
  try {
    const data = await wallFetch('/api/calendar/sync', { method: 'POST' });
    result.textContent = data.ok
      ? `Synced! ${data.event_count} events loaded.`
      : data.error;
    result.className = data.ok ? 'subtle ok' : 'subtle bad';
    loadWallSettings();
  } catch (err) {
    result.textContent = err.message;
    result.className = 'subtle bad';
  }
}

document.getElementById('wall-zipcode-save').addEventListener('click', () => {
  saveWallSetting('zipcode', document.getElementById('wall-zipcode').value.trim());
});

document.getElementById('wall-cal-save').addEventListener('click', () => {
  saveWallSetting('calendar_ics_url', document.getElementById('wall-cal-url').value.trim());
});

document.getElementById('wall-sync').addEventListener('click', syncCalendar);

document.getElementById('wall-open').addEventListener('click', () => {
  const host = window.location.hostname || '127.0.0.1';
  window.open(`http://${host}:8780/`, '_blank');
});

/* ── Agent Chat ── */

const chatState = { history: [] };

async function loadAgentStatus() {
  const statusEl = document.getElementById("agent-status");
  try {
    const resp = await fetch(agentUrl("/api/status"), { cache: "no-store" });
    const data = await resp.json();
    statusEl.textContent = data.ok ? `online (${data.models.length} models)` : "offline";
    statusEl.className = data.ok ? "hint ok" : "hint bad";
    if (data.models.length) {
      const select = document.getElementById("chat-model");
      select.innerHTML = "";
      for (const m of data.models) {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (m === "llama3.2" || m.includes("llama")) opt.selected = true;
        select.appendChild(opt);
      }
    }
  } catch {
    statusEl.textContent = "offline";
    statusEl.className = "hint bad";
  }
}

function agentUrl(path) {
  const host = window.location.hostname || "127.0.0.1";
  return `http://${host}:8757${path}`;
}

async function sendChatMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addChatMessage("user", text);
  const sendBtn = document.getElementById("chat-send");
  sendBtn.disabled = true;
  sendBtn.textContent = "Waiting...";
  try {
    const resp = await fetch(agentUrl("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: chatState.history }),
    });
    const data = await resp.json();
    if (data.ok) {
      addChatMessage("assistant", data.response);
      chatState.history.push({ role: "user", content: text });
      chatState.history.push({ role: "assistant", content: data.response });
    } else {
      addChatMessage("error", data.error || "Request failed");
    }
  } catch (err) {
    addChatMessage("error", err.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send";
  }
}

function addChatMessage(role, text) {
  const container = document.getElementById("chat-messages");
  const msg = document.createElement("div");
  msg.className = `chat-msg ${role}`;
  const body = document.createElement("div");
  body.className = "chat-msg-body";
  body.textContent = text;
  msg.appendChild(body);
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

document.getElementById("chat-send").addEventListener("click", sendChatMessage);
document.getElementById("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
  }
});

/* ── Drive Inbox ── */

let driveState = { devices: [], mounts: {}, browsePath: null, selectedFiles: new Set() };

async function loadDrives() {
  const statusEl = document.getElementById("drive-status");
  const errorEl = document.getElementById("drive-error");
  try {
    const resp = await fetch("/api/drives", { cache: "no-store" });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "API error");
    driveState.devices = data.devices || [];
    driveState.mounts = data.mounts || {};
    statusEl.textContent = `${driveState.devices.length} drive(s)`;
    errorEl.style.display = "none";
    renderDriveList();
  } catch (err) {
    statusEl.textContent = "error";
    errorEl.textContent = err.message;
    errorEl.style.display = "block";
  }
}

function renderDriveList() {
  const container = document.getElementById("drive-list");
  container.innerHTML = "";
  for (const dev of driveState.devices) {
    const parts = dev.partitions.length ? dev.partitions : [dev];
    for (const part of parts) {
      const mountPoint = driveState.mounts[part.device] || "";
      const item = document.createElement("div");
      item.className = "drive-item";
      item.innerHTML = `
        <span class="drive-icon">${dev.removable ? "💾" : "💽"}</span>
        <div class="drive-info">
          <div class="drive-name">${part.device}</div>
          <div class="drive-detail">${dev.model || dev.vendor || "block device"} &middot; ${part.sizeHuman}${mountPoint ? ` &middot; mounted at ${mountPoint}` : ""}</div>
        </div>
        ${mountPoint
          ? `<button class="drive-unmount-btn" data-device="${part.device}">Unmount</button><button class="drive-browse-btn" data-path="${mountPoint}">Browse</button>`
          : `<button class="drive-mount-btn" data-device="${part.device}">Mount</button>`
        }
      `;
      container.appendChild(item);
    }
  }
  // Event listeners
  for (const btn of container.querySelectorAll(".drive-mount-btn")) {
    btn.addEventListener("click", () => mountDrive(btn.dataset.device));
  }
  for (const btn of container.querySelectorAll(".drive-unmount-btn")) {
    btn.addEventListener("click", () => unmountDrive(btn.dataset.device));
  }
  for (const btn of container.querySelectorAll(".drive-browse-btn")) {
    btn.addEventListener("click", () => browseDrive(btn.dataset.path));
  }
}

async function mountDrive(device) {
  const resultEl = document.getElementById("drive-result");
  resultEl.textContent = `Mounting ${device}...`;
  try {
    const resp = await fetch("/api/drives/mount", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device }),
    });
    const data = await resp.json();
    resultEl.textContent = data.ok ? `Mounted at ${data.mountPoint}` : data.error;
    resultEl.className = data.ok ? "subtle ok" : "subtle bad";
    loadDrives();
    if (data.ok && data.mountPoint) browseDrive(data.mountPoint);
  } catch (err) {
    resultEl.textContent = err.message;
    resultEl.className = "subtle bad";
  }
}

async function unmountDrive(device) {
  const resultEl = document.getElementById("drive-result");
  resultEl.textContent = `Unmounting ${device}...`;
  try {
    const resp = await fetch("/api/drives/unmount", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device }),
    });
    const data = await resp.json();
    resultEl.textContent = data.ok ? "Unmounted." : data.error;
    resultEl.className = data.ok ? "subtle ok" : "subtle bad";
    loadDrives();
    document.getElementById("drive-browse").style.display = "none";
  } catch (err) {
    resultEl.textContent = err.message;
    resultEl.className = "subtle bad";
  }
}

async function browseDrive(dirPath) {
  const resultEl = document.getElementById("drive-result");
  const browseEl = document.getElementById("drive-browse");
  resultEl.textContent = "";
  driveState.selectedFiles = new Set();
  updateSelectedBar();
  try {
    const resp = await fetch("/api/drives/browse?" + new URLSearchParams({ path: dirPath }), { cache: "no-store" });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error);
    driveState.browsePath = data.currentPath;
    renderBreadcrumb(data.currentPath);
    renderFileList(data.entries);
    browseEl.style.display = "flex";
  } catch (err) {
    resultEl.textContent = err.message;
    resultEl.className = "subtle bad";
  }
}

function renderBreadcrumb(currentPath) {
  const container = document.getElementById("drive-breadcrumb");
  const parts = currentPath.split("/").filter(Boolean);
  let accumulated = "";
  const crumbs = [];
  for (const part of parts) {
    accumulated += "/" + part;
    crumbs.push({ name: part, path: accumulated });
  }
  container.innerHTML = "";
  const rootLink = document.createElement("a");
  rootLink.textContent = "󰊘";
  rootLink.onclick = () => browseDrive("/");
  container.appendChild(rootLink);
  for (const crumb of crumbs) {
    const sep = document.createElement("span");
    sep.textContent = " / ";
    container.appendChild(sep);
    const link = document.createElement("a");
    link.textContent = crumb.name;
    link.onclick = () => browseDrive(crumb.path);
    container.appendChild(link);
  }
}

function renderFileList(entries) {
  const container = document.getElementById("drive-file-list");
  container.innerHTML = "";
  if (!entries.length) {
    container.innerHTML = '<div class="drive-file-row" style="color:var(--muted);padding:16px;text-align:center">Empty directory</div>';
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "drive-file-row" + (entry.isDir ? " is-dir" : "");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.path = entry.path;
    if (driveState.selectedFiles.has(entry.path)) checkbox.checked = true;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) driveState.selectedFiles.add(entry.path);
      else driveState.selectedFiles.delete(entry.path);
      updateSelectedBar();
    });
    row.appendChild(checkbox);
    const nameSpan = document.createElement("span");
    nameSpan.className = "file-name";
    nameSpan.textContent = entry.name + (entry.isDir ? "/" : "");
    if (entry.isDir) {
      nameSpan.addEventListener("dblclick", () => browseDrive(entry.path));
    }
    row.appendChild(nameSpan);
    const sizeSpan = document.createElement("span");
    sizeSpan.className = "file-size";
    sizeSpan.textContent = entry.sizeHuman;
    row.appendChild(sizeSpan);
    container.appendChild(row);
  }
}

function updateSelectedBar() {
  const count = driveState.selectedFiles.size;
  document.getElementById("drive-selected-count").textContent = `${count} selected`;
  document.getElementById("drive-import-btn").disabled = count === 0;
}

async function driveImportSelected() {
  const paths = Array.from(driveState.selectedFiles);
  const resultEl = document.getElementById("drive-result");
  resultEl.textContent = `Importing ${paths.length} file(s)...`;
  try {
    const resp = await fetch("/api/drives/import-multi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error);
    const ok = data.results.filter(r => r.ok).length;
    const fail = data.results.filter(r => !r.ok).length;
    resultEl.textContent = `${ok} imported${fail ? `, ${fail} failed` : ""}.`;
    resultEl.className = "subtle ok";
    driveState.selectedFiles = new Set();
    updateSelectedBar();
    browseDrive(driveState.browsePath);
  } catch (err) {
    resultEl.textContent = err.message;
    resultEl.className = "subtle bad";
  }
}

document.getElementById("drive-import-btn").addEventListener("click", driveImportSelected);

function tickClock() {
  const now = new Date();
  document.getElementById("time").textContent = now.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  document.getElementById("date").textContent = now.toLocaleDateString([], {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

document.getElementById("refresh").addEventListener("click", refresh);
for (const button of document.querySelectorAll("[data-action]")) {
  button.addEventListener("click", () => launch(button.dataset.action));
}

tickClock();
refresh();
loadWallSettings();
loadDrives();
loadAgentStatus();
setInterval(tickClock, 1000);
setInterval(refresh, 10000);
setInterval(loadWallSettings, 15000);
setInterval(loadDrives, 10000);
setInterval(loadAgentStatus, 15000);
