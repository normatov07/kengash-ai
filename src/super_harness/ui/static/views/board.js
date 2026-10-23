// Task board: every ticket in its status column; the top bar's project and search narrow it.
import { get } from "../api.js";
import { html } from "../html.js";

const COLOURS = {
  in_queue: "var(--faint)",
  plan: "var(--info)",
  review_plan: "var(--info)",
  implement: "var(--accent)",
  review_code: "var(--warn)",
  security: "var(--danger)",
  run_tests: "var(--warn)",
  docs: "var(--info)",
  waiting: "var(--muted)",
  needs_you: "var(--danger)",
  done: "var(--ok)",
};
const STATE = {
  ready: "ready",
  blocked: "blocked",
  parked: "parked",
  waiting_slot: "waiting for a slot",
  waiting_quota: "waiting for quota",
  paused: "paused",
  needs_approval: "needs approval",
  stalled: "stalled",
  failed: "failed",
  awaiting_merge: "ready to merge",
  merged: "merged",
  branch_ready: "branch ready",
  closed: "closed",
};

export async function load(app) {
  return get(`/api/board${app.project ? `?project=${encodeURIComponent(app.project)}` : ""}`);
}

function matches(card, query) {
  if (!query) return true;
  const text = `${card.id} ${card.title} ${card.project}`.toLowerCase();
  return query.toLowerCase().split(/\s+/).every((word) => text.includes(word));
}

function card(item, column) {
  const sub = item.status.split("/")[1];
  const state = STATE[sub];
  const running = !state && column !== "done";
  return html`<a class="card imp-${item.importance}" href="#/ticket/${item.id}">
    <div class="card-top"><span class="imp">${item.importance}</span><span class="tag">${item.parallel ? "parallel" : "serial"}</span><span class="end">${item.loop}/${item.loop_max}</span></div>
    <div class="card-title">${item.title}</div>
    <div class="card-meta">
      ${running && item.provider ? html`<span class="chip"><span class="dot"></span>${item.provider}</span>` : ""}
      ${state ? html`<span class="chip plain">${state}</span>` : ""}
      ${item.findings ? html`<span style="color: var(--warn)">${item.findings} ${item.findings === 1 ? "finding" : "findings"}</span>` : ""}
      ${item.added || item.removed ? html`<span><span class="add">+${item.added}</span> <span class="del">−${item.removed}</span></span>` : ""}
    </div>
    <div class="card-foot"><span>${item.id}</span><span>${item.project}</span></div>
  </a>`;
}

export function view(data, app) {
  const columns = data.columns.map((column) => ({ ...column, cards: column.cards.filter((c) => matches(c, app.query)) }));
  const count = (key) => columns.find((c) => c.key === key)?.cards.length ?? 0;
  const running = columns.filter((c) => !["in_queue", "waiting", "needs_you", "done"].includes(c.key)).reduce((sum, c) => sum + c.cards.length, 0);
  const shown = columns.filter((c) => c.cards.length || ["in_queue", "implement", "review_code", "needs_you", "done"].includes(c.key));
  return html`<div class="page wide">
    <div class="page-head"><div><h1>Task board</h1><p>${running} running · ${count("needs_you")} need you · ${count("in_queue")} queued · ${count("done")} done${app.query ? ` · matching “${app.query}”` : ""}</p></div></div>
    <div class="columns">${shown.map(
      (column) => html`<section class="column" style="--col: ${COLOURS[column.key]}">
        <div class="column-bar"></div>
        <div class="column-head"><h2>${column.title}</h2><span class="count">${column.cards.length}</span></div>
        <div class="cards">${column.cards.length ? column.cards.map((c) => card(c, column.key)) : html`<div class="faint" style="font-size: 12px; padding: 6px 2px">empty</div>`}</div>
      </section>`,
    )}</div>
  </div>`;
}
