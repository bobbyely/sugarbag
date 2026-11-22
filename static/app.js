// Sugarbag's page: signing in, the board, the list and the issue panel. Runs in the browser and talks only to sugarbag.py's /api.
// No library and no build step. Everything anyone typed goes through esc() or md.js before it reaches the page.
"use strict";
const $app = document.getElementById("app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const TYPE_NAMES = { epic: "Epic", story: "Story", task: "Task", bug: "Bug", subtask: "Sub-task" };
const PRIORITIES = ["highest", "high", "medium", "low", "lowest"];
const COLORS = { blue: "Blue", teal: "Teal", green: "Green", yellow: "Yellow", orange: "Orange", red: "Red", pink: "Pink", purple: "Purple" };  // as COLORS in sugarbag.py
const STALE_DAYS = 14;  // a card this long in one working column is probably stuck
const state = { me: null, projects: [], project: null, items: [], users: [], view: "board", q: "", assignee: "", epic: "", openKey: null, name: "Sugarbag" };
try { Object.assign(state, JSON.parse(localStorage.getItem("sugarbag") || "{}")); } catch { /* a private window has no storage; the defaults do */ }
state.me = null; state.openKey = null;

const remember = () => {
  try { localStorage.setItem("sugarbag", JSON.stringify({ project: state.project, view: state.view, theme: state.theme })); } catch { /* as above */ }
};
// Auto follows the phone or computer. The other two stay as chosen, on this device only.
const THEMES = { auto: "Auto", light: "Light", dark: "Dark" };
const applyTheme = () => {
  if (state.theme === "light" || state.theme === "dark") document.documentElement.dataset.theme = state.theme;
  else delete document.documentElement.dataset.theme;
};
applyTheme();

async function api(method, path, body) {
  const res = await fetch(path, { method, headers: body !== undefined || method !== "GET" ? { "Content-Type": "application/json" } : {}, body: body !== undefined ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => null);
  if (res.status === 401 && path !== "/api/login") { state.me = null; drawLogin(); throw new Error("Please sign in."); }
  if (!res.ok) throw new Error(data?.error || "Something went wrong.");
  return data;
}

let toastTimer;
function toast(message) {
  const t = document.getElementById("toast");
  t.textContent = message; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
}
const attempt = fn => async (...args) => { try { return await fn(...args); } catch (e) { toast(e.message); } };
const canEdit = () => state.me && state.me.role !== "viewer";

// --- Small drawings ---

const ICONS = {
  epic: '<rect width="16" height="16" rx="2" fill="currentColor"/><path d="M9 3 5 9h3l-1 4 4-6H8z" fill="#fff"/>',
  story: '<rect width="16" height="16" rx="2" fill="currentColor"/><path d="M5 3.5h6v9L8 10.3 5 12.5z" fill="#fff"/>',
  task: '<rect width="16" height="16" rx="2" fill="currentColor"/><path d="m4.5 8.2 2.4 2.4 4.6-5" fill="none" stroke="#fff" stroke-width="2"/>',
  bug: '<rect width="16" height="16" rx="2" fill="currentColor"/><circle cx="8" cy="8" r="3.5" fill="#fff"/>',
  subtask: '<rect width="16" height="16" rx="2" fill="currentColor"/><path d="M4 4h5v5H4z" fill="none" stroke="#fff" stroke-width="1.5"/><path d="M7 7h5v5H7z" fill="#fff"/>',
};
const typeIcon = t => `<svg class="icon ty-${t}" viewBox="0 0 16 16" role="img" aria-label="${TYPE_NAMES[t]}">${ICONS[t]}</svg>`;
const PRIORITY_PATHS = {
  highest: "M3 8l5-4 5 4M3 12l5-4 5 4", high: "M3 10l5-4 5 4", medium: "M3 6h10M3 10h10", low: "M3 6l5 4 5-4", lowest: "M3 4l5 4 5-4M3 8l5 4 5-4",
};
const priorityIcon = p => `<svg class="icon pr-${p}" viewBox="0 0 16 16" role="img" aria-label="${p} priority"><path d="${PRIORITY_PATHS[p]}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const hash = s => [...s].reduce((n, c) => (n * 31 + c.charCodeAt(0)) >>> 0, 7);
const avatar = name => name ? `<span class="avatar av${hash(name) % 8}" title="${esc(name)}">${esc(name.slice(0, 2).toUpperCase())}</span>` : '<span class="avatar none" title="Nobody yet"></span>';
const LOGO = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="7" cy="7.5" rx="4.5" ry="3" transform="rotate(-30 7 7.5)" fill="currentColor" opacity=".35"/><ellipse cx="17" cy="7.5" rx="4.5" ry="3" transform="rotate(30 17 7.5)" fill="currentColor" opacity=".35"/><ellipse cx="12" cy="14" rx="5.5" ry="7.5" fill="#e8a317"/><path d="M6.9 11.500h10.200M6.7 15.500h10.6" stroke="#172b4d" stroke-width="2.2"/></svg>';
const SUN_ICON = '<svg class="icon small" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor"/></svg>';
const GEAR_ICON = '<svg class="icon small" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="2.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 1.500v2M8 12.500v2M1.5 8h2M12.5 8h2M3.4 3.400l1.4 1.400M11.2 11.200l1.4 1.400M3.4 12.600l1.4-1.400M11.2 4.800l1.4-1.4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';
const COLUMNS_ICON = '<svg class="icon small" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 2.5h3v11H2zM6.5 2.5h3v7h-3zM11 2.5h3v9h-3z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';
const PROJECTS_ICON = '<svg class="icon small" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 3h11v3h-11zM2.5 10h11v3h-11z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';
const COMMENT_ICON = '<svg class="icon small" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3h12v8H7l-3 3v-3H2z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';
const ALL = "*", DONE_ALL = "*done";  // the All projects view, and its one Done column
const allMode = () => state.project === ALL;
const projectInfo = (key = state.project) => state.projects.find(p => p.key === key);
const shownProjects = () => {  // hiding every project would leave nothing, so that shows them all
  const shown = state.projects.filter(p => !(state.me?.hidden_projects || []).includes(p.key));
  return shown.length ? shown : state.projects;
};
// Looked up for every card on every redraw, so kept in a map that is rebuilt when the projects are fetched again.
let statusMap = new Map(), statusFrom = null;
const statusInfo = (slug, project = state.project) => {
  if (statusFrom !== state.projects) { statusFrom = state.projects; statusMap = new Map(state.projects.flatMap(p => p.statuses.map(s => [`${p.key}/${s.slug}`, s]))); }
  return statusMap.get(`${project}/${slug}`);
};
const st = i => statusInfo(i.status, i.project);
const today = () => new Date().toLocaleDateString("en-CA");
const when = t => new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const statusChip = i => {
  const s = st(i), slug = i.status;
  // The first column is where work waits, so anything past it and not finished counts as under way.
  const kind = s?.is_done ? "done" : s?.position ? "active" : "";
  return `<span class="status ${kind}">${esc(s?.name || slug)}</span>`;
};

// --- Signing in ---

function drawLogin() {
  $app.innerHTML = `<form class="login"><h1>${LOGO}${esc(state.name)}</h1><p class="err" hidden></p>
    <label class="field">Name<input class="input" name="name" autocomplete="username" autocapitalize="none" required></label>
    <label class="field">Password<input class="input" name="password" type="password" autocomplete="current-password" required></label>
    <button class="btn primary">Sign in</button></form>`;
  const form = $app.querySelector("form");
  form.onsubmit = async e => {
    e.preventDefault();
    try {
      await api("POST", "/api/login", { name: form.name.value, password: form.password.value });
      await start();
    } catch (err) {
      const p = form.querySelector(".err"); p.textContent = err.message; p.hidden = false;
    }
  };
  form.name.focus();
}

async function start() {
  state.name = (await api("GET", "/info")).name;
  document.title = state.name;
  try { state.me = await api("GET", "/api/me"); } catch { return; }
  [state.projects, state.users] = await Promise.all([api("GET", "/api/projects"), api("GET", "/api/users")]);
  if (!projectInfo() && !(allMode() && state.projects.length > 1)) state.project = state.projects[0]?.key || null;
  await load();
  drawShell();
  openFromAddress();
}

let loads = 0;
async function load() {
  // The board shows only recently finished work, so it doesn't fetch every old done ticket; the other views get everything.
  const recent = state.view === "board" && state.me?.done_days ? `&done_days=${state.me.done_days}` : "";
  const mine = ++loads;
  // All projects asks for the ones this person shows, or for everything when none are hidden.
  const keys = !allMode() ? state.project : shownProjects().length < state.projects.length ? shownProjects().map(p => p.key).join(",") : "";
  const items = state.project ? await api("GET", `/api/items?project=${encodeURIComponent(keys)}${recent}`) : [];
  if (mine === loads) state.items = items;  // an older answer arriving late must not replace a newer view's items
}

// --- The frame around the board ---

function drawShell() {
  const options = (state.projects.length > 1 ? `<option value="${ALL}"${allMode() ? " selected" : ""}>All projects</option>` : "") + state.projects.map(p => `<option value="${esc(p.key)}"${p.key === state.project ? " selected" : ""}>${esc(p.name)}</option>`).join("") +
    (state.me.role === "admin" ? '<option value="+new">+ New project</option>' : "");
  $app.innerHTML = `<div class="top"><span class="brand">${LOGO}<span>${esc(state.name)}</span></span>
      <label class="sr" for="project">Project</label><select class="input" id="project">${options}</select>
      <div class="tabs"><button data-view="board" aria-pressed="${state.view === "board"}">Board</button><button data-view="list" aria-pressed="${state.view === "list"}">List</button><button data-view="roadmap" aria-pressed="${state.view === "roadmap"}">Roadmap</button><button data-view="timeline" aria-pressed="${state.view === "timeline"}">Timeline</button></div>
      <span class="spacer"></span>
      ${canEdit() && state.project ? '<button class="btn primary" id="create" aria-label="New ticket">+ New<span class="wide"> ticket</span></button>' : ""}
      <button class="btn icon-btn" id="theme" aria-label="Colour theme: ${THEMES[state.theme] || "Auto"}. Tap to change.">${SUN_ICON}<span>${THEMES[state.theme] || "Auto"}</span></button>
      <button class="btn icon-btn" id="settings" aria-label="Settings">${GEAR_ICON}<span>Settings</span></button></div>
    <div class="filters"><label class="sr" for="q">Search</label><input class="input" id="q" type="search" placeholder="Search" value="${esc(state.q)}">
      <label class="sr" for="who">Assignee</label><select class="input" id="who"></select>
      <label class="sr" for="epic">Epic</label><select class="input" id="epic"></select>
      ${allMode() ? `<button class="btn icon-btn" id="columns" aria-label="Choose projects">${PROJECTS_ICON}<span>Projects${shownProjects().length < state.projects.length ? ` (${shownProjects().length} of ${state.projects.length})` : ""}</span>${shownProjects().length < state.projects.length ? `<b class="hide-wide">${shownProjects().length}</b>` : ""}</button>`
        : `<button class="btn icon-btn" id="columns" aria-label="Show or hide columns">${COLUMNS_ICON}<span>Columns${hiddenColumns().length ? ` (${hiddenColumns().length} hidden)` : ""}</span>${hiddenColumns().length ? `<b class="hide-wide">${hiddenColumns().length}</b>` : ""}</button>`}</div>
    <div id="view"></div>`;
  document.getElementById("project").onchange = attempt(async e => {
    if (e.target.value === "+new") { e.target.value = state.project || ""; return openNewProject(); }
    state.project = e.target.value; state.epic = ""; state.doneColumn = null; remember(); await load(); drawShell();
  });
  $app.querySelectorAll(".tabs button").forEach(b => { b.onclick = attempt(() => showView(b.dataset.view)); });
  document.getElementById("q").oninput = e => { state.q = e.target.value; drawView(); };
  document.getElementById("who").onchange = e => { state.assignee = e.target.value; drawView(); };
  document.getElementById("epic").onchange = e => { state.epic = e.target.value; drawView(); };
  document.getElementById("settings").onclick = attempt(openSettings);
  document.getElementById("columns").onclick = attempt(() => allMode() ? openProjects() : openColumns(state.project));
  document.getElementById("theme").onclick = () => {
    const order = Object.keys(THEMES);
    state.theme = order[(order.indexOf(state.theme || "auto") + 1) % order.length];
    applyTheme(); remember(); drawShell();
  };
  const create = document.getElementById("create");
  if (create) create.onclick = () => openCreate();
  drawFilters();
  drawView();
}

// Switching between the board and the rest reloads, because the board leaves out older done work.
async function showView(view, doneColumn = null) {
  state.view = view; state.doneColumn = doneColumn; boardShown = false; remember();
  await load(); drawShell();
}

function drawFilters() {
  const who = document.getElementById("who"), epic = document.getElementById("epic");
  if (!who) return;
  who.innerHTML = `<option value="">Anyone</option><option value="-"${state.assignee === "-" ? " selected" : ""}>Nobody</option>` +
    state.users.filter(u => u.active).map(u => `<option value="${esc(u.name)}"${u.name === state.assignee ? " selected" : ""}>${esc(u.name)}</option>`).join("");
  epic.innerHTML = '<option value="">All epics</option>' +
    state.items.filter(i => i.type === "epic").map(i => `<option value="${esc(i.key)}"${i.key === state.epic ? " selected" : ""}>${allMode() ? esc(i.project) + ": " : ""}${esc(i.title)}</option>`).join("");
}

function matches(i) {
  if (state.assignee && (i.assignee || "-") !== state.assignee) return false;
  // The server names each item's epic, even a sub-task's whose parent the board left out.
  if (state.epic && i.epic !== state.epic && i.key !== state.epic) return false;
  const q = state.q.trim().toLowerCase();
  return !q || `${i.key} ${i.title} ${i.labels.join(" ")}`.toLowerCase().includes(q);
}

function drawView() {
  const box = document.getElementById("view");
  if (!box) return;
  if (!state.project) {
    box.className = "empty";
    box.innerHTML = state.me.role === "admin" ? '<p>No projects yet.</p><button class="btn primary" id="first">+ New project</button>' : "<p>No projects yet. Ask an admin to make one.</p>";
    const first = document.getElementById("first");
    if (first) first.onclick = openNewProject;
  } else if (state.view === "list") drawList(box);
  else if (state.view === "roadmap") drawRoadmap(box);
  else if (state.view === "timeline") drawTimeline(box);
  else drawBoard(box);
}

// --- The board ---

function cardHtml(i) {
  const s = st(i);
  const overdue = i.due && i.due < today() && !s?.is_done;
  // Finished work has no clock. Ideas can wait for ever, so only later columns turn amber.
  const days = Math.floor((Date.now() / 1000 - (i.status_since || i.created)) / 86400);
  const age = !s?.is_done && days >= 1 ? `<span class="age${s?.position && days >= STALE_DAYS ? " stale" : ""}" title="${days} day${days === 1 ? "" : "s"} in this column">${days}d</span>` : "";
  const tags = (i.parent ? `<span class="lozenge${i.parent_type === "epic" ? " epic" : " parent"}">${esc(i.parent_title)}</span>` : "") +
    i.labels.map(l => `<span class="lozenge">${esc(l)}</span>`).join("") + (overdue ? `<span class="lozenge overdue">Due ${esc(new Date(i.due + "T12:00").toLocaleDateString(undefined, { day: "numeric", month: "short" }))}</span>` : "");
  return `<button class="card${s?.is_done ? " is-done" : ""}" data-key="${esc(i.key)}">
    <span class="title">${mdInline(i.title)}</span>${i.next ? `<span class="next" title="Next step">&rarr; ${esc(i.next)}</span>` : ""}${tags ? `<span class="tags">${tags}</span>` : ""}
    <span class="meta">${typeIcon(i.type)}<span>${esc(i.key)}</span>
      ${i.children ? `<span class="progress" title="Sub-tasks done">${i.children_done}/${i.children}</span>` : ""}
      ${i.comment_count ? `<span class="progress" title="Comments">${COMMENT_ICON}${i.comment_count}</span>` : ""}
      <span class="right">${age}${i.priority === "medium" ? "" : priorityIcon(i.priority)}${avatar(i.assignee)}</span></span></button>`;
}

const hiddenColumns = (key = state.project) => state.me?.hidden?.[key] || [];
// An epic is a theme, so it never gets a card. A sub-task gets one only while it's being worked on: its parent waits in
// its column and the step moves across. Waiting and finished steps stay inside their parent, or they'd swamp the board.
const onBoard = i => {
  if (i.type === "epic" || !matches(i)) return false;
  if (i.type !== "subtask") return true;
  const s = st(i);
  return !!s && s.position >= 2 && !s.is_done;
};

let boardShown = false;

// The All projects board. Projects can have different columns, so: each project's columns in its own order, merged by
// short name (slug), which lines up the usual columns; a column only some projects have sits after the one before it in
// those projects. Every done column, whatever its name, becomes one Done at the end. parts lists [project, slug] pairs.
function allColumns() {
  const cols = [], done = { slug: DONE_ALL, name: "Done", is_done: 1, count: 0, color: null, parts: [] };
  for (const p of shownProjects()) {
    let at = 0;
    for (const s of p.statuses) {
      if (s.is_done) { done.count += s.count; done.color ||= s.color; done.parts.push([p.key, s.slug]); continue; }
      let n = cols.findIndex(c => c.slug === s.slug);
      if (n < 0) { n = at; cols.splice(n, 0, { ...s, count: 0, parts: [] }); }
      cols[n].count += s.count; cols[n].color ||= s.color; cols[n].parts.push([p.key, s.slug]);
      at = n + 1;
    }
  }
  return done.parts.length ? [...cols, done] : cols;
}
// Which board column a card sits in: its own, or in All projects the merged one.
const columnOf = i => allMode() && st(i)?.is_done ? DONE_ALL : i.status;
// The real column a project has behind a board column: in All projects, from the merged column's own list, since the
// same short name can be done in one project and not in another.
const statusFor = (column, project) => !allMode() ? column : allColumns().find(c => c.slug === column)?.parts.find(([k]) => k === project)?.[1];

function drawBoard(box) {
  const scroll = box.scrollLeft;
  box.className = "board";
  // All projects: a column is hidden only if every project in it hides it, and a card is hidden if its own column is.
  const columns = allMode() ? allColumns().filter(c => !c.parts.every(([k, slug]) => hiddenColumns(k).includes(slug)))
    : projectInfo().statuses.filter(s => !hiddenColumns().includes(s.slug));
  const showing = i => onBoard(i) && (!allMode() || !hiddenColumns(i.project).includes(i.status));
  box.innerHTML = columns.map(s => {
    const cards = state.items.filter(i => columnOf(i) === s.slug && showing(i)).sort((a, b) => a.position - b.position);
    return `<section class="column${COLORS[s.color] ? ` tinted tint-${s.color}` : ""}" data-status="${esc(s.slug)}" aria-label="${esc(s.name)}">
      <header><span>${esc(s.name)}</span><span class="count">${cards.length}</span>${s.is_done ? '<span class="tick" aria-hidden="true">✓</span>' : ""}</header>
      <div class="cards">${cards.map(cardHtml).join("")}</div>
      ${s.is_done && s.count > state.items.filter(i => columnOf(i) === s.slug).length ? `<button class="add-card all-done" data-done="${esc(s.slug)}">Show all ${s.count} done</button>` : ""}
      ${canEdit() ? '<button class="add-card">+ New ticket</button>' : ""}</section>`;
  }).join("");
  box.scrollLeft = scroll;
  // On a phone only one column fits, so open on the first one with work in it.
  if (!boardShown && innerWidth <= 600) box.querySelector(".column:has(.card)")?.scrollIntoView({ inline: "start", block: "nearest" });
  boardShown = true;
  box.querySelectorAll(".add-card:not(.all-done)").forEach(b => { b.onclick = () => openCreate({ status: b.closest(".column").dataset.status }); });
  box.querySelectorAll("[data-done]").forEach(b => { b.onclick = attempt(() => showView("list", b.dataset.done)); });
  box.querySelectorAll(".card").forEach(c => { if (canEdit()) enableDrag(c); c.onclick = () => { if (!justDragged) openItem(c.dataset.key); }; });
}

// Pointer events rather than HTML drag and drop, because iPhones don't do HTML drag and drop.
// A finger must rest on a card first, so a swipe still scrolls the board.
let justDragged = false, activeDrag = null;

function enableDrag(card) {
  card.addEventListener("pointerdown", down => {
    if (down.button) return;
    const start = { x: down.clientX, y: down.clientY };
    let timer = null, drag = null;
    const stop = () => {
      clearTimeout(timer);
      removeEventListener("pointermove", move); removeEventListener("pointerup", up); removeEventListener("pointercancel", cancel);
    };
    const begin = () => { drag = startDrag(card, start); };
    const move = e => {
      const far = Math.hypot(e.clientX - start.x, e.clientY - start.y);
      if (!drag && down.pointerType !== "touch" && far > 5) begin();
      if (!drag && down.pointerType === "touch" && far > 8) return stop();  // it's a swipe
      if (drag) dragTo(drag, e.clientX, e.clientY);
    };
    const up = () => { stop(); if (drag) finishDrag(drag); };
    const cancel = () => { stop(); if (drag) cancelDrag(drag); };
    if (down.pointerType === "touch") timer = setTimeout(begin, 220);
    addEventListener("pointermove", move); addEventListener("pointerup", up); addEventListener("pointercancel", cancel);
  });
  // A drag starting on a card must never also select text or open the phone's menu.
  card.addEventListener("contextmenu", e => { if (activeDrag) e.preventDefault(); });
}

addEventListener("touchmove", e => { if (activeDrag) e.preventDefault(); }, { passive: false });

function startDrag(card, at) {
  const r = card.getBoundingClientRect();
  const ghost = card.cloneNode(true); ghost.classList.add("ghost"); ghost.removeAttribute("data-key");
  ghost.style.width = r.width + "px"; ghost.style.left = r.left + "px"; ghost.style.top = r.top + "px";
  const place = document.createElement("div"); place.className = "placeholder"; place.style.height = r.height + "px";
  card.after(place); card.classList.add("lifted");
  document.body.append(ghost); document.body.classList.add("dragging");
  if (navigator.vibrate) navigator.vibrate(8);
  activeDrag = { card, ghost, place, dx: at.x - r.left, dy: at.y - r.top };
  autoScroll(activeDrag);
  return activeDrag;
}

function dragTo(d, x, y) {
  d.x = x; d.y = y;
  d.ghost.style.left = x - d.dx + "px"; d.ghost.style.top = y - d.dy + "px";
  placeCard(d);
}

// A finger held at the screen's edge sends no more events, so the board keeps scrolling on a timer of its own.
function autoScroll(d) {
  if (activeDrag !== d) return;
  const board = document.querySelector(".board");
  if (d.x !== undefined && board) {
    const before = board.scrollLeft;
    if (d.x < 40) board.scrollLeft -= 10; else if (d.x > innerWidth - 40) board.scrollLeft += 10;
    if (board.scrollLeft !== before) placeCard(d);
  }
  requestAnimationFrame(() => autoScroll(d));
}

function placeCard(d) {
  const x = d.x, y = d.y;
  const under = document.elementFromPoint(Math.min(Math.max(x, 1), innerWidth - 1), y)?.closest(".column");
  if (!under) return;
  const list = under.querySelector(".cards");
  const next = [...list.querySelectorAll(".card:not(.lifted)")].find(c => { const r = c.getBoundingClientRect(); return y < r.top + r.height / 2; });
  list.insertBefore(d.place, next || null);
  const box = list.getBoundingClientRect();
  if (y < box.top + 30) list.scrollTop -= 8; else if (y > box.bottom - 30) list.scrollTop += 8;
}

function endDrag(d) {
  d.ghost.remove(); document.body.classList.remove("dragging"); d.card.classList.remove("lifted");
  activeDrag = null;
  justDragged = true; setTimeout(() => { justDragged = false; }, 50);
}

function cancelDrag(d) { d.place.remove(); endDrag(d); }

async function finishDrag(d) {
  const keyed = new Map(state.items.map(i => [i.key, i])), byKey = k => keyed.get(k);
  const item = byKey(d.card.dataset.key), column = d.place.closest(".column").dataset.status;
  // In All projects a column holds several projects' cards: Done means this project's first done column, and the card
  // goes above the next card of its own project and column, since the server only places it among those.
  const status = statusFor(column, item.project);
  let next = d.place.nextElementSibling;
  while (next && (byKey(next.dataset.key)?.project !== item.project || byKey(next.dataset.key)?.status !== status)) next = next.nextElementSibling;
  d.place.replaceWith(d.card);
  endDrag(d);
  try {
    if (!status) throw new Error(`${item.project} has no ${d.card.closest(".column")?.getAttribute("aria-label") || "such"} column.`);
    await api("POST", `/api/items/${item.key}/move`, { status, before: next?.dataset.key || null });
  } catch (e) { toast(e.message); }
  await load();
  drawView();
}

// --- The list: everything, nested, including what the board leaves out ---

// Each item's children by key, so drawing thousands of rows doesn't search the whole list for every one.
function childrenOf() {
  const kids = new Map();
  for (const i of state.items) if (i.parent) (kids.get(i.parent) || kids.set(i.parent, []).get(i.parent)).push(i);
  return kids;
}

// Everything in one done column, most recently finished first: where "Show all done" on the board leads.
function drawDoneList(box) {
  const s = allMode() ? { name: "Done" } : statusInfo(state.doneColumn);
  const rows = state.items.filter(i => columnOf(i) === state.doneColumn && matches(i)).sort((a, b) => (b.finished || 0) - (a.finished || 0));
  const day = t => t ? new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
  box.innerHTML = `<div class="done-head"><button class="btn" id="backboard">&larr; Back to board</button><h2>${esc(s?.name || state.doneColumn)}: all ${rows.length}, newest first</h2></div>` +
    (rows.map(i => `<button class="row" data-key="${esc(i.key)}">${typeIcon(i.type)}<span class="key">${esc(i.key)}</span><span class="t">${mdInline(i.title)}</span><span class="tl-note">${esc(day(i.finished))}</span>${avatar(i.assignee)}</button>`).join("") || '<p class="empty">Nothing here.</p>');
  box.querySelector("#backboard").onclick = attempt(() => showView("board"));
  box.querySelectorAll(".row").forEach(r => { r.onclick = () => openItem(r.dataset.key); });
}

function drawList(box) {
  box.className = "list";
  if (state.doneColumn && (allMode() ? state.doneColumn === DONE_ALL : statusInfo(state.doneColumn))) return drawDoneList(box);
  const rows = [], kids = childrenOf();
  const add = (i, depth) => {
    rows.push(`<button class="row ${depth === 1 ? "child" : depth === 2 ? "grand" : ""}" data-key="${esc(i.key)}">${typeIcon(i.type)}<span class="key">${esc(i.key)}</span>
      <span class="t">${mdInline(i.title)}</span>${statusChip(i)}${priorityIcon(i.priority)}${avatar(i.assignee)}</button>`);
    (kids.get(i.key) || []).sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true })).forEach(k => { if (matches(k) || state.q) add(k, depth + 1); });
  };
  // Anything whose parent is hidden still shows, at the top level.
  const shown = state.items.filter(matches), shownKeys = new Set(shown.map(i => i.key));
  shown.filter(i => !i.parent || !shownKeys.has(i.parent)).sort((a, b) => (a.type === "epic" ? 0 : 1) - (b.type === "epic" ? 0 : 1) || a.key.localeCompare(b.key, undefined, { numeric: true })).forEach(i => add(i, 0));
  box.innerHTML = rows.join("") || '<p class="empty">Nothing here.</p>';
  box.querySelectorAll(".row").forEach(r => { r.onclick = () => openItem(r.dataset.key); });
}

// --- The roadmap: one row per epic, with progress ---

const openEpics = new Set();  // epics whose stories are showing; kept across redraws
const natural = (a, b) => a.localeCompare(b, undefined, { numeric: true });

function drawRoadmap(box) {
  box.className = "list";
  // No ticket needs a date, so undated epics sort after dated ones, by title with numbers in order ("Stage 2" before "Stage 10").
  const isDone = i => !!st(i)?.is_done;
  const filtering = !!(state.q.trim() || state.assignee), kids = childrenOf();
  // An epic shows if it or any of its stories match, so a search for a story's title finds its epic.
  const rows = state.items.filter(i => i.type === "epic").map(e => {
    const stories = (kids.get(e.key) || []).sort((a, b) => natural(a.key, b.key));
    return { e, stories, hits: stories.filter(matches) };
  }).filter(r => matches(r.e) || r.hits.length).sort((x, y) => {
    const a = x.e, b = y.e;
    return isDone(a) - isDone(b) || (a.start ? 0 : 1) - (b.start ? 0 : 1) || (a.start || "").localeCompare(b.start || "") || natural(a.title, b.title);
  });
  box.innerHTML = rows.map(({ e, stories, hits }) => {
    // While filtering, epics with matches start open; a tap on the arrow flips that.
    const open = openEpics.has(e.key) !== (filtering && hits.length > 0), shown = filtering ? hits : stories;
    return `<div class="road${isDone(e) ? " is-done" : ""}"><div class="road-head">
      <button class="road-toggle" data-toggle="${esc(e.key)}" aria-expanded="${open}" aria-label="${open ? "Hide" : "Show"} stories of ${esc(e.title)}"${stories.length ? "" : " disabled"}>${open ? "&#9662;" : "&#9656;"}</button>
      <button class="road-main" data-key="${esc(e.key)}"><span class="road-top">${typeIcon("epic")}${allMode() ? `<span class="key">${esc(e.key)}</span>` : ""}<span class="t">${mdInline(e.title)}</span>${statusChip(e)}</span>
        <span class="road-bar"><progress value="${e.children_done}" max="${e.children || 1}" aria-label="Done"></progress><span class="progress">${e.children_done}/${e.children}</span></span>
        ${e.next ? `<span class="next">&rarr; ${esc(e.next)}</span>` : ""}</button></div>
      ${open ? shown.map(k => `<button class="row child" data-key="${esc(k.key)}">${typeIcon(k.type)}<span class="key">${esc(k.key)}</span><span class="t">${mdInline(k.title)}</span>${statusChip(k)}${avatar(k.assignee)}</button>`).join("") : ""}</div>`;
  }).join("") || '<p class="empty">No epics yet.</p>';
  box.querySelectorAll("[data-key]").forEach(r => { r.onclick = () => openItem(r.dataset.key); });
  box.querySelectorAll("[data-toggle]").forEach(b => {
    b.onclick = () => {
      const k = b.dataset.toggle;
      openEpics.has(k) ? openEpics.delete(k) : openEpics.add(k);
      drawRoadmap(box);
      box.querySelector(`[data-toggle="${CSS.escape(k)}"]`)?.focus();  // the redraw drops focus, which would lose a keyboard user's place
    };
  });
}

// --- The timeline: dated work as bars on one shared time axis ---

const DAY_PX = 4;  // fixed scale; shortcut: no zoom, add one if a project spans many years
const WINDOW_DAYS = 1826;  // 5 years each side of today; a mistyped year would otherwise draw thousands of month labels. shortcut: fixed window, make it a setting if a project needs longer
const dayNumber = d => Date.parse(d + "T00:00:00Z") / 864e5;
const dayText = d => new Date(d + "T12:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

function drawTimeline(box) {
  box.className = "list";
  const isDone = i => !!st(i)?.is_done;
  const dated = i => !!(i.start || i.due);
  const epics = state.items.filter(i => i.type === "epic"), epicKeys = new Set(epics.map(e => e.key)), children = childrenOf();
  const kids = e => (children.get(e.key) || []).filter(k => k.type !== "subtask").sort((a, b) => natural(a.key, b.key));
  const groups = epics.map(e => ({ e, hits: kids(e).filter(matches) })).filter(g => matches(g.e) || g.hits.length);
  // Work with no epic above it still belongs on the chart.
  const loose = state.items.filter(i => i.type !== "epic" && i.type !== "subtask" && !epicKeys.has(i.parent) && matches(i));
  if (loose.length) groups.push({ e: null, hits: loose });
  const rowsOf = g => (g.e && matches(g.e) ? [g.e] : []).concat(g.hits);
  const all = groups.flatMap(rowsOf);
  const undated = all.filter(i => !dated(i));
  // An epic with no dates of its own stays as a heading when its stories are dated.
  const nowDay = dayNumber(today());
  const inWindow = i => [i.start, i.due].filter(Boolean).every(d => Math.abs(dayNumber(d) - nowDay) <= WINDOW_DAYS);
  const earliest = g => [g.e, ...g.hits].filter(i => i && dated(i)).map(i => i.start || i.due).sort()[0] || "9";
  const shownGroups = groups.filter(g => rowsOf(g).some(i => dated(i) && inWindow(i)) || g.hits.some(i => dated(i) && inWindow(i))).sort((a, b) => (a.e ? 0 : 1) - (b.e ? 0 : 1) || earliest(a).localeCompare(earliest(b)));
  const outside = all.filter(i => dated(i) && !inWindow(i));
  // The axis fits what is drawn: dated rows inside the window, plus an epic heading whose own dates are inside it.
  const drawn = shownGroups.flatMap(g => [g.e, ...g.hits.filter(dated)].filter(i => i && dated(i) && inWindow(i)));
  const days = drawn.flatMap(i => [i.start, i.due].filter(Boolean)).map(dayNumber);
  const listRow = (i, note) => `<button class="row" data-key="${esc(i.key)}">${typeIcon(i.type)}<span class="key">${esc(i.key)}</span><span class="t">${mdInline(i.title)}</span>${note ? `<span class="tl-note">${esc(note)}</span>` : ""}${statusChip(i)}</button>`;
  const noDates = (undated.length ? `<details class="tl-undated"${days.length ? "" : " open"}><summary>No dates (${undated.length})</summary>${undated.map(i => listRow(i)).join("")}</details>` : "") +
    (outside.length ? `<details class="tl-undated" open><summary>Too far from today to draw (${outside.length})</summary>${outside.map(i => listRow(i, [i.start, i.due].filter(Boolean).map(dayText).join(" to "))).join("")}</details>` : "");
  if (!days.length) {
    box.innerHTML = `<p class="empty">${all.length ? "Nothing can be drawn yet. " : "Nothing here. "}To put work on the timeline, open a ticket and set its start and due dates in the details.</p>${noDates}`;
    box.querySelectorAll("[data-key]").forEach(r => { r.onclick = () => openItem(r.dataset.key); });
    return;
  }
  // Pad a week before and ~2 months after (room for the date label), then snap to whole months.
  const first = new Date(Math.min(...days) * 864e5 - 7 * 864e5), last = new Date(Math.max(...days) * 864e5 + 75 * 864e5);
  const from = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1) / 864e5;
  const to = Date.UTC(last.getUTCFullYear(), last.getUTCMonth() + 1, 1) / 864e5;
  const width = (to - from) * DAY_PX;
  const months = [];
  for (let d = new Date(from * 864e5); d.getTime() / 864e5 < to; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
    months.push(`<span class="tl-month" data-at="${d.getTime() / 864e5 - from}">${esc(d.toLocaleDateString(undefined, { month: "short", timeZone: "UTC", ...(d.getUTCMonth() === 0 || !months.length ? { year: "numeric" } : {}) }))}</span>`);
  }
  const row = (i, head) => {
    // The server allows a start after the due date, so draw from the earlier day and say so.
    const flip = i.start && i.due && i.start > i.due, [a, z] = flip ? [i.due, i.start] : [i.start, i.due];
    const range = a && z ? `${dayText(a)} to ${dayText(z)}${flip ? " (dates reversed)" : ""}` : i.start ? `starts ${dayText(i.start)}` : i.due ? `due ${dayText(i.due)}` : "no dates";
    const here = dated(i) && inWindow(i), statusName = st(i)?.name || i.status;
    const late = i.due && i.due < today() && !isDone(i);
    const kind = isDone(i) ? "done" : st(i)?.position ? "active" : "wait";
    const mark = !here ? "" : a && z
      ? `<span class="tl-bar ${kind}${late ? " late" : ""}" data-from="${dayNumber(a) - from}" data-len="${dayNumber(z) - dayNumber(a) + 1}"></span>`
      : `<span class="tl-dot ${kind}${late ? " late" : ""}" data-from="${dayNumber(i.start || i.due) - from}"></span>`;
    const label = here ? `<span class="tl-when" data-from="${dayNumber(z || a) - from + 1}">${esc(statusName)}, ${esc(range)}</span>` : "";
    return `<button class="tl-row${head ? " head" : ""}${isDone(i) ? " is-done" : ""}" data-key="${esc(i.key)}" aria-label="${esc(i.key)} ${esc(i.title)}, ${esc(statusName)}, ${esc(range)}${late ? ", overdue" : ""}">
      <span class="tl-name">${typeIcon(i.type)}${allMode() ? `<span class="key">${esc(i.project)}</span>` : ""}<span class="t">${mdInline(i.title)}</span></span><span class="tl-track">${mark}${label}</span></button>`;
  };
  const body = shownGroups.map(g => {
    const title = g.e ? "" : '<div class="tl-loose">No epic</div>';
    return title + (g.e ? row(g.e, true) : "") + g.hits.filter(i => dated(i) && inWindow(i)).map(k => row(k)).join("");
  }).join("");
  box.innerHTML = `<div class="tl-scroll"><div class="tl-chart"><div class="tl-row axis" aria-hidden="true"><span class="tl-name"></span><span class="tl-track">${months.join("")}</span></div>${body}</div></div>${noDates}`;
  const chart = box.querySelector(".tl-chart"), nowAt = dayNumber(today()) - from;
  chart.querySelectorAll(".tl-track").forEach(t => {
    t.style.width = width + "px";
    t.querySelectorAll("[data-at]").forEach(m => { m.style.left = m.dataset.at * DAY_PX + "px"; });
    t.querySelectorAll("[data-from]").forEach(b => { b.style.left = b.dataset.from * DAY_PX + "px"; if (b.dataset.len) b.style.width = b.dataset.len * DAY_PX + "px"; });
    if (nowAt >= 0 && nowAt <= to - from) {
      const line = document.createElement("span");
      line.className = "tl-today"; line.style.left = nowAt * DAY_PX + "px";
      t.append(line);
    }
  });
  // Open at today when it would otherwise be off-screen, so a phone doesn't start months in the past.
  const scroller = box.querySelector(".tl-scroll");
  if (nowAt * DAY_PX > scroller.clientWidth - 200) scroller.scrollLeft = nowAt * DAY_PX - 40;
  box.querySelectorAll("[data-key]").forEach(r => { r.onclick = () => openItem(r.dataset.key); });
}

// --- Create ---

function parentOptions(type, current, project = state.project) {
  const wanted = type === "subtask" ? ["story", "task", "bug"] : type === "epic" ? [] : ["epic"];
  return `<option value="">None</option>` + state.items.filter(i => wanted.includes(i.type) && i.project === project)
    .map(i => `<option value="${esc(i.key)}"${i.key === current ? " selected" : ""}>${esc(i.key)} ${esc(i.title)}</option>`).join("");
}
const typeOptions = cur => Object.entries(TYPE_NAMES).map(([k, v]) => `<option value="${k}"${k === cur ? " selected" : ""}>${v}</option>`).join("");
const statusOptions = (cur, project = state.project) => projectInfo(project).statuses.map(s => `<option value="${esc(s.slug)}"${s.slug === cur ? " selected" : ""}>${esc(s.name)}</option>`).join("");
const priorityOptions = cur => PRIORITIES.map(p => `<option value="${p}"${p === cur ? " selected" : ""}>${p[0].toUpperCase() + p.slice(1)}</option>`).join("");
const userOptions = cur => '<option value="">Nobody</option>' + state.users.filter(u => u.active || u.name === cur).map(u => `<option value="${esc(u.name)}"${u.name === cur ? " selected" : ""}>${esc(u.name)}</option>`).join("");

function shade(html, center) {
  const s = document.createElement("div");
  s.className = "shade" + (center ? " center" : "");
  s.innerHTML = html;
  s.addEventListener("pointerdown", e => { if (e.target === s) s.dataset.close = "1"; });
  s.addEventListener("click", e => {
    const typing = [...s.querySelectorAll("#comment, #bodyedit")].some(t => t.value.trim());
    // A stray tap outside must not throw away a half-written comment.
    if (e.target === s && s.dataset.close && !typing) closeShade(s);
    delete s.dataset.close;
  });
  document.body.append(s);
  return s;
}
function closeShade(s) {
  s.remove();
  if (s.dataset.item) { state.openKey = null; wholePage = false; history.replaceState(null, "", location.pathname); }
}
addEventListener("keydown", e => { if (e.key === "Escape") { const all = document.querySelectorAll(".shade"); if (all.length) closeShade(all[all.length - 1]); } });

function openNewProject() {
  const s = shade(`<form class="dialog"><h2>New project</h2><p class="err" hidden></p>
    <label class="field">Name<input class="input" name="name" maxlength="80" required></label>
    <label class="field">Key: the short code at the start of its ticket numbers. AB makes AB-1.<input class="input" name="key" maxlength="10" autocapitalize="characters" required></label>
    <div class="addbar"><button class="btn primary">Create project</button><button class="btn" type="button" id="cancel">Cancel</button></div></form>`, true);
  const f = s.querySelector("form");
  // Suggest a key from the name, until the person types their own.
  f.name.oninput = () => { if (!f.key.dataset.typed) f.key.value = f.name.value.replace(/[^a-z0-9]/gi, "").slice(0, 3).toUpperCase(); };
  f.key.oninput = () => { f.key.dataset.typed = "1"; };
  s.querySelector("#cancel").onclick = () => closeShade(s);
  f.onsubmit = async e => {
    e.preventDefault();
    try {
      const made = await api("POST", "/api/projects", { key: f.key.value, name: f.name.value });
      closeShade(s);
      state.project = made.key; state.epic = ""; remember();
      state.projects = await api("GET", "/api/projects"); await load(); drawShell();
    } catch (err) { const p = f.querySelector(".err"); p.textContent = err.message; p.hidden = false; }
  };
  f.name.focus();
}

function openCreate(preset = {}) {
  const type = preset.type || "task";
  // All projects: the ticket needs a project first, and the parents and columns on offer follow it. A board column there
  // may be the merged Done, or one only some projects have, so start with a project that has it.
  const want = preset.status, statusIn = key => want && statusFor(want, key);
  let project = allMode() ? (shownProjects().find(p => statusInfo(statusIn(p.key), p.key)) || shownProjects()[0]).key : state.project;
  const s = shade(`<form class="dialog"><h2>New ticket</h2><p class="err" hidden></p>
    ${allMode() ? `<label class="field">Project<select class="input" name="project">${shownProjects().map(p => `<option value="${esc(p.key)}"${p.key === project ? " selected" : ""}>${esc(p.name)} (${esc(p.key)})</option>`).join("")}</select></label>` : ""}
    <label class="field">Type<select class="input" name="type">${typeOptions(type)}</select></label>
    <label class="field">Title<input class="input" name="title" maxlength="300" required></label>
    <label class="field">Parent<select class="input" name="parent">${parentOptions(type, preset.parent, project)}</select></label>
    <div class="fields"><label class="field">Status<select class="input" name="status">${statusOptions(statusIn(project), project)}</select></label>
    <label class="field">Priority<select class="input" name="priority">${priorityOptions("medium")}</select></label>
    <label class="field">Assignee<select class="input" name="assignee">${userOptions(state.me.name)}</select></label></div>
    <label class="field">Description<textarea class="input" name="body"></textarea></label>
    <div class="addbar"><button class="btn primary">Create ticket</button><button class="btn" type="button" id="cancel">Cancel</button></div></form>`, true);
  const f = s.querySelector("form");
  f.type.onchange = () => { f.parent.innerHTML = parentOptions(f.type.value, "", project); };
  if (f.project) f.project.onchange = () => {
    project = f.project.value;
    f.parent.innerHTML = parentOptions(f.type.value, "", project);
    f.status.innerHTML = statusOptions(want ? statusIn(project) : f.status.value, project);
  };
  s.querySelector("#cancel").onclick = () => closeShade(s);
  f.onsubmit = async e => {
    e.preventDefault();
    try {
      await api("POST", "/api/items", { project, type: f.type.value, title: f.title.value, parent: f.parent.value || null, status: f.status.value,
        priority: f.priority.value, assignee: f.assignee.value || null, body: f.body.value });
      closeShade(s);
      await refresh();
    } catch (err) { const p = f.querySelector(".err"); p.textContent = err.message; p.hidden = false; }
  };
  f.title.focus();
}

// --- One item ---

async function refresh() {
  state.projects = await api("GET", "/api/projects");  // someone else may have changed the columns
  await load();
  drawFilters();
  if (!activeDrag) drawView();
}

// An issue opens over the board. Its own page is the same thing filling the screen, at an address that can be saved or sent.
let wholePage = false;

const openItem = attempt(async asked => {
  const item = await api("GET", `/api/items/${encodeURIComponent(asked)}`), key = item.key;  // an old key answers with the new one
  // The address may name another project's issue, so show that project's board and columns behind it.
  if (!allMode() && item.project !== state.project) { state.project = item.project; state.epic = ""; await load(); drawShell(); }
  // A save redraws the issue, so stay at the same place on it.
  const old = document.querySelector(".shade[data-item]");
  const scroll = old?.dataset.item === key ? old.scrollTop : 0;
  old?.remove();
  state.openKey = key;
  history.replaceState(null, "", wholePage ? `?issue=${encodeURIComponent(key)}` : "#" + key);
  drawItem(item).scrollTop = scroll;
});

function drawItem(i) {
  const ro = canEdit() ? "" : " disabled";
  const s = shade(`<div class="panel" role="dialog" aria-modal="true" aria-label="${esc(i.key)} ${esc(i.title)}">
    <div class="panel-top">${typeIcon(i.type)}${i.parent ? `<button class="btn link" data-open="${esc(i.parent)}">${esc(i.parent)}</button> /` : ""}<span>${esc(i.key)}</span>
      <span class="right">${wholePage ? "" : `<a class="btn" href="?issue=${encodeURIComponent(i.key)}">Open as page</a>`}
        <button class="btn" id="close">${wholePage ? "Back to board" : "Close"}</button></span></div>
    <label class="sr" for="title">Title</label><textarea class="title-edit" id="title" rows="1" maxlength="300"${ro}>${esc(i.title)}</textarea>
    <div class="item-grid">
      <aside class="item-side">
        <div class="key-fields"><label class="field">Status<select class="input" data-f="status"${ro}>${statusOptions(i.status, i.project)}</select></label>
        <label class="field">Assignee<select class="input" data-f="assignee"${ro}>${userOptions(i.assignee)}</select></label>
        <label class="field wide">Next step<input class="input" data-f="next" maxlength="200" value="${esc(i.next)}"${ro} placeholder="Who does what next"></label></div>
        <details class="more"${innerWidth > 700 ? " open" : ""}><summary>More details</summary><div class="more-fields">
        <label class="field">Priority<select class="input" data-f="priority"${ro}>${priorityOptions(i.priority)}</select></label>
        <label class="field">Type<select class="input" data-f="type"${ro}>${typeOptions(i.type)}</select></label>
        <label class="field">Parent<select class="input" data-f="parent"${ro}>${parentOptions(i.type, i.parent, i.project)}</select></label>
        <label class="field">Labels<input class="input" data-f="labels" value="${esc(i.labels.join(", "))}"${ro} placeholder="comma, separated"></label>
        <label class="field">Start<input class="input" type="date" data-f="start" value="${esc(i.start)}"${ro}></label>
        <label class="field">Due<input class="input" type="date" data-f="due" value="${esc(i.due)}"${ro}></label></div></details>
      </aside>
      <div class="item-main">
        <h3 class="section">Description</h3><div id="bodybox"></div>
        ${i.type === "subtask" ? "" : `<h3 class="section">${i.type === "epic" ? "Issues in this epic" : "Sub-tasks"}${i.children ? ` <span class="quiet">${i.children_done}/${i.children} done</span>` : ""}</h3>
          <div class="subs">${i.subitems.map(k => `<button class="row" data-open="${esc(k.key)}">${typeIcon(k.type)}<span class="key">${esc(k.key)}</span><span class="t">${mdInline(k.title)}</span>${statusChip(k)}${avatar(k.assignee)}</button>`).join("")}</div>
          ${canEdit() ? `<form class="addbar" id="addsub"><label class="sr" for="subtitle">New</label><input class="input" id="subtitle" placeholder="Add ${i.type === "epic" ? "a task" : "a sub-task"}" maxlength="300"><button class="btn">Add</button></form>` : ""}`}
        <h3 class="section" id="comments">Comments${i.comments.length ? ` <span class="quiet">${i.comments.length}</span>` : ""}</h3>
        ${canEdit() ? '<form id="addcomment"><label class="sr" for="comment">Add a comment</label><textarea class="input short" id="comment" placeholder="Add a comment"></textarea><div class="addbar"><button class="btn primary">Save</button></div></form>' : ""}
        <div class="comment-list">${[...i.comments].reverse().map(c => `<div class="comment">${avatar(c.user)}<div><span class="who">${esc(c.user || "Someone")}</span><span class="when">${when(c.at)}</span><div class="body-md">${mdToHtml(c.body)}</div></div></div>`).join("") || '<p class="quiet">None yet.</p>'}</div>
        <h3 class="section">History</h3>
        ${i.activity.map(a => a.field === "project" ? `<p class="history"><b>${esc(a.user || "Someone")}</b> moved it from ${esc(a.old)} to ${esc(a.new)}, ${when(a.at)}</p>` : `<p class="history"><b>${esc(a.user || "Someone")}</b> changed ${esc(a.field.replace("_id", "").replace("_date", ""))}${a.new !== null && a.field !== "assignee_id" && a.field !== "parent_id" && a.field !== "labels" ? ` to ${esc(a.new)}` : ""}, ${when(a.at)}</p>`).join("") || '<p class="history">Made by ' + esc(i.created_by || "someone") + ", " + when(i.created) + ".</p>"}
        ${canEdit() ? `<div class="danger-row">${i.type !== "subtask" && state.projects.length > 1 ? '<button class="btn" id="moveproject">Move to project…</button>' : ""}<button class="btn danger" id="del">Delete ticket</button></div>` : ""}
      </div>
    </div>
  </div>`, true);
  if (wholePage) s.classList.add("whole");
  s.dataset.item = i.key;
  s.querySelector("#close").onclick = () => closeShade(s);
  s.querySelectorAll("[data-open]").forEach(b => { b.onclick = () => openItem(b.dataset.open); });
  const reopen = async () => { await refresh(); await openItem(i.key); };
  // On a refusal, redraw too, so the page doesn't keep showing a change that didn't happen.
  const save = attempt(async change => {
    try { await api("PATCH", `/api/items/${i.key}`, change); } finally { await reopen(); }
  });
  const title = s.querySelector("#title");
  // A textarea so a long title wraps on a phone. It grows to fit, and Enter saves rather than adding a line.
  const fit = () => { title.style.height = "auto"; title.style.height = title.scrollHeight + "px"; };
  fit(); title.oninput = fit;
  title.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } };
  title.onchange = () => { if (title.value.trim()) save({ title: title.value.replace(/\s*\n\s*/g, " ") }); else title.value = i.title; };
  s.querySelectorAll("[data-f]").forEach(el => {
    el.onchange = () => {
      const f = el.dataset.f;
      save({ [f]: f === "labels" ? el.value.split(",").map(x => x.trim()).filter(Boolean) : el.value || null });
    };
  });
  // Type and parent depend on each other, so they're saved together. A sub-task can't exist without a parent, so that change waits for one.
  const typeField = s.querySelector('[data-f="type"]'), parentField = s.querySelector('[data-f="parent"]');
  typeField.onchange = () => {
    const kind = typeField.value;
    const keep = kind !== "epic" && kind !== "subtask" && i.parent_type === "epic";
    parentField.innerHTML = parentOptions(kind, keep ? i.parent : "", i.project);
    if (kind === "subtask") return toast("Now pick the story, task or bug it belongs to.");
    save({ type: kind, parent: keep ? i.parent : null });
  };
  parentField.onchange = () => save({ type: typeField.value, parent: parentField.value || null });
  const moveProject = s.querySelector("#moveproject");
  if (moveProject) moveProject.onclick = () => openMoveProject(i);
  const del = s.querySelector("#del");
  if (del) del.onclick = attempt(async () => {
    if (!confirm(`Delete ${i.key}${i.children ? ` and the ${i.children} under it` : ""}? This can't be undone.`)) return;
    await api("DELETE", `/api/items/${i.key}`);
    closeShade(s); await refresh();
  });
  const bodyBox = s.querySelector("#bodybox");
  // An Edit button rather than tapping the text, so selecting words or scrolling on a phone never opens the editor.
  const showBody = () => {
    bodyBox.innerHTML = `<div class="body">${i.body ? mdToHtml(i.body) : '<p class="quiet">No description yet.</p>'}</div>
      ${canEdit() ? `<button class="btn" id="editbody">${i.body ? "Edit description" : "Add a description"}</button>` : ""}`;
    const open = bodyBox.querySelector("#editbody");
    if (!open) return;
    open.onclick = () => {
      bodyBox.innerHTML = `<textarea class="input tall" id="bodyedit" aria-label="Description">${esc(i.body)}</textarea><div class="addbar"><button class="btn primary" id="bsave">Save description</button><button class="btn" id="bcancel">Cancel</button></div>`;
      bodyBox.querySelector("#bsave").onclick = () => save({ body: bodyBox.querySelector("#bodyedit").value });
      bodyBox.querySelector("#bcancel").onclick = showBody;
      bodyBox.querySelector("#bodyedit").focus();
    };
  };
  showBody();
  const sub = s.querySelector("#addsub");
  if (sub) sub.onsubmit = attempt(async e => {
    e.preventDefault();
    const t = s.querySelector("#subtitle").value.trim();
    if (!t) return;
    await api("POST", "/api/items", { project: i.project, type: i.type === "epic" ? "task" : "subtask", title: t, parent: i.key, status: st(i)?.is_done ? undefined : i.status });
    await reopen();
  });
  const add = s.querySelector("#addcomment");
  if (add) add.onsubmit = attempt(async e => {
    e.preventDefault();
    const t = s.querySelector("#comment").value.trim();
    if (!t) return;
    await api("POST", `/api/items/${i.key}/comments`, { body: t });
    s.querySelector("#comment").value = "";
    await reopen();
  });
  return s;
}

