// The app shell: sidebar, top bar, hash routes, and live refresh from the journal stream.
import { get, post, subscribe } from "./api.js";
import { html, mount, raw } from "./html.js";
import * as agents from "./views/agents.js";
import * as board from "./views/board.js";
import * as memory from "./views/memory.js";
import * as overview from "./views/overview.js";
import * as settings from "./views/settings.js";
import * as ticketView from "./views/ticket.js";
import * as workflow from "./views/workflow.js";

const ICONS = {
  overview: '<rect x="2.3" y="2.3" width="5" height="5" rx="1"/><rect x="8.7" y="2.3" width="5" height="5" rx="1"/><rect x="2.3" y="8.7" width="5" height="5" rx="1"/><rect x="8.7" y="8.7" width="5" height="5" rx="1"/>',
  board: '<rect x="2" y="2.5" width="3.4" height="11" rx="1"/><rect x="6.3" y="2.5" width="3.4" height="7.4" rx="1"/><rect x="10.6" y="2.5" width="3.4" height="9.2" rx="1"/>',
  workflow: '<rect x="1.4" y="5.6" width="5" height="5" rx="1.2"/><rect x="9.6" y="5.6" width="5" height="5" rx="1.2"/><path d="M6.4 8.1h3.2"/>',
  agents: '<circle cx="8" cy="5.6" r="2.6"/><path d="M3 13.6c.8-2.6 2.8-3.8 5-3.8s4.2 1.2 5 3.8"/>',
  memory: '<ellipse cx="8" cy="3.8" rx="5.2" ry="1.9"/><path d="M2.8 3.8v8.4c0 1 2.3 1.9 5.2 1.9s5.2-.9 5.2-1.9V3.8"/><path d="M2.8 8c0 1 2.3 1.9 5.2 1.9s5.2-.9 5.2-1.9"/>',
  settings: '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.6v2M8 12.4v2M1.6 8h2M12.4 8h2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4M3.5 12.5l1.4-1.4M11.1 4.9l1.4-1.4"/>',
};
const NAV = [
  ["OPERATE", [["overview", "Overview"], ["board", "Task board"]]],
  ["ORCHESTRATE", [["workflow", "Workflow"], ["agents", "Agents"]]],
  ["PROJECT", [["memory", "Memory"], ["settings", "Settings"]]],
];
const SCREENS = { overview, board, ticket: ticketView, workflow, agents, memory, settings };

export const app = {
  project: "",
  scope: undefined, // the configure screens' scope: "" is the defaults, else a project
  dirty: false, // a configure screen holds unsaved edits; live refresh waits
  query: "",
  window: "today",
  live: false,
  version: "",
  overview: null,
  refresh: () => show(),
  toast,
  post: async (path, body) => {
    try {
      const result = await post(path, body);
      await show();
      return result;
    } catch (error) {
      toast(error.message, true);
      return null;
    }
  },
};

