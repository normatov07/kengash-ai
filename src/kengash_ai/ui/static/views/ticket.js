// Ticket detail (canvas board Ticket): a sheet over the dimmed page with the ticket's header
// and gate action, tabs Live (while a worker runs, SP12) · Overview · Changes · Timeline ·
// Memory file, and a rail with the agent chain, metadata and actions. Closes back to where it
// was opened (× or Escape).
import { get } from "../api.js";
import { STEPS, activityRow, clock, elapsed, shortTime, span, tick, tokens } from "../format.js";
import { html, raw } from "../html.js";
import { icon } from "../icons.js";
import { armed } from "../scope.js";

const state = { id: "", tab: "overview", diff: null, file: "", plan: null, park: false, paths: false };
const IMPORTANCE = { critical: ["#3A2024", "#EF7A72"], standard: ["#2A2320", "#D8B24C"], simple: ["#1B2733", "#68A4E0"] };
const SEVERITY = { high: ["HIGH", "red"], critical: ["CRIT", "red"], medium: ["MED", "warn"], med: ["MED", "warn"], low: ["LOW", "info"] };
const GATED = ["needs_approval", "stalled", "failed", "awaiting_merge"];

// The Live tab's stream; closed on every render and when the user leaves the ticket.
// The Live tab's rows and stream outlive a render: the sheet re-renders on every journal
// event, and the stream would otherwise replay its history and lose the scroll each time.
const live = { id: "", rows: [], source: null, done: false, follow: true, timer: null };
function closeLive() {
  live.source?.close();
  live.source = null;
  clearInterval(live.timer); // the header's elapsed time stops counting with the stream
  live.timer = null;
}
export function liveAppend(id, item) {
  if (live.id !== id) Object.assign(live, { id, rows: [], done: false, follow: true });
  live.rows.push(activityRow(item).text);
  return live.rows.length;
}
export function liveRows(id) {
  return live.id === id ? live.rows.join("") : "";
}
globalThis.addEventListener?.("hashchange", () => {
  if (location.hash.startsWith("#/ticket/")) return;
  closeLive();
  Object.assign(live, { id: "", rows: [], done: false, follow: true });
});

export async function load(app, id) {
  if (state.id !== id) Object.assign(state, { id, tab: app.ticketTab || "overview", diff: null, file: "", plan: null, park: false, paths: false });
  app.ticketTab = "";
  const data = await get(`/api/tickets/${encodeURIComponent(id)}`);
  if (state.tab === "changes" && state.diff === null && data.changes.length) state.diff = await loadDiff(id);
  return data;
}

async function loadDiff(id) {
  try {
    return (await get(`/api/tickets/${encodeURIComponent(id)}/diff`)).diff;
  } catch {
    return "";
  }
}

// The ticket diff (one `git show` per commit) cut into per-file hunks.
function byFile(diff) {
  const files = {};
  let current = null;
  for (const line of (diff || "").split("\n")) {
    const head = /^diff --git a\/(.+) b\/(.+)$/.exec(line);
    if (head) {
      current = head[2];
      files[current] ??= [];
      continue;
    }
    if (/^[0-9a-f]{40}$/.test(line)) {
      current = null;
      continue;
    }
    if (!current || /^(index |--- |\+\+\+ |new file|deleted file|similarity|rename )/.test(line)) continue;
    files[current].push(line);
  }
  return files;
}

function findings(text) {
  return (text || "")
    .split("\n")
    .filter((line) => line.trim().startsWith("- "))
    .map((line) => {
      const parts = line.trim().slice(2).split(" · ");
      const [severity, where, issue, fix] = parts.length >= 4 ? parts : ["", "", parts.join(" · "), ""];
      const [label, tone] = SEVERITY[severity.toLowerCase()] ?? [severity.toUpperCase() || "NOTE", "plain"];
      return { label, tone, where, issue, fix };
    });
}

function acceptance(text) {
  return (text || "")
    .split("\n")
    .map((line) => /^\s*[-*]\s*(\[( |x|X)\]\s*)?(.+)$/.exec(line))
    .filter(Boolean)
    .map((m) => ({ done: (m[2] || "").toLowerCase() === "x", text: m[3] }));
}

