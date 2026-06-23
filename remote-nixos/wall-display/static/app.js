/* ── State ── */

const state = {
  events: [],
  today: new Date(),
  viewMonth: new Date().getMonth(),
  viewYear: new Date().getFullYear(),
};

/* ── Helpers ── */

function pad(n) { return String(n).padStart(2, '0'); }

function apiURL(path) {
  const port = window.location.port || '8780';
  return `http://${window.location.hostname}:${port}${path}`;
}

/* ── Clock ── */

function tickClock() {
  const now = new Date();
  document.getElementById('time').textContent = now.toLocaleTimeString([], {
    hour: 'numeric', minute: '2-digit',
  });
  document.getElementById('date').textContent = now.toLocaleDateString([], {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  });
}

/* ── Calendar ── */

function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function renderCalendar() {
  const { viewYear, viewMonth } = state;
  const today = state.today;
  const firstDow = new Date(viewYear, viewMonth, 1).getDay();
  const totalDays = daysInMonth(viewMonth, viewYear);
  const prevDays = daysInMonth(viewMonth === 0 ? viewYear - 1 : viewYear, viewMonth === 0 ? 11 : viewMonth - 1);

  document.getElementById('month-title').textContent =
    new Date(viewYear, viewMonth).toLocaleDateString([], { month: 'long', year: 'numeric' });

  const tbody = document.getElementById('calendar-body');
  tbody.innerHTML = '';

  const eventMap = {};
  for (const ev of state.events) {
    const d = new Date(ev.date);
    const key = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    if (!eventMap[key]) eventMap[key] = [];
    eventMap[key].push(ev);
  }

  let row = document.createElement('tr');
  for (let i = 0; i < firstDow; i++) {
    const td = document.createElement('td');
    td.className = 'other-month';
    const span = document.createElement('span');
    span.className = 'day-num';
    span.textContent = prevDays - firstDow + 1 + i;
    td.appendChild(span);
    row.appendChild(td);
  }

  for (let day = 1; day <= totalDays; day++) {
    const dateObj = new Date(viewYear, viewMonth, day);
    const key = `${dateObj.getFullYear()}-${pad(dateObj.getMonth() + 1)}-${pad(dateObj.getDate())}`;
    const hasEv = eventMap[key] && eventMap[key].length > 0;
    const isToday =
      day === today.getDate() && viewMonth === today.getMonth() && viewYear === today.getFullYear();

    const td = document.createElement('td');
    if (isToday) td.className = 'today';
    if (hasEv) td.classList.add('has-events');
    const span = document.createElement('span');
    span.className = 'day-num';
    span.textContent = day;
    td.appendChild(span);
    row.appendChild(td);

    if (row.children.length === 7) {
      tbody.appendChild(row);
      row = document.createElement('tr');
    }
  }

  // Fill remaining cells
  const remaining = 7 - row.children.length;
  if (remaining < 7) {
    for (let i = 1; i <= remaining; i++) {
      const td = document.createElement('td');
      td.className = 'other-month';
      const span = document.createElement('span');
      span.className = 'day-num';
      span.textContent = i;
      td.appendChild(span);
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }

  renderTodayEvents();
}

/* ── Events ── */

function renderTodayEvents() {
  const list = document.getElementById('events-list');
  const { viewYear, viewMonth } = state;

  // Show events for the selected day (or today if viewing current month)
  const isCurrentMonth =
    viewMonth === state.today.getMonth() && viewYear === state.today.getFullYear();
  const targetDay = isCurrentMonth ? state.today.getDate() : null;

  const todayEvents = state.events.filter(ev => {
    const d = new Date(ev.date);
    if (isCurrentMonth && targetDay) {
      return d.getFullYear() === viewYear && d.getMonth() === viewMonth && d.getDate() === targetDay;
    }
    // Show all events in the viewed month if not current
    return d.getFullYear() === viewYear && d.getMonth() === viewMonth;
  });

  // Sort by time
  todayEvents.sort((a, b) => (a.time || '00:00').localeCompare(b.time || '00:00'));

  list.innerHTML = '';
  if (todayEvents.length === 0) {
    list.innerHTML = '<p class="subtle">No events</p>';
    return;
  }

  for (const ev of todayEvents) {
    const div = document.createElement('div');
    div.className = 'event-item';

    const dot = document.createElement('span');
    dot.className = 'event-dot';
    dot.style.background = ev.color || 'var(--event-dot)';
    div.appendChild(dot);

    if (ev.time && ev.time !== '00:00') {
      const t = document.createElement('span');
      t.className = 'event-time';
      t.textContent = ev.time;
      div.appendChild(t);
    }

    const title = document.createElement('span');
    title.className = 'event-title';
    title.textContent = ev.title;
    div.appendChild(title);

    list.appendChild(div);
  }
}

/* ── Fetch calendar data ── */

async function fetchEvents() {
  try {
    const resp = await fetch(apiURL('/api/calendar'), { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    state.events = data.events || [];
    renderCalendar();
  } catch (err) {
    console.error('Failed to fetch events:', err);
  }
}

/* ── Weather ── */

async function fetchWeather() {
  try {
    const resp = await fetch(apiURL('/api/weather'), { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    document.getElementById('weather-temp').textContent =
      data.temp != null ? `${Math.round(data.temp)}°` : '--°';
    if (data.icon) {
      document.getElementById('weather-icon').textContent = data.icon;
    }
  } catch (err) {
    // Keep default display
  }
}

/* ── Status ── */

async function fetchStatus() {
  try {
    const resp = await fetch(apiURL('/api/status'), { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    document.getElementById('host-display').textContent = data.hostname || 'Fauxnix Wall';
    document.getElementById('status-dot').className = 'status-indicator';
    document.getElementById('status-text').textContent = 'Connected';
    if (data.disk) {
      const { used, total, percent } = data.disk;
      document.getElementById('disk-info').textContent =
        `${Math.round(percent)}% · ${formatBytes(used)} / ${formatBytes(total)}`;
    }
  } catch (err) {
    document.getElementById('status-dot').className = 'status-indicator offline';
    document.getElementById('status-text').textContent = 'Offline';
  }
}

function formatBytes(bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = Number(bytes || 0);
  let u = 0;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
  return `${v.toFixed(u === 0 ? 0 : 1)} ${units[u]}`;
}

/* ── Navigation ── */

document.getElementById('prev-month').addEventListener('click', () => {
  state.viewMonth--;
  if (state.viewMonth < 0) { state.viewMonth = 11; state.viewYear--; }
  renderCalendar();
});

document.getElementById('next-month').addEventListener('click', () => {
  state.viewMonth++;
  if (state.viewMonth > 11) { state.viewMonth = 0; state.viewYear++; }
  renderCalendar();
});

/* ── Init ── */

tickClock();
fetchEvents();
fetchWeather();
fetchStatus();

setInterval(tickClock, 1000);
setInterval(fetchEvents, 60000);
setInterval(fetchWeather, 300000);
setInterval(fetchStatus, 15000);
