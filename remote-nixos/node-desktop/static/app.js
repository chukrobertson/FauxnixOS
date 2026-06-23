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
  setText("node-service", status.services["fauxnix-node-desktop"], serviceClass(status.services["fauxnix-node-desktop"]));
  setText("ollama", status.services.ollama, serviceClass(status.services.ollama));
  setText("tailscale", status.services.tailscaled, serviceClass(status.services.tailscaled));
  setText("uptime", status.systemUptime || `${status.serverUptimeSeconds}s server uptime`);
  setText("disk", `${formatBytes(status.disk.used)} used of ${formatBytes(status.disk.total)} (${status.disk.percent}%)`);
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
  } catch (error) {
    result.textContent = error.message;
    result.className = "subtle bad";
  }
}

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
setInterval(tickClock, 1000);
setInterval(refresh, 10000);
