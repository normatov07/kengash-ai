// Overview: live sessions, the queue, what needs the user, token spend, the journal tail.
import { get } from "../api.js";
import { clock, elapsed, stepLabel, tokens } from "../format.js";
import { html } from "../html.js";

const WINDOWS = [["today", "Today"], ["7d", "7 days"], ["all", "All"]];
const GATES = {
  needs_approval: ["Needs approval", "danger"],
  stalled: ["Stalled", "warn"],
  failed: ["Failed", "danger"],
  awaiting_merge: ["Ready to merge", "ok"],
};

export async function load(app) {
  return app.overview ?? get(`/api/overview?window=${app.window}`);
}

function inScope(app, item) {
  return !app.project || item.project === app.project;
}

function tiles(data, app) {
  const sessions = data.sessions.filter((s) => inScope(app, s));
  const gates = data.gates.filter((g) => inScope(app, g));
  const total = data.slots.reduce((sum, slot) => sum + slot.total, 0);
  const providers = new Set(sessions.map((s) => s.provider)).size;
  const queued = data.queue.ready + data.queue.blocked;
  return html`<div class="tiles">
    <div class="tile"><div class="label">LIVE SESSIONS</div><div class="value">${sessions.length}</div><div class="note">of ${total} slots · ${providers} ${providers === 1 ? "provider" : "providers"}</div></div>
    <div class="tile"><div class="label">IN QUEUE</div><div class="value">${queued}</div><div class="note">${data.queue.parallel} parallel-safe · ${data.queue.serial} serial${data.queue.parked ? ` · ${data.queue.parked} parked` : ""}</div></div>
    <div class="tile ${gates.length ? "alert" : ""}"><div class="label">AWAITING YOU</div><div class="value">${gates.length}</div><div class="note">loop caps and gates</div></div>
    <div class="tile"><div class="label">DONE TODAY</div><div class="value">${data.done_today}</div><div class="note">merged or closed since midnight</div></div>
  </div>`;
}

function sessions(data, app) {
  const rows = data.sessions.filter((s) => inScope(app, s));
  return html`<section class="panel grow">
    <div class="panel-head"><h2>Live agent sessions</h2>${rows.length ? html`<span class="chip"><span class="dot"></span>running</span>` : ""}<a class="end" href="#/board">Open board</a></div>
    ${rows.length
      ? html`<div class="table"><div class="rows">
          <div class="thead"><div class="cell-step">STEP</div><div class="cell-id">TICKET</div><div class="cell-grow">PROJECT</div><div class="cell-agent">AGENT · MODEL</div><div class="cell-num">LOOP</div><div class="cell-num">ELAPSED</div></div>
          ${rows.map(
            (s) => html`<div class="trow">
              <div class="cell-step"><span class="dot busy"></span><span style="color: var(--accent); font-weight: 500">${stepLabel(s.status)}</span></div>
              <div class="cell-id"><a href="#/ticket/${s.ticket}">${s.ticket}</a></div>
              <div class="cell-grow" title="${s.title}">${s.project}</div>
              <div class="cell-agent">${s.provider || "—"} · ${s.model || "default"}</div>
              <div class="cell-num">${s.loop}/${s.loop_max}</div>
              <div class="cell-num">${elapsed(s.since)}</div>
            </div>`,
          )}
        </div></div>`
      : html`<div class="empty">No agent is running a step. Start tickets with /to-loop in your agent.</div>`}
  </section>`;
}

function gate(item) {
  const sub = item.status.split("/")[1];
  const [label, tone] = GATES[sub] ?? [sub, "warn"];
  const actions = {
    needs_approval: html`<button class="btn primary small" type="button" data-act="approve" data-id="${item.ticket}">Grant +2 loops</button><button class="btn ghost small" type="button" data-act="park" data-id="${item.ticket}">Park ticket</button>`,
    awaiting_merge: html`<button class="btn primary small" type="button" data-act="merge" data-id="${item.ticket}">Merge</button>`,
    failed: html`<button class="btn small" type="button" data-act="run" data-id="${item.ticket}">Run again</button>`,
    stalled: html`<a class="btn small" href="#/ticket/${item.ticket}">Read the findings</a><button class="btn ghost small" type="button" data-act="run" data-id="${item.ticket}">Run again</button>`,
  }[sub];
  return html`<div class="gate">
    <div class="gate-head"><span class="badge ${tone}">${label}</span><a href="#/ticket/${item.ticket}">${item.ticket}</a><span class="faint mono" style="margin-left: auto; font-size: 11px">${item.loop}/${item.loop_max}</span></div>
    <p>${item.title}${item.reason ? html`<span class="muted"> · ${item.reason}</span>` : ""}</p>
    <div class="actions">${actions}</div>
  </div>`;
}