// A sub-task never gets here: it moves with its parent.
function openMoveProject(i) {
  const s = shade(`<form class="dialog"><h2>Move ${esc(i.key)} to another project</h2><p class="err" hidden></p>
    <label class="field">Project<select class="input" name="to">${state.projects.filter(p => p.key !== i.project).map(p => `<option value="${esc(p.key)}">${esc(p.name)} (${esc(p.key)})</option>`).join("")}</select></label>
    <ul class="move-notes"><li>It gets a new key there. ${esc(i.key)} keeps working and leads to it.</li>
      <li>Its comments, history and labels come too${i.children ? ", and so does everything under it" : ""}.</li>
      <li>It keeps its column if the project has a matching one (the same short name). Otherwise it starts in the first column.</li>
      ${i.parent ? `<li>It leaves its epic, ${esc(i.parent)}, behind.</li>` : ""}</ul>
    <div class="addbar"><button class="btn primary">Move</button><button class="btn" type="button" id="cancel">Cancel</button></div></form>`, true);
  const f = s.querySelector("form");
  s.querySelector("#cancel").onclick = () => closeShade(s);
  f.onsubmit = async e => {
    e.preventDefault();
    const go = f.querySelector(".primary");
    go.disabled = true;  // a second tap would only be refused, as it has already moved
    try {
      const moved = await api("POST", `/api/items/${encodeURIComponent(i.key)}/move-project`, { project: f.to.value });
      closeShade(s);
      toast(`${i.key} is now ${moved.key}.`);
      await refresh(); await openItem(moved.key);
    } catch (err) { const p = f.querySelector(".err"); p.textContent = err.message; p.hidden = false; go.disabled = false; }
  };
  f.to.focus();
}

