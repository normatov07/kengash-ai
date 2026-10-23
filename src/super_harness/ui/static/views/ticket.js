// Ticket detail: the ticket's header and actions, what it changed, its findings, prompt,
// acceptance and dependencies, its step timeline and file, and the agent chain beside them.
import { get } from "../api.js";
import { clock, elapsed, stepLabel, tokens } from "../format.js";
import { html } from "../html.js";
import { armed } from "../scope.js";

const state = { id: "", tab: "overview", diff: null, plan: null };

export async function load(app, id) {
  if (state.id !== id) Object.assign(state, { id, tab: "overview", diff: null, plan: null });
  return get(`/api/tickets/${encodeURIComponent(id)}`);
}

const TABS = [["overview", "Overview"], ["changes", "Changes"], ["timeline", "Timeline"], ["file", "Ticket file"]];

function bullets(text) {
  const lines = (text || "").split("\n").map((line) => line.trim()).filter(Boolean);
  return lines.map((line) => line.replace(/^[-*]\s*(\[[ xX]\]\s*)?/, ""));
}

function changesTable(data) {
  if (!data.changes.length) return html`<div class="empty">No commits under this ticket yet.</div>`;
  const added = data.changes.reduce((sum, c) => sum + (c.added ?? 0), 0);
  const removed = data.changes.reduce((sum, c) => sum + (c.removed ?? 0), 0);
  return html`<div class="table"><div class="rows">
    <div class="thead"><div class="cell-grow">FILE</div><div class="cell-diff">DIFF</div><div class="cell-agent">WRITTEN BY</div><div class="cell-num">LOOP</div></div>
    ${data.changes.map(
      (c) => html`<div class="trow"><div class="cell-grow mono">${c.path}</div><div class="cell-diff mono"><span class="add">+${c.added ?? "?"}</span> <span class="del">−${c.removed ?? "?"}</span></div><div class="cell-agent mono faint">${c.model}</div><div class="cell-num mono">${c.loop}</div></div>`,
    )}
    <div class="trow"><div class="cell-grow faint">${data.changes.length} ${data.changes.length === 1 ? "file" : "files"}</div><div class="cell-diff mono"><span class="add">+${added}</span> <span class="del">−${removed}</span></div><div class="cell-agent"></div><div class="cell-num"><button class="btn small" type="button" data-diff>${state.diff ? "Hide diff" : "Open full diff"}</button></div></div>
  </div></div>
  ${state.diff ? html`<pre class="diff mono">${state.diff.split("\n").map((line) => html`<span class="${line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : line.startsWith("@@") ? "hunk" : ""}">${line || " "}</span>`)}</pre>` : ""}`;
}

function links(items, empty) {
  if (!items.length) return html`<span class="faint">${empty}</span>`;
  return items.map((item) => html`<div class="dep"><a class="mono" href="#/ticket/${item.id}">${item.id}</a><span>${item.title}</span><span class="faint mono">${item.status}</span></div>`);
}

