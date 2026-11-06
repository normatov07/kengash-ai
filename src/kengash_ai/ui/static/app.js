// The app shell: sidebar, top bar, hash routes, and live refresh from the journal stream.
// A screen module exports load(app, arg), view(data, app) and optionally bind(root, app,
// data, bar), top(data, app) (its own top bar) and foot(data, app) (its sidebar card).
import { get, post, subscribe } from "./api.js";
import { html, mount } from "./html.js";
import { brand, icon } from "./icons.js";
import * as agents from "./views/agents.js";
import * as board from "./views/board.js";
import * as memory from "./views/memory.js";
import * as overview from "./views/overview.js";
import * as settings from "./views/settings.js";
import * as ticketView from "./views/ticket.js";
import * as workflow from "./views/workflow.js";

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
  navOpen: false, // below 900 px the sections fold into a menu
  query: "",
  window: "today",
  live: false,
  version: "",
  overview: null,
  from: "#/board", // where the ticket sheet closes back to
  ticketTab: "", // the tab the next ticket opens on: "live" from a running session or card
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
  return { name: name || "overview", arg: decodeURIComponent(rest.join("/")) };
}

function navName(name) {
  return name === "ticket" ? "board" : name;
}

function nav(current) {
  const data = app.overview;
  const counts = {
    board: data ? String(data.tickets_total) : "",
    agents: data?.agents_total ? `${data.agents_on}/${data.agents_total}` : "",
    memory: data?.links_broken ? String(data.links_broken) : "",
  };
  mount(
    document.getElementById("nav-main"),
    html`<div class="brand">${brand()}<b>kengash</b><span class="live ${app.live ? "on" : ""}" title="${app.live ? "live: updates as the journal grows" : "reconnecting to the journal"}"></span><span>${app.version}</span><button class="nav-toggle" type="button" data-nav-toggle aria-controls="nav" aria-expanded="${app.navOpen ? "true" : "false"}" aria-label="${app.navOpen ? "Close the menu" : "Open the menu"}">${icon(app.navOpen ? "close" : "menu", { size: 15, width: 1.7 })}</button></div>
      ${NAV.map(
        ([title, links]) => html`<div class="nav-group"><div class="nav-title">${title}</div>${links.map(
          ([name, label]) => html`<a class="nav-link" href="#/${name}" ${current === name ? html`aria-current="page"` : ""}>${icon(name, { width: 1.4 })}${label}${counts[name] ? html`<span class="nav-count ${name === "memory" ? "alarm" : ""}" ${name === "memory" ? html`title="folder links that need a fix"` : ""}>${counts[name]}</span>` : ""}</a>`,
        )}</div>`,
      )}`,
  );
}

function openNav(open) {
  if (app.navOpen === open) return;
  app.navOpen = open;
  document.getElementById("nav").classList.toggle("open", open);
  nav(navName(route().name));
  if (open) document.querySelector("#nav [aria-current=page]")?.focus();
  else document.querySelector("[data-nav-toggle]")?.focus();
}

function defaultTop() {
  const projects = app.overview?.projects ?? [];
  return html`<label class="sr-only" for="project">Project</label>
    <select id="project" class="select">${[["", "all projects"], ...projects.map((p) => [p, p])].map(
      ([value, label]) => html`<option value="${value}" ${value === app.project ? "selected" : ""}>${label}</option>`,
    )}</select>
    <label class="sr-only" for="q">Search tickets</label>
    <input id="q" class="search" type="search" placeholder="Search tickets, ids, projects…" value="${app.query}">
    <button class="btn mono quiet" type="button" data-copy="/kengash:ticket">${icon("plus-square", { size: 13 })}/kengash:ticket</button>
    <button class="btn mono accent" type="button" data-copy="/kengash:loop">${icon("play", { size: 13, width: 1.8 })}/kengash:loop</button>`;
}

function placeholder(name) {
  return html`<div class="page"><div class="panel"><div class="empty">No screen called “${name}”. <a href="#/overview">Open the overview</a>.</div></div></div>`;
}

let showing = 0;
let shown = ""; // the route on screen; a slow load of another one shows Loading
async function show() {
  const ticket = ++showing;
  const { name, arg } = route();
  nav(navName(name)); // the nav follows the route at once, before any data arrives
  const slow = setTimeout(() => {
    if (ticket === showing && name !== shown) mount(fresh(), html`<div class="page"><div class="panel"><div class="empty">Loading…</div></div></div>`);
  }, 400);
  try {
    app.overview = await get(`/api/overview?window=${app.window}`);
    const screen = SCREENS[name];
    const data = screen ? await screen.load(app, arg) : null;
    const body = screen ? screen.view(data, app) : placeholder(name);
    if (ticket !== showing) return;
    nav(navName(name));
    const bar = document.getElementById("top");
    if (!bar.contains(document.activeElement) || shown !== name) mount(bar, screen?.top?.(data, app) ?? defaultTop());
    mount(document.getElementById("nav-foot"), screen?.foot?.(data, app) ?? "");
    const root = fresh();
    mount(root, body);
    document.body.dataset.screen = name;
    screen?.bind?.(root, app, data, bar);
    shown = name;
  } catch (error) {
    shown = "";
    if (ticket !== showing) return;
    mount(document.getElementById("top"), defaultTop());
    mount(document.getElementById("nav-foot"), "");
    const back = name === "ticket" ? html`<a href="#/board">Open the task board</a>` : html`<button class="linkish" type="button" data-retry>Try again</button>`;
    mount(fresh(), html`<div class="page"><div class="panel"><div class="empty error-state">${icon("warning", { size: 15, stroke: "var(--danger)", width: 1.6 })}<span>${error.message.replace(/^\w/, (c) => c.toUpperCase())}.</span>${back}</div></div></div>`);
    document.querySelector("[data-retry]")?.addEventListener("click", () => show());
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
  box.setAttribute("role", error ? "alert" : "status");
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
  if (event.target.id === "q") app.query = event.target.value;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && app.navOpen) openNav(false);
  if (event.target.id === "q" && event.key === "Enter" && route().name !== "board") location.hash = "#/board";
});
document.addEventListener("click", async (event) => {
  if (event.target.closest("[data-nav-toggle]")) return openNav(!app.navOpen);
  if (app.navOpen && (event.target.closest(".nav-link") || !event.target.closest("#nav"))) openNav(false);
  const copy = event.target.closest("[data-copy]");
  if (copy) {
    const command = copy.dataset.copy;
    await navigator.clipboard?.writeText(command).catch(() => {});
    toast(copy.dataset.note || `Run ${command} in your agent; it is copied.`);
  }
});

// A loop that dies or goes stale journals nothing, so Overview also reads again every 30 s
// while it is on screen (SP11 §5.4).
setInterval(() => {
  if (route().name === "overview" && !app.dirty && !document.hidden) show();
}, 30_000);

let pending = 0;
subscribe(
  () => {
    clearTimeout(pending);
    pending = setTimeout(() => app.dirty || show(), 300);
  },
  (live) => {
    if (app.live !== live) {
      app.live = live;
      nav(navName(route().name));
    }
  },
);
window.addEventListener("hashchange", (event) => {
  app.dirty = false;
  const before = new URL(event.oldURL).hash;
  if (!before.startsWith("#/ticket/")) app.from = before || "#/overview";
  show();
});
get("/api/meta")
  .then((meta) => (app.version = meta.version))
  .catch(() => {})
  .finally(show);