function openFromAddress() {
  const page = new URLSearchParams(location.search).get("issue");
  const key = page || location.hash.slice(1);
  if (!/^[A-Z0-9]+-\d+$/.test(key)) return;
  wholePage = !!page;
  openItem(key);
}

// --- Settings: me, tokens, and for admins, projects and users ---

async function openSettings() {
  const tokens = await api("GET", "/api/tokens");
  const admin = state.me.role === "admin";
  const s = shade(`<div class="dialog"><h2>Settings</h2><p class="quiet">Signed in as ${esc(state.me.name)} (${esc(state.me.role)}).</p>
    <h3 class="section">Your name</h3><form class="addbar" id="rename"><label class="sr" for="myname">Your name</label><input class="input" id="myname" value="${esc(state.me.name)}" autocapitalize="none" autocomplete="username" maxlength="80" required><button class="btn">Save name</button></form>
    <h3 class="section">Done columns</h3><form class="addbar" id="donedays"><label class="field">Days of finished tickets to show on the board (0 shows all)<input class="input" id="days" type="number" inputmode="numeric" min="0" max="3650" step="1" value="${esc(state.me.done_days ?? 14)}" required></label><button class="btn">Save</button></form>
    <h3 class="section">Look</h3><div class="addbar" id="themes">${Object.entries(THEMES).map(([k, v]) => `<button class="btn" type="button" data-theme-pick="${k}" aria-pressed="${(state.theme || "auto") === k}">${v}</button>`).join("")}</div>
    ${admin ? `<h3 class="section">Projects</h3>${state.projects.map(p => `<div class="table-row"><b>${esc(p.name)}</b><span class="quiet">${esc(p.key)}</span><button class="btn" data-columns="${esc(p.key)}">Columns</button></div>`).join("")}
      <div class="addbar"><button class="btn" type="button" id="addproject">+ New project</button></div>
      <h3 class="section">People</h3><div id="people"></div>
      <form class="addbar" id="adduser"><label class="sr" for="uname">Name</label><input class="input" id="uname" placeholder="Name" autocapitalize="none" required><label class="sr" for="upass">Password</label><input class="input" id="upass" type="password" placeholder="Password" autocomplete="new-password" minlength="8" required><label class="sr" for="urole">Role</label><select class="input" id="urole"><option>member</option><option>viewer</option><option>admin</option></select><button class="btn">Add</button></form>` : ""}
    ${canEdit() ? `<h3 class="section">API tokens</h3><p class="quiet">For agents and scripts. A token acts as you.</p><div id="tokens">${tokens.map(t => `<div class="table-row"><b>${esc(t.label)}</b><span class="quiet">${t.last_used ? "used " + when(t.last_used) : "not used yet"}</span><button class="btn danger" data-token="${t.id}">Revoke</button></div>`).join("")}</div>
      <div id="newtoken"></div><form class="addbar" id="addtoken"><label class="sr" for="tlabel">What is it for?</label><input class="input" id="tlabel" placeholder="What is it for?" required><button class="btn">Create token</button></form>` : ""}
    <h3 class="section">Change password</h3><form class="addbar" id="pw"><label class="sr" for="oldpw">Old password</label><input class="input" id="oldpw" type="password" placeholder="Old" autocomplete="current-password" required><label class="sr" for="newpw">New password</label><input class="input" id="newpw" type="password" placeholder="New" autocomplete="new-password" minlength="8" required><button class="btn">Change password</button></form>
    <div class="addbar"><button class="btn" id="out">Sign out</button><button class="btn" id="close">Close</button></div></div>`, true);
  s.querySelector("#close").onclick = () => closeShade(s);
  const again = async () => { closeShade(s); state.users = await api("GET", "/api/users"); state.projects = await api("GET", "/api/projects"); await openSettings(); };
  s.querySelector("#out").onclick = attempt(async () => { await api("POST", "/api/logout", {}); closeShade(s); state.me = null; drawLogin(); });
  s.querySelector("#rename").onsubmit = attempt(async e => {
    e.preventDefault();
    const old = state.me.name;
    Object.assign(state.me, await api("PATCH", "/api/me", { name: s.querySelector("#myname").value }));
    if (state.assignee === old) state.assignee = state.me.name;
    state.users = await api("GET", "/api/users");  // before the redraw, so the assignee menu has the new name
    await load(); drawShell();  // cards name the assignee, so they change too
    await again();
    toast("Name saved.");
  });
  s.querySelector("#donedays").onsubmit = attempt(async e => {
    e.preventDefault();
    Object.assign(state.me, await api("PATCH", "/api/me", { done_days: Number(s.querySelector("#days").value) }));
    await load(); drawShell();
    toast("Saved.");
  });
  s.querySelectorAll("[data-theme-pick]").forEach(b => {
    b.onclick = () => {
      state.theme = b.dataset.themePick; applyTheme(); remember(); drawShell();
      s.querySelectorAll("[data-theme-pick]").forEach(x => x.setAttribute("aria-pressed", x === b));
    };
  });
  s.querySelector("#pw").onsubmit = attempt(async e => {
    e.preventDefault();
    await api("POST", "/api/password", { old: s.querySelector("#oldpw").value, new: s.querySelector("#newpw").value });
    e.target.reset(); toast("Password changed.");
  });
  s.querySelectorAll("[data-token]").forEach(b => { b.onclick = attempt(async () => { await api("DELETE", `/api/tokens/${b.dataset.token}`); await again(); }); });
  const addToken = s.querySelector("#addtoken");
  if (addToken) addToken.onsubmit = attempt(async e => {
    e.preventDefault();
    const made = await api("POST", "/api/tokens", { label: s.querySelector("#tlabel").value });
    // Shown once: only its fingerprint is stored.
    s.querySelector("#newtoken").innerHTML = `<p>Copy this now. It won't be shown again.</p><p class="token">${esc(made.token)}</p>`;
    e.target.reset();
  });
  if (!admin) return;
  s.querySelectorAll("[data-columns]").forEach(b => { b.onclick = () => { closeShade(s); openColumns(b.dataset.columns); }; });
  const people = s.querySelector("#people");
  people.innerHTML = state.users.map(u => `<div class="table-row"><b>${esc(u.name)}</b>
    <label class="sr" for="role-${esc(u.name)}">Role</label><select class="input" id="role-${esc(u.name)}" data-user="${esc(u.name)}">${["admin", "member", "viewer"].map(r => `<option${r === u.role ? " selected" : ""}>${r}</option>`).join("")}</select>
    <button class="btn" data-active="${esc(u.name)}" data-to="${u.active ? "off" : "on"}">${u.active ? "Disable" : "Enable"}</button></div>`).join("");
  people.querySelectorAll("select[data-user]").forEach(el => { el.onchange = attempt(async () => { try { await api("PATCH", `/api/users/${encodeURIComponent(el.dataset.user)}`, { role: el.value }); } finally { await again(); } }); });
  people.querySelectorAll("[data-active]").forEach(b => { b.onclick = attempt(async () => { await api("PATCH", `/api/users/${encodeURIComponent(b.dataset.active)}`, { active: b.dataset.to === "on" }); await again(); }); });
  s.querySelector("#adduser").onsubmit = attempt(async e => {
    e.preventDefault();
    await api("POST", "/api/users", { name: s.querySelector("#uname").value, password: s.querySelector("#upass").value, role: s.querySelector("#urole").value });
    await again();
  });
  s.querySelector("#addproject").onclick = () => { closeShade(s); openNewProject(); };
}