function overviewTab(data) {
  const findings = bullets(data.sections.Findings);
  const acceptance = bullets(data.sections.Acceptance);
  const parallel = data.meta.touches.length > 0;
  return html`
    <section class="panel"><div class="panel-head"><h2>Changes made under this ticket</h2></div>${changesTable(data)}</section>
    <section class="panel ${findings.length ? "alert" : ""}"><div class="panel-head"><h2>Open findings</h2><span class="end mono faint">${findings.length}</span></div>
      <div class="panel-body">${findings.length ? html`<ul class="list">${findings.map((line) => html`<li>${line}</li>`)}</ul>` : html`<span class="faint">No open findings.</span>`}</div></section>
    <section class="panel"><div class="panel-head"><h2>Original prompt</h2>${data.plan.found ? html`<button class="btn ghost small end" type="button" data-plan>${state.plan ? "Hide the plan" : `Read plan ${data.plan.id}`}</button>` : ""}</div>
      <div class="panel-body">${data.plan.found ? html`<p class="prompt">${data.plan.prompt || "(the plan has no Prompt section)"}</p><div class="faint" style="font-size: 12px">from plan ${data.plan.id} · ${data.plan.title}${data.siblings.length ? ` · ${data.siblings.length} sibling ${data.siblings.length === 1 ? "ticket" : "tickets"}` : ""}</div>` : html`<span class="faint">Plan ${data.plan.id} is not in the store.</span>`}
      ${data.sections.Scope ? html`<h3 class="sub">Scope</h3><p class="prompt">${data.sections.Scope}</p>` : ""}
      ${state.plan ? Object.entries(state.plan.sections).filter(([name]) => name !== "Prompt").map(([name, text]) => html`<h3 class="sub">plan · ${name}</h3><p class="prompt">${text}</p>`) : ""}</div></section>
    <section class="panel"><div class="panel-head"><h2>Acceptance criteria</h2></div><div class="panel-body">${acceptance.length ? html`<ul class="list checks-list">${acceptance.map((line) => html`<li>${line}</li>`)}</ul>` : html`<span class="faint">None written.</span>`}</div></section>
    <section class="panel"><div class="panel-head"><h2>Dependencies</h2></div><div class="panel-body deps">
      <div><span class="badge info">waits on</span>${links(data.depends_on, "nothing")}</div>
      <div><span class="badge warn">blocks</span>${links(data.blocks, "nothing")}</div>
      <div><span class="badge ${parallel ? "ok" : "danger"}">${parallel ? "parallel" : "serial"}</span><span class="faint">${parallel ? `touches ${data.meta.touches.join(", ")}; runs beside tickets that touch other paths` : "touches nothing named, so it claims the whole repo and runs alone"}</span></div>
      ${data.siblings.length ? html`<div><span class="badge">siblings</span>${links(data.siblings, "")}</div>` : ""}
    </div></section>`;
}

function timelineTab(data) {
  if (!data.timeline.length) return html`<section class="panel"><div class="empty">No step has run yet.</div></section>`;
  const steps = data.timeline.filter((row) => row.kind === "step.end");
  const seconds = steps.reduce((sum, row) => sum + (row.duration_s ?? 0), 0);
  return html`<section class="panel"><div class="panel-head"><h2>Step timeline</h2><span class="end faint">${data.timeline.length} events · ${steps.length} steps · ${Math.round(seconds / 60)}m of session time</span></div>
    <div class="table"><div class="rows">${data.timeline.map((row) =>
      row.kind === "step.end"
        ? html`<div class="trow"><div class="cell-time mono faint">${clock(row.ts)}</div><div class="cell-step">${row.step.replaceAll("_", " ")}</div><div class="cell-agent mono faint">${row.provider}${row.model ? ` · ${row.model}` : ""}</div><div class="cell-grow">${row.verdict}${row.loop ? html` <span class="faint">loop ${row.loop}</span>` : ""}</div><div class="cell-num mono">${tokens(row.tokens)}</div><div class="cell-num mono faint">${row.duration_s != null ? `${Math.floor(row.duration_s / 60)}m ${String(Math.round(row.duration_s % 60)).padStart(2, "0")}s` : ""}</div></div>`
        : html`<div class="trow"><div class="cell-time mono faint">${clock(row.ts)}</div><div class="cell-step"><span class="badge">${row.kind.replace("ticket.", "").replaceAll("_", " ")}</span></div><div class="cell-grow faint">${row.note}</div></div>`,
    )}</div></div></section>`;
}

function fileTab(data) {
  return html`<section class="panel"><div class="panel-head"><h2>Ticket file</h2><span class="end faint" style="font-size: 12px">one file, two paths: the repo sees the store through its folder link</span></div>
    <div class="panel-body"><div class="paths mono"><div><span class="faint">store</span> ${data.store_path}</div><div><span class="faint">repo</span> ${data.repo_path}</div></div>
    <pre class="file-view mono">${data.file.split("\n").map((line) => html`<span class="line">${line || " "}</span>`)}</pre></div></section>`;
}