function statusPill(meta) {
  const sub = meta.status.split("/")[1];
  const step = STEPS[meta.step];
  if (meta.status.startsWith("done/")) return html`<span class="spill" style="background: #1E2A20; color: #5FC08B"><span style="background: #5FC08B"></span>${sub.replace("_", " ")}</span>`;
  if (meta.status.startsWith("in_queue/")) return html`<span class="spill" style="background: #22262C; color: #A7B0BC"><span style="background: #A7B0BC"></span>${sub}</span>`;
  const color = GATED.includes(sub) ? (sub === "awaiting_merge" ? "#5FC08B" : "#EF7A72") : step ? step.color : "#A7B0BC";
  return html`<span class="spill" style="background: #22262C; color: ${color}"><span style="background: ${color}"></span>${GATED.includes(sub) ? sub.replace("_", " ") : step?.label ?? sub.replaceAll("_", " ")}</span>`;
}

function gateAction(meta, data) {
  const sub = meta.status.split("/")[1];
  if (sub === "needs_approval") return html`<button class="btn accent big" type="button" data-act="approve">${meta.loop >= meta.loop_max ? `Grant +${data.grant} loops` : "Approve"}</button>`;
  if (sub === "awaiting_merge") return html`<button class="btn accent big" type="button" data-act="merge">Merge</button>`;
  if (["stalled", "failed"].includes(sub) || meta.status === "in_queue/ready") return html`<button class="btn accent big" type="button" data-act="run">${meta.status === "in_queue/ready" ? "Run" : "Run again"}</button>`;
  return "";
}

function overviewTab(data) {
  const meta = data.meta;
  const crit = acceptance(data.sections.Acceptance);
  const siblings = data.siblings.map((s) => s.id);
  const index = [...siblings, meta.id].sort().indexOf(meta.id) + 1;
  return html`
    <h2 class="t-h">Original prompt</h2>
    ${data.plan.found ? html`<blockquote class="prompt-quote">${data.plan.prompt || "The plan has no Prompt section."}</blockquote>` : html`<blockquote class="prompt-quote faint">Plan ${data.plan.id} is not in the store any more.</blockquote>`}
    <div class="t-meta mono"><span>cut from plan <span class="muted">${data.plan.id}</span> · ticket ${index} of ${siblings.length + 1}</span>${siblings.length ? html`<span>sibling tickets: ${data.siblings.map((s, i) => html`${i ? ", " : ""}<a href="#/ticket/${s.id}">${s.id}</a>`)}</span>` : ""}${data.plan.found ? html`<button class="linkish" type="button" data-plan>${state.plan ? "hide the plan" : "read the whole plan"}</button>` : ""}</div>
    ${state.plan ? html`<div class="plan-sections">${Object.entries(state.plan.sections).filter(([name]) => name !== "Prompt" && name !== "Review log").map(([name, text]) => html`<h3>${name}</h3><p>${text}</p>`)}</div>` : ""}
    ${data.sections.Scope ? html`<h2 class="t-h">Scope</h2><p class="t-p">${data.sections.Scope}</p>` : ""}
    <h2 class="t-h">Acceptance criteria</h2>
    ${crit.length ? html`<div class="crit">${crit.map((c) => html`<label><input type="checkbox" ${c.done ? "checked" : ""} data-readonly aria-readonly="true">${c.text}</label>`)}</div>` : html`<p class="t-p faint">None written in the ticket.</p>`}
    <h2 class="t-h">Dependencies</h2>
    <div class="deps-list">
      ${data.depends_on.map((d) => html`<a class="dep-row" href="#/ticket/${d.id}"><span class="dep-tag">WAITS ON</span><span class="mono muted">${d.id}</span><span class="ellipsis">${d.title}</span><span class="end mono faint">${d.status}</span></a>`)}
      ${data.blocks.map((d) => html`<a class="dep-row" href="#/ticket/${d.id}"><span class="dep-tag">BLOCKS</span><span class="mono muted">${d.id}</span><span class="ellipsis">${d.title}</span><span class="end mono faint">${d.status}</span></a>`)}
      <div class="dep-row"><span class="dep-tag">${meta.touches.length ? "PARALLEL" : "SERIAL"}</span><span class="muted">${meta.touches.length ? `touches ${meta.touches.join(", ")}; runs beside tickets that touch other paths` : "names no paths it touches, so it claims the whole repo and runs alone"}</span></div>
    </div>`;
}

