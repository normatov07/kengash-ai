// Task board (canvas board Board): filters, step columns with their footers, ticket cards,
// group by status, project or importance, a sortable list view, and the importance legend.
import { get } from "../api.js";
import { clock } from "../format.js";
import { html, mount } from "../html.js";
import { icon } from "../icons.js";

const state = { view: "board", group: "status", importance: "", agent: "", text: "", sort: "updated", desc: true, only: "" };

// Each column's canvas palette: top bar, title, count pill, column and card tints, footer.
const TINTS = {
  in_queue: { bar: "#78828F", title: "#C4CBD4", pill: ["#22262C", "#A7B0BC"], col: ["#22272E", "#14171A"], card: ["#262B32", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  plan: { bar: "#68A4E0", title: "#68A4E0", pill: ["#1B2733", "#68A4E0"], col: ["#22272E", "#14171A"], card: ["#2C3A48", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  review_plan: { bar: "#B191E8", title: "#B191E8", pill: ["#241F33", "#B191E8"], col: ["#2B2538", "#14171A"], card: ["#332B44", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  implement: { bar: "#F0883E", title: "#F0883E", pill: ["#2A1E10", "#F0883E"], col: ["#332A1E", "#16171A"], card: ["#3A2E1E", "#1D1F22"], foot: ["#2A2318", "#9A845F"] },
  review_code: { bar: "#B191E8", title: "#B191E8", pill: ["#241F33", "#B191E8"], col: ["#2B2538", "#14171A"], card: ["#332B44", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  security: { bar: "#D8B24C", title: "#D8B24C", pill: ["#2A2320", "#D8B24C"], col: ["#332C1C", "#14171A"], card: ["#332C1C", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  run_tests: { bar: "#5FC08B", title: "#5FC08B", pill: ["#1E2A20", "#5FC08B"], col: ["#22302A", "#14171A"], card: ["#2E4030", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  docs: { bar: "#5FC08B", title: "#5FC08B", pill: ["#1E2A20", "#5FC08B"], col: ["#22302A", "#14171A"], card: ["#2E4030", "#1A1E22"], foot: ["#1F242A", "#7E8895"] },
  approve: { bar: "#EF7A72", title: "#EF7A72", pill: ["#3A2024", "#EF7A72"], col: ["#3A2A26", "#14171A"], card: ["#4A2B2B", "#1F1B1C"], foot: ["#1F242A", "#7E8895"] },
  done: { bar: "#5FC08B", title: "#5FC08B", pill: ["#1E2A20", "#5FC08B"], col: ["#22302A", "#14171A"], card: ["#262B32", "#181B1E"], foot: ["#1F242A", "#7E8895"] },
};
const IMPORTANCE = {
  critical: { color: "#EF7A72", soft: "#3A2024" },
  standard: { color: "#D8B24C", soft: "#2A2320" },
  simple: { color: "#68A4E0", soft: "#1B2733" },
};
const MAX_TAGS = 3;
const RED_CHIPS = new Set(["loop cap hit", "token cap hit", "needs approval", "failed"]);
const WARN_CHIPS = new Set(["stalled", "blocked", "parked"]);
const OK_CHIPS = new Set(["ready to merge"]);

export async function load(app) {
  if (app.query && app.query !== state.text) state.text = app.query; // the search box elsewhere hands over
  return get(`/api/board${app.project ? `?project=${encodeURIComponent(app.project)}` : ""}`);
}

function matches(card) {
  if (state.importance && card.importance !== state.importance) return false;
  if (state.agent && card.provider !== state.agent) return false;
  const text = state.text.trim().toLowerCase();
  return !text || `${card.id} ${card.title} ${card.project} ${card.tags.join(" ")}`.toLowerCase().includes(text);
}

function loopDots(card, color) {
  const atCap = card.loop >= card.loop_max;
  const fill = atCap ? "#EF7A72" : color;
  return html`<span class="loop"><span class="dots">${Array.from({ length: Math.min(card.loop_max, 10) }, (_, i) => html`<span style="background: ${i < card.loop ? fill : "#2C333B"}"></span>`)}</span><span class="${atCap ? "at-cap" : ""}">${card.loop}/${card.loop_max}</span></span>`;
}

function chipTone(chip) {
  return RED_CHIPS.has(chip) ? "red" : WARN_CHIPS.has(chip) ? "warn" : OK_CHIPS.has(chip) ? "ok" : "plain";
}

function card(item, key) {
  const tint = TINTS[key] ?? TINTS.in_queue;
  const imp = IMPORTANCE[item.importance] ?? IMPORTANCE.standard;
  const done = item.status.startsWith("done/");
  const queued = item.status.startsWith("in_queue/");
  const active = !done && !queued && !item.chip;
  const gated = RED_CHIPS.has(item.chip);
  const border = gated ? "#4A2B2B" : active ? tint.card[0] : key === "in_queue" || done ? tint.card[0] : "#262B32";
  const bg = gated ? "#1F1B1C" : active ? tint.card[1] : done ? "#181B1E" : "#1A1E22";
  const sub = item.status.split("/")[1];
  const head = done
    ? html`<span class="cbadge" style="background: #1E2A20; color: #5FC08B">${sub === "merged" ? icon("check", { size: 9, width: 2.2 }) : ""}${sub.replace("_", " ").toUpperCase()}</span><span class="end mono faint">${item.loop}/${item.loop_max}</span>`
    : html`<span class="cbadge" style="background: ${imp.soft}; color: ${imp.color}">${item.importance.toUpperCase()}</span>${queued
        ? html`<span class="end ctag ${item.parallel ? "par" : ""}">${item.parallel ? "parallel" : "serial"}</span>`
        : html`<span class="end">${loopDots(item, tint.bar)}</span>`}`;
  const chips = [];
  if (active && item.provider) chips.push(html`<span class="cprov" style="background: ${tint.pill[0]}; color: ${tint.pill[1]}"><span style="background: ${tint.pill[1]}"></span>${item.provider}</span>`);
  if (item.chip) chips.push(html`<span class="cchip ${chipTone(item.chip)}">${RED_CHIPS.has(item.chip) ? icon("bang", { size: 9, width: 2 }) : ""}${item.chip}</span>`);
  if (item.findings) chips.push(html`<span class="cchip red">${item.findings} ${item.findings === 1 ? "finding" : "findings"}</span>`);
  if (item.rejected) chips.push(html`<span class="cchip warn">plan rejected ${item.rejected}x</span>`);
  // tags (request step 6): the first three, then how many more; untagged cards add nothing
  for (const tag of item.tags.slice(0, MAX_TAGS)) chips.push(html`<span class="cchip plain">#${tag}</span>`);
  if (item.tags.length > MAX_TAGS) chips.push(html`<span class="cchip plain" title="${item.tags.slice(MAX_TAGS).join(", ")}">+${item.tags.length - MAX_TAGS}</span>`);
  const diff = item.added || item.removed ? html`<span class="end cdiff">+${item.added} −${item.removed}</span>` : "";
  return html`<a class="card" href="#/ticket/${item.id}" style="border-color: ${border}; border-left-color: ${done ? "#5FC08B" : imp.color}; background: ${bg}" title="${item.title}">
    <div class="card-top">${head}</div>
    <div class="card-title">${item.title}</div>
    ${chips.length || diff ? html`<div class="card-meta">${chips}${diff}</div>` : ""}
    <div class="card-foot"><span>${item.id}</span><span class="end">${done && item.done_at ? clock(item.done_at).slice(0, 5) : item.project}</span></div>
  </a>`;
}

function columnFoot(column) {
  const tint = TINTS[column.key] ?? TINTS.in_queue;
  if (column.key === "in_queue") return html`<button class="col-add" type="button" data-copy="/to-ticket" data-note="Copied: run /to-ticket in your agent to cut tickets from a plan.">${icon("plus", { size: 12, width: 1.9 })}<span class="long">Add with</span> /to-ticket</button>`;
  if (column.key === "done") return html`<button class="col-open" type="button" data-only="done">Open tasks/done</button>`;
  return html`<div class="col-note" style="color: ${tint.foot[1]}">${column.footer}</div>`;
}

function column(col, tint = TINTS[col.key] ?? TINTS.in_queue) {
  const cards = col.cards.filter(matches);
  const gate = col.footer.includes("blocking gate");
  return html`<section class="col" style="border-color: ${tint.col[0]}; background: ${tint.col[1]}" aria-label="${col.title}">
    <div class="col-bar" style="background: ${tint.bar}"></div>
    <div class="col-head"><h2 style="color: ${tint.title}" title="${col.title}">${col.title.toUpperCase()}</h2><span class="col-count" style="background: ${tint.pill[0]}; color: ${tint.pill[1]}">${cards.length}</span>
      <button class="col-more" type="button" data-only="${col.key}" aria-label="Show ${col.title} as a list" title="Show as a list">${icon("more", { size: 13, stroke: "none", width: 0 })}</button></div>
    <div class="col-cards">${cards.map((item) => card(item, col.key))}${gate && !cards.length ? html`<div class="col-empty">Blocking gate: a ticket stops here until it passes</div>` : !cards.length ? html`<div class="col-empty">${state.text || state.importance || state.agent ? "nothing matches" : "empty"}</div>` : ""}</div>
    <div class="col-foot" style="border-top-color: ${tint.foot[0]}">${columnFoot(col)}</div>
  </section>`;
}

function groups(data) {
  if (state.group === "status") return data.columns;
  const all = data.columns.flatMap((col) => col.cards.map((item) => ({ ...item, at: col.key })));
  const keys = state.group === "importance" ? ["critical", "standard", "simple"] : [...new Set(all.map((item) => item.project))].sort();
  return keys.map((key) => ({
    key: state.group === "importance" ? `imp-${key}` : "in_queue",
    title: key,
    footer: "",
    cards: all.filter((item) => (state.group === "importance" ? item.importance : item.project) === key),
  }));
}

function boardBody(data) {
  if (state.view === "list") return listBody(data);
  const cols = groups(data);
  return html`<div class="cols" style="--n: ${cols.length}">${cols.map((col) => {
    const imp = IMPORTANCE[col.title];
    return column(col, col.key.startsWith("imp-") ? { ...TINTS.in_queue, bar: imp.color, title: imp.color, pill: [imp.soft, imp.color] } : undefined);
  })}</div>`;
}

const LIST_COLUMNS = [["id", "ID"], ["title", "TITLE"], ["project", "PROJECT"], ["importance", "IMPORTANCE"], ["status", "STATUS"], ["loop", "LOOP"], ["provider", "AGENT"], ["added", "DIFF"], ["updated", "UPDATED"]];

function listBody(data) {
  const rows = data.columns
    .filter((col) => !state.only || col.key === state.only)
    .flatMap((col) => col.cards)
    .filter(matches)
    .sort((a, b) => {
      const [x, y] = [a[state.sort], b[state.sort]];
      const order = typeof x === "number" ? x - y : String(x).localeCompare(String(y));
      return state.desc ? -order : order;
    });
  return html`<section class="panel list-view">
    ${state.only ? html`<div class="panel-head"><h2>${data.columns.find((col) => col.key === state.only)?.title ?? state.only}</h2><span class="faint" style="font-size: 12px">${rows.length} tickets</span><button class="btn small quiet end" type="button" data-only="">Show every column</button></div>` : ""}
    <div class="table"><div class="rows">
      <div class="thead list-row">${LIST_COLUMNS.map(([key, label]) => html`<button type="button" class="l-${key} sort ${state.sort === key ? "on" : ""}" data-sort="${key}">${label}${state.sort === key ? (state.desc ? " ↓" : " ↑") : ""}</button>`)}</div>
      ${rows.length
        ? rows.map((item) => {
            const imp = IMPORTANCE[item.importance] ?? IMPORTANCE.standard;
            return html`<a class="trow list-row" href="#/ticket/${item.id}">
              <span class="l-id mono">${item.id}</span><span class="l-title ellipsis" title="${item.title}">${item.title}</span><span class="l-project ellipsis faint">${item.project}</span>
              <span class="l-importance"><span class="cbadge" style="background: ${imp.soft}; color: ${imp.color}">${item.importance.toUpperCase()}</span></span>
              <span class="l-status mono muted ellipsis">${item.status}${item.chip ? html` <span class="cchip ${chipTone(item.chip)}">${item.chip}</span>` : ""}</span>
              <span class="l-loop mono">${item.loop}/${item.loop_max}</span><span class="l-provider mono muted">${item.provider || "—"}</span>
              <span class="l-added mono"><span class="add">+${item.added}</span> <span class="del">−${item.removed}</span></span><span class="l-updated mono faint">${clock(item.updated).slice(0, 5)}</span>
            </a>`;
          })
        : html`<div class="empty">No ticket matches these filters.</div>`}
    </div></div>
  </section>`;
}

export function top(data, app) {
  const projects = app.overview?.projects ?? [];
  const agents = [...new Set(data.columns.flatMap((col) => col.cards.map((item) => item.provider)).filter(Boolean))].sort();
  return html`<label class="sr-only" for="project">Project</label>
    <select id="project" class="select">${[["", "all projects"], ...projects.map((p) => [p, p])].map(([value, label]) => html`<option value="${value}" ${value === app.project ? "selected" : ""}>${label}</option>`)}</select>
    <label class="sr-only" for="imp-filter">Importance</label>
    <select id="imp-filter" class="select sans quiet-select">${[["", "Importance"], ["critical", "critical"], ["standard", "standard"], ["simple", "simple"]].map(([value, label]) => html`<option value="${value}" ${value === state.importance ? "selected" : ""}>${label}</option>`)}</select>
    <label class="sr-only" for="agent-filter">Agent</label>
    <select id="agent-filter" class="select sans quiet-select">${[["", "Agent"], ...agents.map((a) => [a, a])].map(([value, label]) => html`<option value="${value}" ${value === state.agent ? "selected" : ""}>${label}</option>`)}</select>
    <label class="sr-only" for="bq">Filter tickets</label>
    <input id="bq" class="search" type="search" placeholder="Filter by title, tag or id…" value="${state.text}">
    <div class="segmented" role="group" aria-label="View">${[["board", "Board"], ["list", "List"]].map(([key, label]) => html`<button type="button" data-view="${key}" aria-pressed="${state.view === key ? "true" : "false"}">${label}</button>`)}</div>
    <button class="btn mono accent" type="button" data-copy="/to-loop">${icon("play", { size: 13, width: 1.8 })}/to-loop</button>`;
}

export function view(data, app) {
  const o = app.overview;
  const running = o ? o.sessions.filter((s) => !app.project || s.project === app.project).length : 0;
  const blocked = o ? o.queue.blocked + o.gates.filter((g) => !app.project || g.project === app.project).length : 0;
  return html`<div class="board-page">
    <div class="board-head">
      <h1>Task board</h1>
      <div class="board-stats"><span><span class="dot" style="background: var(--accent)"></span>${running} running</span><span><span class="dot" style="background: var(--danger)"></span>${blocked} blocked or waiting on you</span><span><span class="dot" style="background: var(--ok)"></span>${o?.done_today ?? 0} done today</span></div>
      <label class="group-by">Group by<select id="group-by" class="bare">${[["status", "status"], ["project", "project"], ["importance", "importance"]].map(([value, label]) => html`<option value="${value}" ${value === state.group ? "selected" : ""}>${label}</option>`)}</select>${icon("chevron", { size: 11, stroke: "#78828F", width: 1.7 })}</label>
    </div>
    <div class="board-body">${boardBody(data)}</div>
  </div>`;
}

export function foot(data) {
  return html`<div class="foot-card"><div class="nav-title">IMPORTANCE</div><div class="foot-rows sans">${["critical", "standard", "simple"].map(
    (key) => html`<div><span class="bar" style="background: ${IMPORTANCE[key].color}"></span>${key}<span class="end mono">${data.steps[key] ? `${data.steps[key]} steps` : "—"}</span></div>`,
  )}</div></div>`;
}

export function bind(root, app, data, bar) {
  const body = root.querySelector(".board-body");
  const paint = () => mount(body, boardBody(data));
  const syncBar = () => bar.querySelectorAll("[data-view]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.view === state.view ? "true" : "false"));
  bar.querySelector("#bq")?.addEventListener("input", (event) => {
    state.text = event.target.value;
    app.query = state.text;
    paint();
  });
  bar.querySelector("#imp-filter")?.addEventListener("change", (event) => {
    state.importance = event.target.value;
    paint();
  });
  bar.querySelector("#agent-filter")?.addEventListener("change", (event) => {
    state.agent = event.target.value;
    paint();
  });
  bar.querySelectorAll("[data-view]").forEach((button) =>
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      if (state.view === "board") state.only = "";
      syncBar();
      paint();
    }),
  );
  root.querySelector("#group-by")?.addEventListener("change", (event) => {
    state.group = event.target.value;
    state.view = "board";
    syncBar();
    paint();
  });
  root.addEventListener("click", (event) => {
    const only = event.target.closest("[data-only]");
    if (only) {
      state.only = only.dataset.only;
      state.view = state.only ? "list" : "board";
      syncBar();
      return paint();
    }
    const sort = event.target.closest("[data-sort]");
    if (sort) {
      state.desc = state.sort === sort.dataset.sort ? !state.desc : true;
      state.sort = sort.dataset.sort;
      paint();
    }
  });
}