function route() {
  const [name, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  return { name: name || "overview", arg: rest.join("/") };
}

function icon(name) {
  return raw(`<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke-width="1.4" aria-hidden="true">${ICONS[name]}</svg>`);
}

function nav(current) {
  const data = app.overview;
  const open = data ? data.sessions.length + data.gates.length + data.queue.ready + data.queue.blocked + data.queue.parked : "";
  const counts = { board: open, memory: data?.links_broken || undefined };
  const alarms = { memory: Boolean(data?.links_broken) };
  const pool = (data?.slots ?? []).map(
    (slot) => html`<div class="pool-row"><span class="dot ${slot.total === 0 ? "" : slot.used ? "busy" : "on"}"></span>${slot.provider}<span>${slot.total === 0 ? "off" : `${slot.used}/${slot.total}`}</span></div>`,
  );
  mount(
    document.getElementById("nav"),
    html`<div class="brand">${raw('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F0883E" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.6 20.4 7.3v9.4L12 21.4 3.6 16.7V7.3z"/><path d="M12 21.4v-9.2M3.6 7.3 12 12.2l8.4-4.9"/></svg>')}<b>harness</b><span>${app.version}</span></div>
      ${NAV.map(
        ([title, links]) => html`<div class="nav-group"><div class="nav-title">${title}</div>${links.map(
          ([name, label]) => html`<a class="nav-link" href="#/${name}" ${current === name ? raw('aria-current="page"') : ""}>${icon(name)}${label}${counts[name] !== undefined && counts[name] !== "" ? html`<span class="nav-count ${alarms[name] ? "alarm" : ""}" ${alarms[name] ? raw('title="links need a fix"') : ""}>${counts[name]}</span>` : ""}</a>`,
        )}</div>`,
      )}
      <div class="nav-group"><div class="nav-title">CLI POOL</div><div class="pool">${pool.length ? pool : html`<span class="faint">no store yet</span>`}</div></div>
      <div class="nav-foot"><span class="dot ${app.live ? "on" : ""}"></span>${app.live ? "live" : "reconnecting"}</div>`,
  );
}

function top() {
  const projects = app.overview?.projects ?? [];
  mount(
    document.getElementById("top"),
    html`<label class="sr-only" for="project">Project</label>
      <select id="project">${[["", "all projects"], ...projects.map((p) => [p, p])].map(
        ([value, label]) => html`<option value="${value}" ${value === app.project ? raw("selected") : ""}>${label}</option>`,
      )}</select>
      <label class="sr-only" for="q">Search tickets</label>
      <input id="q" type="search" placeholder="Search tickets, ids, projects…" value="${app.query}">
      <button class="btn mono" type="button" data-copy="/to-ticket">/to-ticket</button>
      <button class="btn primary mono" type="button" data-copy="/to-loop">/to-loop</button>`,
  );
}

function placeholder(name) {
  return html`<div class="page"><div class="page-head"><div><h1>${name[0].toUpperCase() + name.slice(1)}</h1><p>This screen arrives in the next milestone.</p></div></div></div>`;
}

let showing = 0;
let shown = ""; // the route on screen; a slow load of another one shows Loading
async function show() {
  const ticket = ++showing;
  const { name, arg } = route();
  const slow = setTimeout(() => {
    if (ticket === showing && name !== shown) mount(fresh(), html`<div class="page"><div class="panel"><div class="empty">Loading…</div></div></div>`);
  }, 400);
  try {
    app.overview = await get(`/api/overview?window=${app.window}`);
    const screen = SCREENS[name];
    const data = screen ? await screen.load(app, arg) : null;
    const body = screen ? screen.view(data, app) : placeholder(name);
    if (ticket !== showing) return;
    nav(name === "ticket" ? "board" : name);
    if (!document.getElementById("q") || document.activeElement?.id !== "q") top();
    const root = fresh();
    mount(root, body);
    screen?.bind?.(root, app, data);
    shown = name;
  } catch (error) {
    shown = "";
    mount(document.getElementById("view"), html`<div class="page"><div class="panel"><div class="empty">${error.message}</div></div></div>`);
  } finally {
    clearTimeout(slow);
  }
}

// A new view element per render, so listeners bound to the last one go with it.
function fresh() {
  const old = document.getElementById("view");
  const root = old.cloneNode(false);
  old.replaceWith(root);
  return root;
}

let toastTimer = 0;
function toast(message, error = false) {
  document.querySelector(".toast")?.remove();
  const box = document.createElement("div");
  box.className = `toast${error ? " error" : ""}`;
  box.setAttribute("role", "status");
  box.textContent = message;
  document.body.append(box);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.remove(), 4000);
}

document.addEventListener("change", (event) => {
  if (event.target.id === "project") {
    app.project = event.target.value;
    show();
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "q") {
    app.query = event.target.value;
    if (route().name === "board") show();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.target.id === "q" && event.key === "Enter" && route().name !== "board") location.hash = "#/board";
});
document.addEventListener("click", async (event) => {
  const copy = event.target.closest("[data-copy]");
  if (copy) {
    const command = copy.dataset.copy;
    await navigator.clipboard?.writeText(command).catch(() => {});
    toast(copy.dataset.note || `Run ${command} in your agent; it is copied.`);
  }
});

let pending = 0;
subscribe(
  () => {
    clearTimeout(pending);
    pending = setTimeout(() => app.dirty || show(), 300);
  },
  (live) => {
    if (app.live !== live) {
      app.live = live;
      nav(route().name);
    }
  },
);
window.addEventListener("hashchange", () => {
  app.dirty = false;
  show();
});
get("/api/meta").then((meta) => {
  app.version = meta.version;
  show();
});