// --- Which projects the All projects view shows: this person's own choice, kept on the server ---

function openProjects() {
  const hidden = new Set(state.me.hidden_projects || []);
  const s = shade(`<form class="dialog"><h2>All projects: which to show</h2><p class="quiet">Your own view. Pick one project or several.</p><p class="err" hidden></p>
    ${state.projects.map(p => `<label class="check pick-row"><input type="checkbox" value="${esc(p.key)}"${hidden.has(p.key) ? "" : " checked"}> ${esc(p.name)} <span class="quiet">${esc(p.key)}</span></label>`).join("")}
    <div class="addbar"><button class="btn primary">Show these</button><button class="btn" type="button" id="cancel">Cancel</button></div></form>`, true);
  s.querySelector("#cancel").onclick = () => closeShade(s);
  s.querySelector("form").onsubmit = async e => {
    e.preventDefault();
    const err = s.querySelector(".err"), boxes = [...s.querySelectorAll("input[type=checkbox]")];
    if (!boxes.some(b => b.checked)) { err.textContent = "Pick at least one project."; err.hidden = false; return; }
    try {
      state.me.hidden_projects = await api("PUT", "/api/me/projects", { hidden: boxes.filter(b => !b.checked).map(b => b.value) });
      closeShade(s); state.epic = ""; await load(); drawShell();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
}

// --- Columns: edited as a list, then saved all at once ---

async function openColumns(key) {
  const project = state.projects.find(p => p.key === key);
  const admin = state.me.role === "admin";
  const items = await api("GET", `/api/items?project=${encodeURIComponent(key)}`);
  const count = slug => items.filter(i => i.status === slug).length;
  const was = state.me.hidden?.[key] || [];
  const cols = project.statuses.map(c => ({ slug: c.slug, name: c.name, is_done: !!c.is_done, color: c.color, show: !was.includes(c.slug) }));
  const removed = [];
  const s = shade(`<form class="dialog"><h2>Columns: ${esc(project.name)}</h2>
    <p class="quiet">Show or hide a column on your own board. ${admin ? "Name, order and removal change it for everyone." : "An admin can change the columns themselves."}</p><p class="err" hidden></p><div id="cols"></div>
    ${admin ? '<button class="btn" type="button" id="addcol">Add a column</button><div id="moves"></div>' : ""}
    <div class="addbar"><button class="btn primary">Save columns</button><button class="btn" type="button" id="cancel">Cancel</button></div></form>`, true);
  const box = s.querySelector("#cols"), moves = s.querySelector("#moves");
  const draw = () => {
    box.innerHTML = cols.map((c, n) => `<div class="col-row" data-n="${n}">
      ${admin ? `<label class="sr" for="col${n}">Name</label><input class="input col-name" id="col${n}" maxlength="40" value="${esc(c.name)}" required>` : `<b class="col-name">${esc(c.name)}</b>`}
      <span class="col-tools"><label class="check"><input type="checkbox" data-show${c.show ? " checked" : ""}> Show</label>
      ${admin ? `<label class="check"><input type="checkbox" data-done${c.is_done ? " checked" : ""}> Done</label>
      <button class="btn" type="button" data-up aria-label="Move ${esc(c.name)} left"${n ? "" : " disabled"}>←</button>
      <button class="btn" type="button" data-down aria-label="Move ${esc(c.name)} right"${n < cols.length - 1 ? "" : " disabled"}>→</button>
      <button class="btn danger" type="button" data-remove aria-label="Remove ${esc(c.name)}"${cols.length > 1 ? "" : " disabled"}>Remove</button>` : ""}</span>
      ${admin ? `<span class="swatches" role="group" aria-label="Colour of ${esc(c.name || "the new column")}">${Object.entries(COLORS).map(([k, v]) => `<button class="sw tint-${k}" type="button" data-color="${k}" aria-label="${v}" title="${v}" aria-pressed="${c.color === k}"></button>`).join("")}
        <span class="quiet">${c.color ? COLORS[c.color] : "No colour"}</span><button class="btn link" type="button" data-color=""${c.color ? "" : " disabled"}>Reset colour</button></span>` : ""}</div>`).join("");
    box.querySelectorAll(".col-row").forEach(row => {
      const n = +row.dataset.n;
      row.querySelector("[data-show]").onchange = e => { cols[n].show = e.target.checked; };
      if (!admin) return;
      row.querySelector("input.col-name").oninput = e => { cols[n].name = e.target.value; };
      row.querySelector("[data-done]").onchange = e => { cols[n].is_done = e.target.checked; };
      row.querySelector("[data-up]").onclick = () => { [cols[n - 1], cols[n]] = [cols[n], cols[n - 1]]; draw(); };
      row.querySelector("[data-down]").onclick = () => { [cols[n + 1], cols[n]] = [cols[n], cols[n + 1]]; draw(); };
      row.querySelectorAll("[data-color]").forEach(b => {
        b.onclick = () => {
          cols[n].color = b.dataset.color || null; draw();
          const again = box.querySelector(`[data-n="${n}"]`);  // keep a keyboard user's place; Reset is switched off once used
          (again.querySelector(`[data-color="${b.dataset.color}"]:not(:disabled)`) || again.querySelector(".sw")).focus();
        };
      });
      row.querySelector("[data-remove]").onclick = () => {
        const full = cols[n].slug && count(cols[n].slug);
        // Cards can only move to a saved column, so a new one has to be saved before the last old one goes.
        if (full && !cols.some((c, k) => k !== n && c.slug)) return toast("Save the new column first, then remove this one.");
        const [gone] = cols.splice(n, 1);
        if (full) removed.push(gone);
        draw();
      };
    });
    if (!moves) return;
    // Only columns that already exist can take cards: a new one has no slug until it's saved.
    const targets = cols.filter(c => c.slug);
    moves.innerHTML = removed.map((r, n) => `<label class="field">Move the ${count(r.slug)} items in ${esc(r.name)} to
      <select class="input" data-move="${n}">${targets.map(c => `<option value="${esc(c.slug)}"${c.slug === r.to ? " selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>`).join("");
    moves.querySelectorAll("select").forEach(el => { removed[+el.dataset.move].to = el.value; });
    moves.querySelectorAll("select").forEach(el => { el.onchange = () => { removed[+el.dataset.move].to = el.value; }; });
  };
  draw();
  const add = s.querySelector("#addcol");
  if (add) add.onclick = () => { cols.push({ name: "", is_done: false, show: true }); draw(); box.querySelector(".col-row:last-child input.col-name").focus(); };
  s.querySelector("#cancel").onclick = () => closeShade(s);
  s.querySelector("form").onsubmit = async e => {
    e.preventDefault();
    const err = s.querySelector(".err");
    if (!cols.some(c => c.show)) { err.textContent = "Keep at least one column showing."; err.hidden = false; return; }
    try {
      let saved = project;
      if (admin) saved = await api("PUT", `/api/projects/${encodeURIComponent(key)}/columns`, { columns: cols.map(c => ({ slug: c.slug, name: c.name, is_done: c.is_done, color: c.color || null })), move: Object.fromEntries(removed.map(r => [r.slug, r.to])) });
      // A new column only has a slug once saved. It starts showing unless it was unticked here, so match by name.
      const hide = cols.filter(c => !c.show).map(c => c.slug || saved.statuses.find(x => x.name === c.name.trim())?.slug).filter(Boolean);
      const hidden = await api("PUT", `/api/me/hidden/${encodeURIComponent(key)}`, { columns: hide });
      state.me.hidden = { ...state.me.hidden, [key]: hidden };
      closeShade(s);
      state.projects = await api("GET", "/api/projects");
      await load(); drawShell();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
}

// Agents change things too, so keep the board fresh while it's on screen.
// One refresh at a time: on a slow line, a new one would otherwise cancel the last before it ever arrived.
let refreshing = false;
setInterval(async () => {
  if (refreshing || !state.me || document.hidden || activeDrag || document.querySelector(".shade")) return;
  refreshing = true;
  try { await attempt(refresh)(); } finally { refreshing = false; }
}, 15000);

start().catch(() => drawLogin());