function gateActions(meta, gate) {
  const sub = meta.status.split("/")[1];
  const out = [];
  if (sub === "needs_approval") out.push(html`<button class="btn primary small" type="button" data-act="approve">Grant +${gate} loops</button>`);
  if (sub === "awaiting_merge") out.push(html`<button class="btn primary small" type="button" data-act="merge">Merge</button>`);
  if (["stalled", "failed"].includes(sub) || meta.status === "in_queue/ready") out.push(html`<button class="btn small" type="button" data-act="run">${meta.status === "in_queue/ready" ? "Run" : "Run again"}</button>`);
  return out;
}

function chainView(data) {
  if (!data.chain.length) return html`<span class="faint">No workflow ${data.meta.workflow} in the settings.</span>`;
  return html`<ol class="chain">${data.chain.map(
    (step) => html`<li class="chain-${step.state.replace(" ", "-")}"><span class="mono">${step.step.replaceAll("_", " ")}</span><span class="faint mono">${step.role ?? "you"}${step.runs ? ` ×${step.runs}` : ""}</span><span class="chain-state">${step.state}</span></li>`,
  )}</ol>`;
}

export function view(data, app) {
  const meta = data.meta;
  const done = meta.status.startsWith("done/");
  const running = meta.status.startsWith("in_process/") && !["needs_approval", "stalled", "failed", "awaiting_merge"].includes(meta.status.split("/")[1]);
  const gate = app.overview?.gates?.find((item) => item.ticket === meta.id);
  const folder = data.store_path.split("/tasks/")[1]?.split("/")[0] ?? "";
  const counts = { changes: data.changes.length, timeline: data.timeline.length };
  const body = { overview: overviewTab, changes: (d) => html`<section class="panel"><div class="panel-head"><h2>Changes</h2></div>${changesTable(d)}</section>`, timeline: timelineTab, file: fileTab }[state.tab](data);
  return html`<div class="page">
    <div class="crumbs mono"><a href="#/board">Task board</a> / ${meta.id} <span class="faint">projects/${data.project}/tasks/${folder}/</span></div>
    <div class="page-head ticket-head">
      <div>
        <div class="ticket-tags"><span class="imp imp-${meta.importance}">${meta.importance}</span><span class="chip">${stepLabel(meta.status)}</span><span class="faint mono" style="font-size: 11px">${meta.uuid}</span></div>
        <h1>${meta.title}</h1>
        <p class="mono faint" style="font-size: 12px">${data.project}${meta.touches.length ? ` · ${meta.touches.join(", ")}` : ""}${meta.branch ? ` · ${meta.branch}` : ""} · opened ${clock(meta.created)} · ${elapsed(meta.created)} ago</p>
      </div>
      <div class="head-actions"><span class="mono ${meta.loop >= meta.loop_max ? "danger-text" : "faint"}">loop ${meta.loop}/${meta.loop_max}${gate?.reason ? ` · ${gate.reason}` : ""}</span>${gateActions(meta, data.grant)}</div>
    </div>
    <div class="split">
      <div class="grow stack">
        <div class="segmented tabs" role="tablist">${TABS.map(([key, label]) => html`<button type="button" role="tab" data-tab="${key}" aria-pressed="${state.tab === key ? "true" : "false"}">${label}${counts[key] ? html` <span class="faint">${counts[key]}</span>` : ""}</button>`)}</div>
        ${body}
      </div>
      <div class="side">
        <section class="panel"><div class="panel-head"><h2>Written to shared memory</h2></div><div class="panel-body">${data.memory_writes.length ? data.memory_writes.map((w) => html`<div class="memo"><span class="mono">${w.file}</span><span>${w.line}</span><span class="faint mono">${clock(w.ts)}</span></div>`) : html`<span class="faint">Nothing written for this ticket.</span>`}</div></section>
        <section class="panel"><div class="panel-head"><h2>Agent chain</h2><span class="end faint mono">${meta.workflow}</span></div><div class="panel-body">${chainView(data)}</div></section>
        <section class="panel"><div class="panel-head"><h2>Metadata</h2></div><div class="panel-body meta-list">
          <div><span class="faint">workflow</span><span class="mono">${meta.workflow}</span></div>
          <div><span class="faint">gate</span><span class="mono">${meta.gate}</span></div>
          <div><span class="faint">tokens</span><span class="mono">${tokens(meta.tokens)}${meta.tokens_max ? ` / ${tokens(meta.tokens_max)}` : ""}</span></div>
          <div><span class="faint">sessions</span><span class="mono">${Object.keys(meta.sessions).length ? Object.entries(meta.sessions).map(([role, s]) => `${role}: ${s.provider}/${s.model}`).join(", ") : "none yet"}</span></div>
          <div><span class="faint">updated</span><span class="mono">${clock(meta.updated)}</span></div>
          ${meta.tags.length ? html`<div><span class="faint">tags</span><span>${meta.tags.map((tag) => html`<span class="tag">${tag}</span>`)}</span></div>` : ""}
        </div></section>
        <section class="panel"><div class="panel-body stack-small">
          ${data.attach ? html`<button class="btn small" type="button" data-copy="${data.attach}" data-note="Copied; run it in a terminal to open the session.">Attach to the CLI session</button>` : html`<span class="faint" style="font-size: 12px">No CLI session to attach to yet.</span>`}
          ${running ? html`<button class="btn small" type="button" data-act="stop">Stop the running step</button>` : ""}
          ${done ? "" : html`<form class="why-form" data-why-form><label class="sr-only" for="why">Why</label><input id="why" class="inline-input" name="why" placeholder="why (needed to park)">
            <div class="head-actions" style="justify-content: flex-start"><button class="btn small" type="submit" data-act="park">Park</button><button class="btn small" type="button" data-act="move" data-to="in_queue">Send back to in_queue</button><button class="btn small danger" type="button" data-act="move" data-to="done" data-armed-label="Confirm: move to done">Force move to done</button></div></form>`}
        </div></section>
      </div>
    </div>
  </div>`;
}