// What the worker is doing right now, streamed from /api/tickets/<id>/live (SP12 §4.5).
function liveTab(data) {
  const run = data.running;
  const head = run
    ? html`<div class="live-head"><span class="pulse" aria-hidden="true"></span><span class="sr-only">a worker is running</span><span><strong>${STEPS[run.step]?.label ?? run.step}</strong> ${run.provider ? html`→ <span class="mono">${run.provider}/${run.model}</span>` : html`<span class="muted">(between calls)</span>`}</span><span class="muted"><span data-since="${Math.round(Date.now() / 1000 - run.elapsed_s)}">${span(run.elapsed_s)}</span> · ${run.changed} ${run.changed === 1 ? "file" : "files"} changed</span>${run.quiet ? html`<span class="cchip red">quiet</span>` : ""}${run.alive ? "" : html`<span class="cchip red">worker gone</span>`}</div>`
    : html`<div class="live-head"><span class="muted">No worker is running this ticket; its last activity:</span></div>`;
  return html`${head}<div class="live-rows box" id="live-rows" role="log" aria-live="polite" aria-label="Worker activity">${raw(liveRows(data.meta.id))}</div>`;
}

function changesTab(data) {
  const added = data.changes.reduce((sum, c) => sum + (c.added ?? 0), 0);
  const removed = data.changes.reduce((sum, c) => sum + (c.removed ?? 0), 0);
  const files = byFile(state.diff);
  const chosen = state.file || data.changes[0]?.path || "";
  const list = findings(data.sections.Findings);
  const who = data.timeline.filter((r) => r.kind === "step.end").at(-1)?.role;
  const shown = state.file === "*" ? Object.keys(files) : [chosen];
  const working = data.in_progress.length
    ? html`<h2 class="t-h">In progress <span class="faint">· uncommitted in the worktree while the step runs</span></h2><div class="box">${data.in_progress.map((path) => html`<div class="box-row"><div class="f-file mono ellipsis" title="${path}">${path}</div></div>`)}</div>`
    : "";
  return html`${working}
    <div class="t-row"><h2 class="t-h" style="margin: 0">Changes made under this ticket</h2>${data.changes.length ? html`<span class="mono" style="font-size: 12px"><span class="add">+${added}</span> <span class="del">−${removed}</span></span><button class="btn small end" type="button" data-fulldiff>${state.file === "*" ? "Show one file" : "Open full diff"}</button>` : ""}</div>
    ${data.changes.length
      ? html`<div class="box"><div class="box-head"><div class="f-file">FILE</div><div class="f-diff">DIFF</div><div class="f-who">WRITTEN BY</div><div class="f-loop">LOOP</div></div>
          ${data.changes.map((c) => html`<button type="button" class="box-row ${c.path === chosen && state.file !== "*" ? "on" : ""}" data-file="${c.path}"><div class="f-file mono ellipsis" title="${c.path}">${c.path}</div><div class="f-diff mono"><span class="add">+${c.added ?? "?"}</span> <span class="${c.removed ? "del" : "faint"}">−${c.removed ?? "?"}</span></div><div class="f-who mono muted ellipsis">${c.model.replace("/", " · ")}</div><div class="f-loop mono faint">${c.loop}</div></button>`)}
        </div>
        ${shown.map((path) => {
          const lines = files[path];
          const meta = data.changes.find((c) => c.path === path);
          return html`<div class="box"><div class="box-head diff-head"><span class="mono muted">${path}</span><span class="end mono faint">${meta ? `loop ${meta.loop} · ${meta.commit.slice(0, 7)}` : ""}</span></div>
            <div class="diff-body">${state.diff === null ? html`<span class="faint">Loading the diff…</span>` : lines?.length ? html`<div class="diff-lines">${lines.map((l) => html`<span class="${l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : ""}">${l || " "}</span>`)}</div>` : html`<span class="faint">No textual diff for this file.</span>`}</div></div>`;
        })}`
      : html`<div class="box"><div class="empty">No commits under this ticket yet; the implementer's commits appear here with their loop and model.</div></div>`}
    <h2 class="t-h">Open findings${who ? ` from the ${who}` : ""}</h2>
    ${list.length
      ? html`<div class="findings">${list.map((f) => html`<div class="finding ${f.tone}"><span class="sev ${f.tone}">${f.label}</span><div><div class="f-title">${f.issue}</div><div class="f-desc">${f.fix}${f.where ? html` <span class="mono">${f.where}</span>` : ""}</div></div></div>`)}</div>`
      : html`<p class="t-p faint">No open findings.</p>`}`;
}

function timelineTab(data) {
  const steps = data.timeline.filter((r) => r.kind === "step.end");
  const seconds = steps.reduce((sum, r) => sum + (r.duration_s ?? 0), 0);
  const loops = Math.max(0, ...steps.map((r) => r.loop ?? 0));
  return html`<div class="t-row"><h2 class="t-h" style="margin: 0">Step timeline</h2><span class="faint" style="font-size: 12px">${data.timeline.length} events · ${loops} ${loops === 1 ? "loop" : "loops"} · ${shortTime(seconds)} of session time</span></div>
    ${data.timeline.length
      ? html`<div class="tl">${data.timeline.map((r, i) => {
          if (r.kind !== "step.end") {
            const red = ["ticket.needs_approval", "ticket.stalled", "ticket.failed"].includes(r.kind);
            return html`<div class="tl-row ${red ? "gate" : i % 2 ? "" : "alt"}"><span class="tl-time mono">${clock(r.ts).slice(0, 5)}</span><span class="tl-step" style="color: ${red ? "var(--danger)" : "var(--faint)"}">${r.kind.replace("ticket.", "").replaceAll("_", " ")}</span><span class="tl-who mono muted"></span><span class="tl-text ${red ? "danger-text" : "muted"}">${r.note}</span><span class="tl-dur mono faint"></span></div>`;
          }
          const step = STEPS[r.step];
          const fail = r.verdict === "fail";
          return html`<div class="tl-row ${i % 2 ? "" : "alt"}"><span class="tl-time mono">${clock(r.ts).slice(0, 5)}</span><span class="tl-step" style="color: ${step?.color ?? "var(--muted)"}">${r.step.replaceAll("_", " ")}</span><span class="tl-who mono muted ellipsis">${r.provider}${r.model ? ` · ${r.model}` : ""}</span><span class="tl-text ${fail ? "danger-text" : r.verdict === "pass" ? "ok-text" : "muted"}">${r.verdict || "done"}${r.loop ? html` <span class="faint">· loop ${r.loop}</span>` : ""}${r.tokens ? html` <span class="faint">· ${tokens(r.tokens)} tok</span>` : ""}</span><span class="tl-dur mono faint">${r.duration_s != null ? `${Math.floor(r.duration_s / 60)}m ${String(Math.round(r.duration_s % 60)).padStart(2, "0")}s` : ""}</span></div>`;
        })}</div>`
      : html`<div class="box"><div class="empty">No step has run yet. The timeline fills as workers plan, implement and review.</div></div>`}`;
}

function fileTab(data) {
  const storeRel = data.store_path.split(`/projects/${data.project}/`)[1] ?? data.store_path;
  const repoRel = data.repo_path.split("/.kengash/")[1] ?? data.repo_path;
  const colour = { importance: IMPORTANCE[data.meta.importance]?.[1], status: "var(--warn)" };
  let fence = 0;
  return html`<div class="t-row"><h2 class="t-h" style="margin: 0">Ticket file</h2><span class="mono faint ellipsis" style="font-size: 11px; flex: 1 1 200px" title="${data.store_path}">${state.paths ? data.store_path : `~/.kengash/projects/${data.project}/${storeRel}`} · in the repo: ${state.paths ? data.repo_path : `.kengash/${repoRel}`}</span><button class="btn small end" type="button" data-paths>${state.paths ? "Short paths" : "Show both paths"}</button></div>
    <div class="file-box"><div class="file-lines">${data.file.split("\n").map((line) => {
      if (line === "---") {
        fence += 1;
        return html`<span class="faint">---</span>`;
      }
      const kv = fence === 1 ? /^([\w-]+):(.*)$/.exec(line) : null;
      return kv ? html`<span>${kv[1]}:<span style="color: ${colour[kv[1]] ?? "var(--text)"}">${kv[2]}</span></span>` : html`<span>${line || " "}</span>`;
    })}</div></div>
    <h2 class="t-h">Written to shared memory</h2>
    ${data.memory_writes.length
      ? html`<div class="deps-list">${data.memory_writes.map((w) => html`<div class="dep-row"><span class="mono" style="font-size: 11px">${w.file}</span><span class="muted ellipsis" style="font-size: 12px">${String(w.line).replace(/^- /, "")}</span><span class="end mono faint" style="font-size: 10px">${clock(w.ts).slice(0, 5)}</span></div>`)}</div>`
      : html`<p class="t-p faint">Nothing written to MEMORY.md or DECISIONS.md for this ticket yet.</p>`}`;
}

function rail(data) {
  const meta = data.meta;
  const done = meta.status.startsWith("done/");
  const sub = meta.status.split("/")[1];
  const running = meta.status.startsWith("in_process/") && !GATED.includes(sub);
  const lastRun = (step) => data.timeline.filter((r) => r.kind === "step.end" && r.step === step).at(-1);
  const chain = [...data.chain, { step: "done", role: null, runs: 0, state: done ? "done" : "pending" }];
  const label = { done: "done", running: "running", waiting: "waiting", "needs you": sub === "awaiting_merge" ? "ready" : "blocked", pending: "pending" };
  const sessions = Object.keys(meta.sessions).length;
  return html`<aside class="rail">
    <div><div class="rail-title">AGENT CHAIN</div><div class="chain-list">${chain.map((c, i) => {
      const last = lastRun(c.step);
      const who = last ? (last.model && last.model !== "default" ? last.model : last.provider) : "";
      const right = (c.state === "done" || c.state === "pending") && c.runs ? `${who} ×${c.runs}` : label[c.state];
      return html`<div class="chain-row s-${c.state.replace(" ", "-")}"><span class="num">${i + 1}</span><span class="name">${c.step.replaceAll("_", " ")}</span><span class="end mono">${right}</span></div>`;
    })}</div></div>
    <div class="rail-rule"></div>
    <div><div class="rail-title">METADATA</div><div class="meta-rows">
      <div><span>workflow</span><span class="mono">${meta.workflow}</span></div>
      <div><span>parallel</span><span class="mono ${meta.touches.length ? "ok-text" : "danger-text"}">${meta.touches.length ? "true" : "false"}</span></div>
      <div><span>tokens</span><span class="mono">${tokens(meta.tokens)}${meta.tokens_max ? ` / ${tokens(meta.tokens_max)}` : ""}</span></div>
      <div><span>sessions</span><span class="mono">${sessions ? `${sessions} reused` : "none yet"}</span></div>
      <div><span>gate</span><span class="mono">${meta.gate}</span></div>
      <div><span>updated</span><span class="mono">${clock(meta.updated)}</span></div>
    </div>${meta.tags.length ? html`<div class="tag-pills">${meta.tags.map((t) => html`<span>${t}</span>`)}</div>` : ""}</div>
    <div class="rail-rule"></div>
    <div class="rail-actions">
      ${data.attach ? html`<button class="rail-btn" type="button" data-copy="${data.attach}" data-note="Copied: run it in a terminal to open the live CLI session.">Attach to live CLI session</button>` : ""}
      ${running ? html`<button class="rail-btn" type="button" data-act="stop" data-armed-label="Confirm: stop the step">Stop the running step</button>` : ""}
      ${done
        ? ""
        : html`<button class="rail-btn" type="button" data-act="move" data-to="in_queue">Send back to in_queue</button>
          ${state.park ? html`<form class="park-form" data-park><label class="sr-only" for="why">Why park it</label><input id="why" class="inline-input" name="why" placeholder="why park it?" required><button class="btn small" type="submit">Park</button></form>` : html`<button class="rail-btn" type="button" data-park-open>Park…</button>`}
          <button class="rail-btn danger" type="button" data-act="move" data-to="done" data-armed-label="Confirm: move to done">Force move to done</button>`}
    </div>
  </aside>`;
}

export function top(data, app) {
  const folder = data.store_path.split("/tasks/")[1]?.split("/")[0] ?? "";
  const from = app.from.replace("#/", "").split("/")[0] || "overview";
  const back = { board: "Task board", overview: "Overview", memory: "Memory", workflow: "Workflow", agents: "Agents", settings: "Settings" }[from] ?? "Task board";
  return html`<a class="crumb" href="${app.from}">${back}</a><span class="crumb-sep">/</span><span class="mono crumb-id">${data.meta.id}</span><span class="end mono faint crumb-path">projects/${data.project}/tasks/${folder}/</span>`;
}

export function view(data) {
  const meta = data.meta;
  const imp = IMPORTANCE[meta.importance] ?? IMPORTANCE.standard;
  const atCap = meta.loop >= meta.loop_max;
  const counts = { changes: data.changes.length + data.in_progress.length, timeline: data.timeline.length };
  const live = data.running || state.tab === "live";
  if (!live && state.tab === "live") state.tab = "overview";
  const body = { live: liveTab, overview: overviewTab, changes: changesTab, timeline: timelineTab, file: fileTab }[state.tab](data);
  const tabs = [...(live ? [["live", "Live"]] : []), ["overview", "Overview"], ["changes", "Changes"], ["timeline", "Timeline"], ["file", "Memory file"]];
  return html`<div class="sheet-stage">
    <div class="sheet-ghost" aria-hidden="true"><div></div><div></div><div></div><div></div></div>
    <div class="sheet-dim" aria-hidden="true" data-close></div>
    <article class="sheet" aria-labelledby="sheet-title">
      <header class="sheet-head">
        <div class="sheet-tags"><span class="ibadge" style="background: ${imp[0]}; color: ${imp[1]}">${meta.importance.toUpperCase()}</span>${statusPill(meta)}<span class="mono faint uuid">${meta.uuid}</span>
          <button class="close" type="button" data-close aria-label="Close ticket" title="Close (Esc)">${icon("close", { size: 14, width: 1.7 })}</button></div>
        <div class="sheet-title"><h1 id="sheet-title">${meta.title}</h1><div class="sheet-gate"><span class="loop-pill ${atCap ? "cap" : ""}">loop ${meta.loop}/${meta.loop_max}${atCap ? " · cap hit" : ""}</span>${gateAction(meta, data)}</div></div>
        <div class="sheet-meta mono"><span>${data.project}</span>${meta.touches.length ? html`<span title="${meta.touches.join(", ")}">${meta.touches[0]}${meta.touches.length > 1 ? ` +${meta.touches.length - 1}` : ""}</span>` : ""}${meta.branch ? html`<span>${meta.branch}</span>` : ""}<span>opened ${clock(meta.created).slice(0, 5)} · ${elapsed(meta.created)} ago</span></div>
      </header>
      <div class="tabs-line sheet-tabs" role="tablist">${tabs.map(
        ([key, label]) => html`<button type="button" role="tab" data-tab="${key}" aria-selected="${state.tab === key ? "true" : "false"}">${label}${counts[key] ? html`<span class="count mono">${counts[key]}</span>` : ""}</button>`,
      )}</div>
      <div class="sheet-body"><div class="sheet-main">${body}</div>${rail(data)}</div>
    </article>
  </div>`;
}

let onKey = null; // the Escape listener of the open sheet, replaced on each render
export function bind(root, app, data) {
  const id = data.meta.id;
  const rows = root.querySelector("#live-rows");
  if (!rows) closeLive();
  else {
    if (live.follow) rows.scrollTop = rows.scrollHeight;
    rows.addEventListener("scroll", () => (live.follow = rows.scrollHeight - rows.scrollTop - rows.clientHeight < 40));
    const fresh = live.id !== id;
    if (fresh || (!live.source && !live.done)) {
      closeLive();
      if (fresh) Object.assign(live, { id, rows: [], done: false, follow: true });
      const source = new EventSource(`/api/tickets/${encodeURIComponent(id)}/live`);
      live.source = source;
      source.addEventListener("open", () => {
        // the stream starts with the whole history, a reconnect too: start the rows over
        live.rows = [];
        const box = document.getElementById("live-rows");
        if (box) box.textContent = "";
      });
      source.addEventListener("activity", (event) => {
        liveAppend(id, JSON.parse(event.data));
        const box = document.getElementById("live-rows");
        if (!box) return;
        box.insertAdjacentHTML("beforeend", live.rows.at(-1));
        if (live.follow) box.scrollTop = box.scrollHeight;
      });
      source.addEventListener("done", () => {
        live.done = true;
        closeLive();
      });
    }
    if (!live.done) live.timer ??= setInterval(() => tick(document), 1000);
  }
  const close = () => (location.hash = app.from || "#/board");
  const why = () => root.querySelector("#why")?.value.trim() ?? "";
  if (state.focused !== id) {
    state.focused = id;
    root.querySelector(".close")?.focus({ preventScroll: true });
  }
  if (onKey) document.removeEventListener("keydown", onKey);
  onKey = (event) => {
    if (event.key !== "Escape" || document.body.dataset.screen !== "ticket" || event.target.closest?.("input, textarea")) return;
    document.removeEventListener("keydown", onKey);
    onKey = null;
    close();
  };
  document.addEventListener("keydown", onKey);
  root.addEventListener("click", async (event) => {
    if (event.target.closest("[data-readonly]")) return event.preventDefault();
    if (event.target.closest("[data-close]")) return close();
    const tab = event.target.closest("[data-tab]");
    if (tab) {
      state.tab = tab.dataset.tab;
      if (state.tab === "changes" && state.diff === null && data.changes.length) state.diff = await loadDiff(id);
      return app.refresh();
    }
    const file = event.target.closest("[data-file]");
    if (file) {
      state.file = file.dataset.file;
      if (state.diff === null) state.diff = await loadDiff(id);
      return app.refresh();
    }
    if (event.target.closest("[data-fulldiff]")) {
      state.file = state.file === "*" ? "" : "*";
      if (state.diff === null) state.diff = await loadDiff(id);
      return app.refresh();
    }
    if (event.target.closest("[data-plan]")) {
      state.plan = state.plan ? null : ((await get(`/api/plans/${data.plan.id}`).catch((error) => app.toast(error.message, true))) ?? null);
      return app.refresh();
    }
    if (event.target.closest("[data-paths]")) {
      state.paths = !state.paths;
      return app.refresh();
    }
    if (event.target.closest("[data-park-open]")) {
      state.park = true;
      await app.refresh();
      return document.getElementById("why")?.focus();
    }
    const act = event.target.closest("[data-act]");
    if (!act || act.type === "submit") return;
    if (act.dataset.armedLabel && !armed(act, act.dataset.armedLabel)) return;
    const body = act.dataset.act === "move" ? { to: act.dataset.to, why: `moved from the UI to ${act.dataset.to}` } : {};
    act.disabled = true;
    const result = await app.post(`/api/tickets/${id}/${act.dataset.act}`, body);
    const said = { approve: "approved; its loop restarts", run: "started", stop: "stopped", merge: "merged", move: `moved to ${act.dataset.to}` };
    if (result) app.toast(`${id} ${said[act.dataset.act] ?? act.dataset.act}.`);
    else act.disabled = false;
  });
  root.addEventListener("submit", async (event) => {
    if (!event.target.closest("[data-park]")) return;
    event.preventDefault();
    if (!why()) return app.toast("Say why to park it.", true);
    const result = await app.post(`/api/tickets/${id}/park`, { why: why() });
    if (result) {
      state.park = false;
      app.toast(`${id} parked.`);
    }
  });
}
