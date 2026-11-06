// Overview (canvas board Main): what runs, what waits, what needs the user, what it cost,
// and the loop journal, newest first; the running loop and the Auto mode switch (SP11 §5.3).
import { get } from "../api.js";
import { toggle } from "../controls.js";
import { STEPS, clock, elapsed, loopSummary, loopsIn, stepColor, tokens } from "../format.js";
import { html } from "../html.js";
import { icon } from "../icons.js";
import { armed } from "../scope.js";

const WINDOWS = [["today", "Today"], ["7d", "7 days"], ["all", "All"]];
const WINDOW_NAMES = { today: "today", "7d": "last 7 days", all: "all time" };
const journal = { follow: true, frozen: null };

export async function load(app) {
  return app.overview ?? get(`/api/overview?window=${app.window}`);
}

const inScope = (app, item) => !app.project || item.project === app.project;

function subtitle(data, app) {
  const projects = app.project ? 1 : data.projects.length;
  const live = data.sessions.filter((s) => inScope(app, s)).length;
  return `${projects} ${projects === 1 ? "project" : "projects"} · ${live} live CLI ${live === 1 ? "session" : "sessions"} · ${loopSummary(loopsIn(data.loops, app.project))}${data.paused ? " · all loops paused" : ""}`;
}

function tiles(data, app) {
  const sessions = data.sessions.filter((s) => inScope(app, s));
  const gates = data.gates.filter((g) => inScope(app, g));
  const total = data.slots.reduce((sum, slot) => sum + slot.total, 0);
  const providers = new Set(sessions.map((s) => s.provider)).size;
  const queued = data.queue.ready + data.queue.blocked;
  const tile = (label, value, note, alert = false) =>
    html`<div class="tile ${alert ? "alert" : ""}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;
  return html`<div class="tiles">
    ${tile("LIVE SESSIONS", sessions.length, `of ${total} slots · ${providers} ${providers === 1 ? "provider" : "providers"}`)}
    ${tile("IN QUEUE", queued, `${data.queue.parallel} parallel-safe · ${data.queue.serial} serial${data.queue.parked ? ` · ${data.queue.parked} parked` : ""}`)}
    ${tile("AWAITING YOU", gates.length, "loop caps and gates", gates.length > 0)}
    ${tile("DONE TODAY", data.done_today, data.done_today ? `avg ${data.avg_loops_done} loops to done` : "merged or closed since midnight")}
  </div>`;
}

function sessions(data, app) {
  const rows = data.sessions.filter((s) => inScope(app, s));
  return html`<section class="panel sessions">
    <div class="panel-head"><h2>Live agent sessions</h2>${rows.length ? html`<span class="chip"><span class="dot"></span>running</span>` : ""}<a class="end" href="#/board">Open board</a></div>
    ${rows.length
      ? html`<div class="table"><div class="rows">
          <div class="thead"><div class="c-step">STEP</div><div class="c-id">TICKET</div><div class="c-grow">PROJECT</div><div class="c-agent">AGENT · MODEL</div><div class="c-loop">LOOP</div><div class="c-time">ELAPSED</div><div class="c-act"></div></div>
          ${rows.map(
            (s) => html`<div class="trow">
              <div class="c-step"><span class="dot" style="background: ${stepColor(s.step)}"></span><span style="color: ${stepColor(s.step)}; font-weight: 500">${STEPS[s.step]?.label ?? s.step}</span></div>
              <div class="c-id"><a class="mono" href="#/ticket/${s.ticket}" title="${s.title}">${s.ticket}</a></div>
              <div class="c-grow ellipsis muted" title="${s.title}">${s.project}</div>
              <div class="c-agent mono muted ellipsis">${s.provider || "—"} · ${s.model || "default"}</div>
              <div class="c-loop mono ${s.loop >= s.loop_max ? "at-cap" : ""}">${s.loop}/${s.loop_max}</div>
              <div class="c-time mono muted">${elapsed(s.since)}</div>
              <div class="c-act"><button class="icon-btn" type="button" data-stop="${s.ticket}" aria-label="Stop the step on ${s.ticket}" title="Stop the step (click twice)">${icon("stop", { size: 11, width: 1.8 })}</button></div>
            </div>`,
          )}
        </div></div>`
      : html`<div class="empty">No agent is running a step. Start the queue with /kengash:loop in your agent.</div>`}
  </section>`;
}

const GATE_LABELS = {
  loop_cap: ["LOOP CAP", "danger"],
  token_cap: ["TOKEN CAP", "danger"],
  approve_step: ["APPROVE", "danger"],
  stalled: ["STALLED", "warn"],
  failed: ["FAILED", "danger"],
  awaiting_merge: ["READY TO MERGE", "ok"],
};

function gate(item, data) {
  const planStalled = item.kind === "stalled" && ["plan", "review_plan"].includes(item.step);
  const [label, tone] = planStalled ? ["PLAN STALLED", "warn"] : GATE_LABELS[item.kind] ?? [item.kind.toUpperCase(), "warn"];
  const where = STEPS[item.step]?.label ?? item.step;
  const sentence = {
    loop_cap: html`${item.title} reached <span class="mono">${item.loop}/${item.loop_max}</span> loops${where ? ` in ${where}` : ""}.`,
    token_cap: html`${item.title} reached its token ceiling${where ? ` in ${where}` : ""}.`,
    approve_step: html`${item.title} waits for your approval before it goes on.`,
  }[item.kind] ?? html`${item.title}${item.reason ? html`: <span class="muted">${item.reason}</span>` : ""}`;
  const actions = {
    loop_cap: html`<button class="btn small accent" type="button" data-act="approve" data-id="${item.ticket}">Grant +${data.grant} loops</button><button class="btn small ghost" type="button" data-act="park" data-id="${item.ticket}">Park ticket</button>`,
    token_cap: html`<button class="btn small accent" type="button" data-act="approve" data-id="${item.ticket}">Grant more tokens</button><button class="btn small ghost" type="button" data-act="park" data-id="${item.ticket}">Park ticket</button>`,
    approve_step: html`<button class="btn small accent" type="button" data-act="approve" data-id="${item.ticket}">Approve</button><button class="btn small ghost" type="button" data-act="park" data-id="${item.ticket}">Park ticket</button>`,
    stalled: html`<a class="btn small" href="#/ticket/${item.ticket}">${planStalled ? "Read the plan and findings" : "Read the findings"}</a><button class="btn small ghost" type="button" data-act="run" data-id="${item.ticket}">Run again</button>`,
    failed: html`<a class="btn small" href="#/ticket/${item.ticket}">Read what failed</a><button class="btn small ghost" type="button" data-act="run" data-id="${item.ticket}">Run again</button>`,
    awaiting_merge: html`<button class="btn small accent" type="button" data-act="merge" data-id="${item.ticket}">Merge</button><a class="btn small ghost" href="#/ticket/${item.ticket}">Review changes</a>`,
  }[item.kind] ?? html`<a class="btn small" href="#/ticket/${item.ticket}">Open ticket</a>`;
  return html`<div class="gate">
    <div class="gate-head"><span class="badge ${tone}">${label}</span><a class="mono" href="#/ticket/${item.ticket}">${item.ticket}</a></div>
    <p>${sentence}</p>
    <div class="gate-actions">${actions}</div>
  </div>`;
}

function approvals(data, app) {
  const gates = data.gates.filter((g) => inScope(app, g));
  if (!gates.length) {
    return html`<section class="panel"><div class="panel-head"><h2>Needs your approval</h2><span class="end mono faint">0</span></div><div class="empty">Nothing waits on you. Tickets that hit a loop cap, stall, or are ready to merge show up here.</div></section>`;
  }
  return html`<section class="panel approvals">
    <div class="panel-head">${icon("warning", { size: 15, stroke: "var(--danger)", width: 1.6 })}<h2>Needs your approval</h2><span class="end mono danger-text">${gates.length}</span></div>
    ${gates.map((item) => gate(item, data))}
  </section>`;
}

function spend(data, app) {
  const rows = Object.entries(data.spend).sort((a, b) => b[1] - a[1]);
  return html`<section class="panel"><div class="panel-body">
    <h2 class="section-title" style="margin-bottom: 14px">Token spend · ${WINDOW_NAMES[app.window]}</h2>
    <div class="spend">
      ${rows.length ? rows.map(([provider, count]) => html`<div><span class="muted">${provider}</span><span class="end">${tokens(count)}</span></div>`) : html`<div><span class="faint">no step ran ${WINDOW_NAMES[app.window] === "today" ? "today" : "in this window"}</span></div>`}
      <div class="rule"></div>
      <div><span class="faint">avg ticket cost</span><span class="end">${data.avg_ticket_cost ? tokens(data.avg_ticket_cost) : "—"}</span></div>
    </div>
  </div></section>`;
}

// One journal event as the canvas's line: time, kind, ticket, what happened.
function line(event) {
  const step = STEPS[event.step];
  const loop = event.loop ? `loop ${event.loop}${event.loop_max ? `/${event.loop_max}` : ""}` : "";
  const who = event.provider ?? "";
  const back = { review_plan: "plan", review_code: "implement", security: "implement" }[event.step] ?? "an earlier step";
  if (event.type === "step.end") {
    const findings = (event.fingerprints ?? []).length;
    const text = {
      implement: () => (event.files ? html`wrote ${event.files} ${event.files === 1 ? "file" : "files"} <span class="add">+${event.added ?? 0}</span> <span class="del">−${event.removed ?? 0}</span>` : "no file changed"),
      plan: () => "plan written",
      run_tests: () => (event.verdict === "fail" ? "tests failed" : "tests passed"),
    }[event.step]?.() ?? (event.verdict === "fail" ? `${findings || "open"} ${findings === 1 ? "finding" : "findings"} → back to ${back}` : "approved");
    return { kind: step?.kind ?? event.step, color: step?.color, who, text, loop };
  }
  const reason = event.reason ?? event.why ?? "";
  const simple = {
    "ticket.merged": ["done", "var(--ok)", "merged"],
    "ticket.awaiting_merge": ["ready", "var(--ok)", "every step passed → ready to merge"],
    "ticket.needs_approval": ["gate", "var(--danger)", `${reason || "needs you"} → awaiting approval`],
    "ticket.stalled": ["stalled", "var(--warn)", reason || "stalled"],
    "ticket.failed": ["failed", "var(--danger)", reason || "failed"],
    "ticket.approved": ["granted", "var(--ok)", event.loops ? `granted ${event.loops} more loops` : "approved"],
    "ticket.moved": ["moved", "var(--faint)", `${event.from ?? ""} → ${event.to ?? ""}${reason ? ` · ${reason}` : ""}`],
    "ticket.recirculated": ["back", "var(--step-review)", reason || "sent back a step"],
    "ticket.stopped": ["stopped", "var(--faint)", "stopped"],
    "ticket.claimed": ["spawn", "var(--faint)", "claimed by a worker"],
    "worker.started": ["spawn", "var(--faint)", "worker started"],
    "worker.exited": ["exit", "var(--faint)", reason || "worker exited"],
    "session.created": ["spawn", "var(--faint)", `new session ${event.session ?? ""}`],
    "session.resumed": ["spawn", "var(--faint)", `reused session ${event.session ?? ""} · 0 cold start`],
    "memory.write": ["memory", "var(--faint)", `${event.file}: ${String(event.line ?? "").replace(/^- /, "")}`],
    "memory.compacted": ["memory", "var(--faint)", `compacted ${event.file} ${event.before} → ${event.after} lines`],
    "settings.changed": ["settings", "var(--faint)", `${event.project ?? "defaults"}: ${(event.keys ?? []).join(", ")}`],
  }[event.type];
  if (simple) return { kind: simple[0], color: simple[1], who: event.by && event.type.startsWith("memory") ? event.by : who, text: simple[2], loop: "" };
  const [group, verb] = event.type.split(".");
  return { kind: group === "plan" ? "plan" : verb ?? group, color: group === "plan" ? "var(--step-plan)" : "var(--faint)", who, text: group === "plan" ? `plan ${event.plan ?? ""} ${verb}` : reason || verb, loop: "" };
}

function journalPanel(data, app) {
  const events = (journal.follow || !journal.frozen ? data.tail : journal.frozen).filter((e) => inScope(app, e)).slice().reverse();
  if (journal.follow) journal.frozen = data.tail;
  return html`<section class="panel">
    <div class="panel-head"><h2>Loop journal</h2><span class="faint" style="font-size: 12px">every step and status change, newest first</span><button class="btn small quiet end" type="button" data-follow aria-pressed="${journal.follow ? "true" : "false"}">${journal.follow ? "Following tail" : "Follow tail"}</button></div>
    <div class="journal-lines">${events.length
      ? events.map((event) => {
          const item = line(event);
          return html`<div class="jl"><span class="faint">${clock(event.ts)}</span><span class="jl-kind" style="color: ${item.color ?? "var(--muted)"}">${item.kind}</span>${event.ticket ? html`<a class="jl-id" href="#/ticket/${event.ticket}">${event.ticket}</a>` : html`<span class="jl-id faint">${event.plan ?? ""}</span>`}<span class="jl-who">${item.who}</span><span class="jl-text" title="${typeof item.text === "string" ? item.text : ""}">${item.text}${item.loop ? html`<span class="jl-loop">${item.loop}</span>` : ""}</span></div>`;
        })
      : html`<div class="empty" style="padding: 0">Nothing happened yet. Steps, gates and memory writes land here as they happen.</div>`}</div>
  </section>`;
}

export function view(data, app) {
  return html`<div class="page">
    ${data.links_broken ? html`<div class="banner"><span class="badge danger">links</span>${data.links_broken} ${data.links_broken === 1 ? "project's folder link needs" : "projects' folder links need"} a fix; until then the repo does not show the store.<a href="#/memory">Open link health</a></div>` : ""}
    <div class="page-head">
      <div><h1>Overview</h1><p>${subtitle(data, app)}</p></div>
      <div class="head-row">
        <div class="segmented" role="group" aria-label="Window">${WINDOWS.map(([key, label]) => html`<button type="button" data-window="${key}" aria-pressed="${app.window === key ? "true" : "false"}">${label}</button>`)}</div>
        ${toggle({ id: "ov-auto", checked: app.project ? Boolean(data.auto[app.project]) : data.auto_default, label: "Auto mode", hint: app.project ? `start the loop once ${app.project} gets tickets` : "every project without its own setting" })}
        <button class="btn danger" type="button" data-pause="${data.paused ? "resume" : "pause"}">${data.paused ? "Resume all loops" : "Pause all loops"}</button>
      </div>
    </div>
    ${tiles(data, app)}
    <div class="overview-row">
      ${sessions(data, app)}
      <div class="overview-side">${approvals(data, app)}${spend(data, app)}</div>
    </div>
    ${journalPanel(data, app)}
  </div>`;
}

export function foot(data) {
  return html`<div class="foot-card"><div class="nav-title">CLI POOL</div><div class="foot-rows">${data.slots.length
    ? data.slots.map((slot) => html`<div><span class="dot" style="background: ${slot.total === 0 ? "#4a525c" : slot.used ? "var(--accent)" : "var(--ok)"}"></span>${slot.provider}<span class="end ${slot.total === 0 ? "off" : ""}">${slot.total === 0 ? "off" : `${slot.used}/${slot.total}`}</span></div>`)
    : html`<div class="faint">no store yet</div>`}</div></div>`;
}

// The `loop_start` change the Overview switch saves: a project whose new value matches the
// defaults drops its own key (null), so it keeps following the defaults.
export function autoChange(project, auto, autoDefault) {
  return project && auto === autoDefault ? null : auto ? "auto" : "ask";
}

export function bind(root, app) {
  root.addEventListener("change", async (event) => {
    if (event.target.id !== "ov-auto") return;
    const auto = event.target.checked;
    const scope = encodeURIComponent(app.project);
    const loopStart = autoChange(app.project, auto, app.overview?.auto_default ?? false);
    const done = await app.post(`/api/settings?project=${scope}`, { changes: { loop_start: loopStart } });
    if (done) app.toast(auto ? "Auto mode on: the loop starts once tickets are added." : "Auto mode off: your agent asks before it starts the loop.");
    else event.target.checked = !auto;
  });
  root.addEventListener("click", async (event) => {
    const win = event.target.closest("[data-window]");
    if (win) {
      app.window = win.dataset.window;
      return app.refresh();
    }
    if (event.target.closest("[data-follow]")) {
      journal.follow = !journal.follow;
      return app.refresh();
    }
    const pause = event.target.closest("[data-pause]");
    if (pause) {
      const done = await app.post(`/api/${pause.dataset.pause}`, {});
      if (done) app.toast(pause.dataset.pause === "pause" ? "Paused: running steps finish, nothing new starts." : "Resumed: the queue runs again.");
      return;
    }
    const stop = event.target.closest("[data-stop]");
    if (stop) {
      if (stop.dataset.armed !== "1") {
        stop.dataset.armed = "1";
        stop.classList.add("armed");
        setTimeout(() => stop.isConnected && (stop.dataset.armed = "", stop.classList.remove("armed")), 4000);
        return;
      }
      const done = await app.post(`/api/tickets/${stop.dataset.stop}/stop`, {});
      if (done) app.toast(`${stop.dataset.stop}: step stopped.`);
      return;
    }
    const act = event.target.closest("button[data-act]");
    if (!act) return;
    if (act.dataset.act === "park" && !armed(act, "Confirm park")) return;
    const body = act.dataset.act === "park" ? { why: "parked from the overview" } : {};
    act.disabled = true;
    const done = await app.post(`/api/tickets/${act.dataset.id}/${act.dataset.act}`, body);
    const said = { approve: "approved; its loop restarts", park: "parked", run: "started", merge: "merged" };
    if (done) app.toast(`${act.dataset.id} ${said[act.dataset.act]}.`);
    else act.disabled = false;
  });
}