export function bind(root, app, data) {
  const id = data.meta.id;
  const why = () => root.querySelector("#why")?.value.trim() ?? "";
  root.addEventListener("click", async (event) => {
    const tab = event.target.closest("[data-tab]");
    if (tab) {
      state.tab = tab.dataset.tab;
      return app.refresh();
    }
    if (event.target.closest("[data-plan]")) {
      state.plan = state.plan ? null : (await get(`/api/plans/${data.plan.id}`).catch((error) => app.toast(error.message, true))) ?? null;
      return app.refresh();
    }
    if (event.target.closest("[data-diff]")) {
      state.diff = state.diff ? null : (await get(`/api/tickets/${id}/diff`).catch((error) => app.toast(error.message, true)))?.diff ?? null;
      return app.refresh();
    }
    const act = event.target.closest("[data-act]");
    if (!act || act.type === "submit") return;
    if (act.dataset.armedLabel && !armed(act, act.dataset.armedLabel)) return;
    const body = act.dataset.act === "move" ? { to: act.dataset.to, why: why() || `moved from the UI` } : {};
    act.disabled = true;
    const result = await app.post(`/api/tickets/${id}/${act.dataset.act}`, body);
    const said = { approve: "approved; its loop restarts", run: "started", stop: "stopped", merge: "merged", move: `moved to ${act.dataset.to}` };
    if (result) app.toast(`${id} ${said[act.dataset.act] ?? act.dataset.act}.`);
    else act.disabled = false;
  });
  root.querySelector("[data-why-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!why()) return app.toast("Say why to park it.", true);
    const result = await app.post(`/api/tickets/${id}/park`, { why: why() });
    if (result) app.toast(`${id} parked.`);
  });
}