function side(data, app) {
  const gates = data.gates.filter((g) => inScope(app, g));
  const spend = Object.entries(data.spend).sort((a, b) => b[1] - a[1]);
  const total = spend.reduce((sum, [, count]) => sum + count, 0);
  const label = WINDOWS.find(([key]) => key === app.window)[1].toLowerCase();
  return html`<section class="side">
    <div class="panel ${gates.length ? "alert" : ""}">
      <div class="panel-head"><h2>Needs your approval</h2><span class="end mono" style="color: ${gates.length ? "var(--danger)" : "var(--faint)"}">${gates.length}</span></div>
      ${gates.length ? gates.map(gate) : html`<div class="empty">Nothing waits for you.</div>`}
    </div>
    <div class="panel"><div class="panel-body">
      <h2 style="margin: 0 0 14px; font-size: 14px">Token spend · ${label}</h2>
      <div class="spend">
        ${spend.length ? spend.map(([provider, count]) => html`<div><span class="muted">${provider}</span><span>${tokens(count)}</span></div>`) : html`<div><span class="faint">no steps ran</span></div>`}
        <hr><div><span class="faint">total</span><span>${tokens(total)}</span></div>
      </div>
    </div></div>
    ${data.conductors.length
      ? html`<div class="panel"><div class="panel-body"><h2 style="margin: 0 0 12px; font-size: 14px">Live conductors</h2><div class="spend">${data.conductors.map(
          (c) => html`<div><span class="muted">${c.agent}</span><span class="faint">${c.project ?? "all projects"} · ${clock(c.time)}</span></div>`,
        )}</div></div></div>`
      : ""}
  </section>`;
}

function describe(event) {
  const kind = event.type.split(".")[1] ?? event.type;
  if (event.type === "step.end") {
    const diff = event.added || event.removed ? html` <span class="add">+${event.added ?? 0}</span> <span class="del">−${event.removed ?? 0}</span>` : "";
    return [event.step, html`${event.provider} ${event.verdict ?? ""}${diff} · loop ${event.loop}`];
  }
  if (event.type === "step.start") return [event.step, html`${event.provider} started · loop ${event.loop}`];
  const text = event.reason || event.why || event.title || event.line || event.status || event.to || "";
  return [kind, html`${event.by ? `${event.by} · ` : ""}${text}`];
}

function journal(data, app) {
  const rows = data.tail.filter((e) => !app.project || e.project === app.project).slice().reverse();
  return html`<section class="panel">
    <div class="panel-head"><h2>Loop journal</h2><span class="faint" style="font-size: 12px">every step and status change, newest first</span></div>
    ${rows.length
      ? html`<div class="journal">${rows.map((event) => {
          const [kind, text] = describe(event);
          return html`<div class="journal-row"><span class="time">${clock(event.ts)}</span><span class="kind">${kind}</span><span class="id">${event.ticket ? html`<a href="#/ticket/${event.ticket}">${event.ticket}</a>` : event.plan ?? ""}</span><span class="text">${text}</span></div>`;
        })}</div>`
      : html`<div class="empty">The journal is empty.</div>`}
  </section>`;
}

export function view(data, app) {
  const conductors = data.conductors.length;
  const live = data.sessions.filter((s) => inScope(app, s)).length;
  return html`<div class="page">
    <div class="page-head">
      <div><h1>Overview</h1><p>${data.projects.length} ${data.projects.length === 1 ? "project" : "projects"} · ${live} live CLI ${live === 1 ? "session" : "sessions"} · ${conductors ? `${conductors} live ${conductors === 1 ? "conductor" : "conductors"}` : "no live conductor"}${data.paused ? " · paused" : ""}</p></div>
      <div class="end">
        <div class="segmented" role="group" aria-label="Window">${WINDOWS.map(([key, label]) => html`<button type="button" data-window="${key}" aria-pressed="${app.window === key}">${label}</button>`)}</div>
        ${data.paused
          ? html`<button class="btn" type="button" data-act="resume">Resume all loops</button>`
          : html`<button class="btn danger" type="button" data-act="pause">Pause all loops</button>`}
      </div>
    </div>
    ${data.links_broken ? html`<div class="banner"><span class="badge danger">links</span>${data.links_broken} ${data.links_broken === 1 ? "project's folder link needs" : "projects' folder links need"} a fix; until then the repo does not show the store.<a href="#/memory">Open link health</a></div>` : ""}
    ${tiles(data, app)}
    <div class="split">${sessions(data, app)}${side(data, app)}</div>
    ${journal(data, app)}
  </div>`;
}

export function bind(root, app) {
  root.querySelectorAll("[data-window]").forEach((button) =>
    button.addEventListener("click", () => {
      app.window = button.dataset.window;
      app.refresh();
    }),
  );
  root.querySelectorAll("[data-act]").forEach((button) =>
    button.addEventListener("click", async () => {
      const { act, id } = button.dataset;
      button.disabled = true;
      if (act === "pause" || act === "resume") await app.post(`/api/${act}`);
      else if (act === "approve") await app.post(`/api/tickets/${id}/approve`, { loops: 2 });
      else if (act === "park") await app.post(`/api/tickets/${id}/park`, { why: "parked by the user from the UI" });
      else await app.post(`/api/tickets/${id}/${act}`);
      button.disabled = false;
    }),
  );
}
