// Workflow editor (SP10 spec §5.4, mock-up A; SP5 spec decision 10): workflow tabs with New
// workflow and a menu to rename, copy or delete one; a top-to-bottom graph with a "+" on every
// link to insert any agent there, nodes that drag (or move with Alt+arrows), and an inspector
// to swap a node's agent, set where a fail sends the ticket, or remove it; beside it, which
// workflow each importance gets and its loop cap. A save writes each edited workflows.<name>
// whole, the routing and the caps to SETTINGS.md; workflows are created, renamed and deleted
// at once through ops.workflows.
import { post } from "../api.js";
import { agentPicker, bindAgentPicker } from "../controls.js";
import { LABELS, TONES, canvas, layout, learnSteps } from "../graph.js";
import { html, mount } from "../html.js";
import { STEP_ICONS, icon } from "../icons.js";
import { armed, bindScope, configBar, loadScoped, scopeOf } from "../scope.js";

const state = { scope: null, tab: "", selected: "", drafts: {}, loops: {}, routing: {}, flags: {}, dry: false, zoom: 1, fitted: false, picking: null };
const IMP = { simple: "#68A4E0", standard: "#D8B24C", critical: "#EF7A72" };
const IMPORTANCES = ["simple", "standard", "critical"];
const FLAGS = { "review.diff_only": "review_diff_only", "sessions.reuse": "sessions_reuse", loop_ask_at_cap: "loop_ask_at_cap" };
const NAME = /^[a-z][a-z0-9_-]{0,30}$/;

// --- pure edits of a workflow draft {steps, on_fail}; send-back edges only go up -----------
export function backTargets(steps, step) {
  return steps.slice(0, steps.indexOf(step));
}

function keepBackward(steps, onFail) {
  return Object.fromEntries(Object.entries(onFail).filter(([from, to]) => steps.includes(from) && steps.includes(to) && steps.indexOf(to) < steps.indexOf(from)));
}

export function insertStep(draft, at, step) {
  const steps = [...draft.steps];
  steps.splice(at, 0, step);
  return { steps, on_fail: { ...draft.on_fail } };
}

export function moveStep(draft, step, to) {
  const steps = draft.steps.filter((one) => one !== step);
  steps.splice(Math.max(0, Math.min(to, steps.length)), 0, step);
  return { steps, on_fail: keepBackward(steps, draft.on_fail) };
}

export function removeStep(draft, step) {
  const steps = draft.steps.filter((one) => one !== step);
  return { steps, on_fail: keepBackward(steps, draft.on_fail) };
}

// The node keeps its place; edges into it follow the new step, and its own send-back edge
// stays only when the new step reviews too.
export function swapStep(draft, old, step, kinds) {
  const steps = draft.steps.map((one) => (one === old ? step : one));
  const on_fail = {};
  for (const [from, to] of Object.entries(draft.on_fail)) {
    if (from === old) {
      if (kinds[step] === "review") on_fail[step] = to;
    } else on_fail[from] = to === old ? step : to;
  }
  return { steps, on_fail };
}

// --- screen ------------------------------------------------------------------------------------
export async function load(app) {
  if (state.scope !== scopeOf(app)) Object.assign(state, { scope: scopeOf(app), tab: "", selected: "", drafts: {}, loops: {}, routing: {}, flags: {}, dry: false, fitted: false, picking: null });
  const data = await loadScoped(app, "/api/workflows");
  learnSteps(data.kinds);
  return data;
}

const clone = (flow) => ({ steps: [...flow.steps], on_fail: { ...flow.on_fail } });
const draftOf = (data, name) => state.drafts[name] ?? clone(data.workflows[name]);
const loopsOf = (data, imp) => state.loops[imp] ?? data.loop_max[imp];
const routeOf = (data, imp) => state.routing[imp] ?? data.routing[imp];
const flagOf = (data, key) => (key in state.flags ? state.flags[key] : data[FLAGS[key]]);
const label = (step) => LABELS[step] ?? step.replace(/_/g, " ");
const routedFrom = (data, name) => IMPORTANCES.filter((imp) => routeOf(data, imp) === name);

function effective(data, steps) {
  return steps.filter((step) => {
    const role = data.roles[step];
    if (role && data.off.includes(role)) return false;
    return !(step === "review_plan" && !data.plan_review);
  });
}

function problem(draft) {
  if (!draft.steps.length) return "a workflow needs at least one step";
  const stray = Object.entries(draft.on_fail).filter(([from, to]) => !draft.steps.includes(from) || !draft.steps.includes(to));
  return stray.length ? `send-back edge ${stray[0][0]} → ${stray[0][1]} leaves the workflow` : "";
}

function pickerAgents(data, draft) {
  return data.picker.map((pick) => ({ ...pick, label: pick.role || "You approve", kind: pick.step === "approve" ? "pause" : pick.on ? { review: "reviewer", edit: "worker", read: "advisor", check: "shell check" }[pick.kind] ?? pick.kind : "off", used: draft.steps.includes(pick.step) }));
}

function inspector(data, draft) {
  const step = state.selected;
  if (!draft.steps.includes(step)) {
    return html`<section class="panel"><div class="panel-body"><h2 class="section-title">No step selected</h2><p class="section-note" style="margin: 0">Click a step to swap its agent, choose where a failing verdict sends the ticket, or remove it. Use a + between steps to insert an agent, and drag a step (or Alt+↑/↓) to move it.</p></div></section>`;
  }
  const role = data.roles[step];
  const index = draft.steps.indexOf(step);
  const [tile, stroke] = TONES[step] ?? TONES.trigger;
  const review = data.kinds[step] === "review";
  const swaps = data.picker.filter((pick) => pick.step === step || !draft.steps.includes(pick.step));
  const targets = backTargets(draft.steps, step);
  return html`<section class="panel"><div class="panel-body">
    <div class="sel-head"><span class="wf-icon small" style="background: ${tile}">${icon(STEP_ICONS[step] ?? "plan", { size: 13, stroke, width: 1.6 })}</span><h2>${index + 1} · ${label(step)}</h2><button class="icon-btn wide" type="button" data-remove aria-label="Remove ${label(step)} from the workflow" title="Remove the step">${icon("trash", { size: 13, width: 1.6 })}</button></div>
    <p class="section-note" style="margin: 0 0 16px">Selected step · saved under workflows.${state.tab}</p>
    <div class="sel-fields">
      <div class="field"><label for="wf-agent">AGENT AT THIS STEP</label><select id="wf-agent" class="select sans full" data-swap>${swaps.map((pick) => html`<option value="${pick.step}" ${pick.step === step ? "selected" : ""}>${pick.role || "You approve"}${pick.step === step ? "" : ` · ${label(pick.step)}`}</option>`)}</select>${role ? html`<a class="sel-link" href="#/agents/${encodeURIComponent(role)}">Edit ${role}</a>` : ""}</div>
      ${review ? html`<div class="field"><label for="wf-send-back">A FAIL SENDS THE TICKET TO</label><select id="wf-send-back" class="select sans full" data-onfail="${step}">${targets.map((other) => html`<option value="${other}" ${draft.on_fail[step] === other ? "selected" : ""}>${draft.steps.indexOf(other) + 1} · ${label(other)}</option>`)}<option value="" ${draft.on_fail[step] ? "" : "selected"}>stop and ask me</option></select></div>` : html`<p class="section-note" style="margin: 0">Only a reviewer's fail sends a ticket back.</p>`}
      ${review ? html`<label class="boxed-check"><input type="checkbox" data-flag="review.diff_only" ${flagOf(data, "review.diff_only") ? "checked" : ""}>Reviewers read the diff only, never the whole tree</label>` : ""}
      ${role ? html`<label class="boxed-check"><input type="checkbox" data-flag="sessions.reuse" ${flagOf(data, "sessions.reuse") ? "checked" : ""}>Reuse each agent's CLI session, no cold start</label>` : ""}
      <div class="sel-move"><button class="btn small" type="button" data-move="-1" ${index === 0 ? "disabled" : ""}>Move up</button><button class="btn small" type="button" data-move="1" ${index === draft.steps.length - 1 ? "disabled" : ""}>Move down</button></div>
    </div>
  </div></section>`;
}

function routing(data) {
  return html`<section class="panel"><div class="panel-body">
    <h2 class="section-title">Importance → workflow</h2><p class="section-note">The workflow a freshly cut ticket gets, and how many loops it may take before it asks you. Other workflows are picked per ticket.</p>
    <div class="routes"><div class="route-head faint"><span></span><span>importance</span><span>workflow</span><span>max loops</span></div>${IMPORTANCES.map((imp) => html`<div class="route ${imp === "critical" ? "is-crit" : ""}"><span class="bar" style="background: ${IMP[imp]}"></span><label class="route-name" for="wf-route-${imp}">${imp}</label>
      <select id="wf-route-${imp}" class="select route-flow ${data.set_here.includes(`routing.${imp}`) ? "set" : ""}" data-route="${imp}">${data.names.map((name) => html`<option value="${name}" ${name === routeOf(data, imp) ? "selected" : ""}>${name}</option>`)}</select>
      <label class="sr-only" for="wf-loops-${imp}">${imp} max loops</label><input id="wf-loops-${imp}" class="mono route-loops ${data.set_here.includes(`loop_max.${imp}`) ? "set" : ""}" type="number" min="1" max="20" data-loops="${imp}" value="${loopsOf(data, imp)}"></div>`)}</div>
    <label class="check"><input type="checkbox" data-flag="loop_ask_at_cap" ${flagOf(data, "loop_ask_at_cap") ? "checked" : ""}>Ask me before granting extra loops (off: park the ticket)</label>
  </div></section>`;
}

function editor(data) {
  const name = state.tab;
  const draft = draftOf(data, name);
  const graph = layout(draft.steps, draft.on_fail);
  const runs = effective(data, draft.steps);
  const issue = problem(draft);
  const ghost = !draft.steps.includes("run_tests") && data.library.includes("run_tests") ? "run_tests" : "";
  const routed = routedFrom(data, name);
  return html`<div class="wf-row">
    <section class="panel wf-panel">
      <div class="panel-head"><h2>${name}</h2><span class="mono faint" style="font-size: 11px">${draft.steps.length} steps · ${routed.length ? `new ${routed.join(", ")} tickets` : "picked per ticket"}</span>
        ${issue ? html`<span class="pill danger end">${icon("warning", { size: 12, width: 1.8 })}${issue}</span>` : html`<span class="pill ok end">${icon("check", { size: 12, width: 1.8 })}every step reachable</span>`}</div>
      ${data.warnings[name] ? html`<div class="banner" style="margin: 14px 18px 0"><span class="badge danger">blocking</span>${data.warnings[name]}</div>` : ""}
      <div class="wf-tools">
        <button class="btn small" type="button" data-add-end>${icon("plus", { size: 13, width: 1.9 })}Add step</button>
        <button class="btn small quiet" type="button" data-autolayout title="The layout is always automatic; this fits it to the view">Fit</button>
        <button class="btn small quiet" type="button" data-dry aria-pressed="${state.dry ? "true" : "false"}">${state.dry ? "Hide dry run" : "Dry run"}</button>
        <div class="zoom"><button type="button" data-zoom="-1" aria-label="Zoom out">${icon("minus", { size: 13, width: 1.9 })}</button><span class="mono">${Math.round(state.zoom * 100)}%</span><button type="button" data-zoom="1" aria-label="Zoom in">${icon("plus", { size: 13, width: 1.9 })}</button><button type="button" data-zoom="fit" aria-label="Fit to view">${icon("fit", { size: 13, width: 1.6 })}</button></div>
      </div>
      ${state.dry ? html`<div class="wf-dry"><span class="faint">A ${name} ticket runs</span> <span class="mono">${runs.length ? runs.join(" → ") : "no step"}</span>${runs.length < draft.steps.length ? html`<span class="faint"> · skipped: ${draft.steps.filter((s) => !runs.includes(s)).join(", ")}</span>` : ""}</div>` : ""}
      <div class="wf-stage"><div class="wf-zoom" style="transform: scale(${state.zoom}); width: ${100 / state.zoom}%">${canvas(graph, {
        selected: state.selected,
        sub: (id) => (id === "trigger" ? "in_queue · /kengash:loop" : id === "done" ? "tasks/<project>/done/" : !data.roles[id] ? "you approve" : data.blocking.includes(data.roles[id]) ? "blocking gate" : `${data.roles[id]} · ${(data.agents[data.roles[id]] ?? "").replace("/", " · ")}`),
        off: (id) => draft.steps.includes(id) && !runs.includes(id),
        gate: (id) => data.blocking.includes(data.roles[id]),
        ghost,
        insert: true,
      })}</div><div class="wf-pick-layer"></div></div>
      <div class="legend"><span><i class="solid"></i>pass forward</span><span><i class="dashed"></i>send back · counts as a loop</span><span><i class="portdot"></i>port</span><span class="faint">+ inserts an agent · drag or Alt+↑/↓ moves a step</span></div>
    </section>
    <div class="wf-side">${inspector(data, draft)}${routing(data)}</div>
  </div>`;
}

function tabsView(data) {
  return html`<div class="flow-bar">
    <div class="imp-tabs" role="tablist" aria-label="Workflow">${data.names.map((name) => html`<button type="button" role="tab" data-flow="${name}" aria-selected="${name === state.tab ? "true" : "false"}"><span style="background: ${IMP[name] ?? "#78828F"}"></span>${name}${state.drafts[name] ? " •" : ""}</button>`)}</div>
    <button class="btn small" type="button" data-new-flow>${icon("plus", { size: 12, width: 1.9 })}New workflow</button>
    <details class="ag-menu flow-menu"><summary class="icon-btn wide" aria-label="More for ${state.tab}">${icon("more", { size: 14 })}</summary><div class="ag-menu-list" role="menu">
      <button type="button" role="menuitem" data-rename-flow>${icon("pencil", { size: 13 })}Rename ${state.tab}</button>
      <button type="button" role="menuitem" data-copy-flow>${icon("copy", { size: 13 })}Copy ${state.tab}</button>
      <button type="button" role="menuitem" class="danger-text" data-delete-flow>${icon("trash", { size: 13 })}Delete ${state.tab}</button>
    </div></details>
  </div>`;
}

function dialog() {
  return html`<dialog class="wf-dialog" id="wf-dialog" aria-labelledby="wf-dialog-title"><form class="wf-dialog-form" method="dialog" novalidate>
    <h2 id="wf-dialog-title"></h2>
    <div class="field"><label for="wf-name">Name</label><input id="wf-name" class="text-input mono" maxlength="31" autocomplete="off" spellcheck="false" placeholder="hotfix" aria-describedby="wf-name-hint"><small id="wf-name-hint" class="faint">lowercase letters, digits, - and _</small></div>
    <div class="field" data-from-field><label for="wf-from">Start from</label><select id="wf-from" class="select sans full"></select></div>
    <p class="danger-text wf-dialog-error" role="alert"></p>
    <div class="wf-dialog-foot"><button class="btn quiet" type="button" data-dialog-cancel>Cancel</button><button class="btn accent" type="submit"></button></div>
  </form></dialog>`;
}

export function top(data, app) {
  return configBar(app, data.projects, data.set_here, {});
}

export function view(data) {
  if (data.problem) {
    return html`<div class="page"><div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix SETTINGS.md, or run kengash settings check.</div></div>`;
  }
  if (!data.names.includes(state.tab)) state.tab = data.names.includes("critical") ? "critical" : data.names[0] ?? "";
  return html`<div class="page wide-page">
    <div class="page-head"><div><h1>Collaboration workflow</h1><p>One step graph per workflow. A ticket enters at the trigger and only leaves through done; a dashed edge sends it back and burns a loop.</p></div></div>
    <div class="wf-tabs-slot">${tabsView(data)}</div>
    <div class="wf-editor">${data.names.length ? editor(data) : html`<div class="panel"><div class="empty">No workflow in these settings yet.</div></div>`}</div>
    ${dialog()}
  </div>`;
}

export function bind(root, app, data, bar) {
  if (data.problem || !data.names.length) return;
  const extra = () => {
    const found = {};
    for (const [name, draft] of Object.entries(state.drafts)) {
      if (JSON.stringify(draft) !== JSON.stringify(clone(data.workflows[name]))) found[`workflows.${name}`] = draft;
    }
    for (const [imp, loops] of Object.entries(state.loops)) if (loops !== data.loop_max[imp] && loops >= 1) found[`loop_max.${imp}`] = loops;
    for (const [imp, flow] of Object.entries(state.routing)) if (flow !== data.routing[imp]) found[`routing.${imp}`] = flow;
    for (const [key, value] of Object.entries(state.flags)) if (value !== data[FLAGS[key]]) found[key] = value;
    return found;
  };
  const { dirty } = bindScope(root, app, { setHere: data.set_here, extra, bar, clear: () => Object.assign(state, { drafts: {}, loops: {}, routing: {}, flags: {}, picking: null }) });
  const box = root.querySelector(".wf-editor");
  const tabsSlot = root.querySelector(".wf-tabs-slot");
  // floor: the smallest zoom a fit may pick; the first, automatic fit keeps text readable
  // and lets a narrow screen pan the graph inside its stage instead
  const fit = (floor = 0.4) => {
    const stage = root.querySelector(".wf-stage");
    const inner = root.querySelector(".wf-canvas");
    if (!stage || !inner) return;
    const wide = (stage.clientWidth - 40) / inner.offsetWidth;
    const tall = Math.max(floor, (window.innerHeight - 260) / inner.offsetHeight);
    state.zoom = Math.round(Math.max(floor, Math.min(1.5, wide, tall)) * 100) / 100;
  };
  // a scaled element keeps its layout height: pull the space it no longer fills back up
  const settle = () => {
    const zoom = box.querySelector(".wf-zoom");
    const inner = box.querySelector(".wf-canvas");
    if (zoom && inner) zoom.style.marginBottom = `${(state.zoom - 1) * inner.offsetHeight}px`;
  };
  const redraw = () => {
    mount(box, editor(data));
    mount(tabsSlot, tabsView(data));
    settle();
    if (state.picking) openPicker();
    dirty();
  };
  const edit = (change) => {
    state.drafts[state.tab] = change(draftOf(data, state.tab));
    redraw();
  };
  const focusNode = (step) => box.querySelector(`[data-node="${CSS.escape(step)}"]`)?.focus();
  const insertAt = (at, step) => {
    state.picking = null;
    state.selected = step;
    edit((draft) => insertStep(draft, at, step));
    focusNode(step);
  };
  function openPicker() {
    const layer = box.querySelector(".wf-pick-layer");
    const stage = box.querySelector(".wf-stage");
    const anchor = state.picking.at === "end" ? box.querySelector("[data-add-end]") : box.querySelector(`[data-insert-at="${state.picking.at}"]`);
    if (!layer || !anchor) return;
    mount(layer, agentPicker({ agents: pickerAgents(data, draftOf(data, state.tab)) }));
    const picker = layer.firstElementChild;
    const [a, s] = [anchor.getBoundingClientRect(), stage.getBoundingClientRect()];
    const left = Math.min(a.right - s.left + stage.scrollLeft + 8, stage.scrollLeft + stage.clientWidth - picker.offsetWidth - 8);
    picker.style.left = `${Math.max(8, left)}px`;
    picker.style.top = `${Math.max(8, a.top - s.top + stage.scrollTop - 8)}px`;
    const at = state.picking.at === "end" ? draftOf(data, state.tab).steps.length : state.picking.at;
    bindAgentPicker(picker, (step) => insertAt(at, step), closePicker);
  }
  function closePicker() {
    const at = state.picking?.at;
    state.picking = null;
    mount(box.querySelector(".wf-pick-layer"), "");
    (at === "end" ? box.querySelector("[data-add-end]") : box.querySelector(`[data-insert-at="${at}"]`))?.focus();
  }

  if (!state.fitted) {
    state.fitted = true;
    const stage = root.querySelector(".wf-stage");
    const inner = root.querySelector(".wf-canvas");
    if (stage && inner && inner.offsetWidth > stage.clientWidth - 40) {
      fit(0.6);
      redraw();
    }
  }
  settle();

  tabsSlot.addEventListener("click", async (event) => {
    const tab = event.target.closest("[data-flow]");
    if (tab) {
      Object.assign(state, { tab: tab.dataset.flow, selected: "", picking: null });
      return redraw();
    }
    if (event.target.closest("[data-new-flow]")) return openDialog("new");
    if (event.target.closest("[data-copy-flow]")) return openDialog("copy");
    if (event.target.closest("[data-rename-flow]")) {
      if (state.drafts[state.tab]) return app.toast(`Save or discard the changes to ${state.tab} first.`, true);
      return openDialog("rename");
    }
    const remove = event.target.closest("[data-delete-flow]");
    if (remove) {
      if (!armed(remove, `Click again to delete ${state.tab}`)) return;
      const done = await app.post(`/api/workflows/${encodeURIComponent(state.tab)}/remove`, { project: scopeOf(app) });
      if (done) {
        delete state.drafts[state.tab];
        app.toast(`Deleted workflow ${state.tab}.`);
        state.tab = "";
      }
    }
  });

  const modal = root.querySelector("#wf-dialog");
  const form = modal.querySelector("form");
  const nameInput = modal.querySelector("#wf-name");
  const fromSelect = modal.querySelector("#wf-from");
  const error = modal.querySelector(".wf-dialog-error");
  let dialogMode = "new";
  function openDialog(mode) {
    dialogMode = mode;
    form.reset();
    error.textContent = "";
    modal.querySelector("#wf-dialog-title").textContent = mode === "rename" ? `Rename ${state.tab}` : mode === "copy" ? `Copy ${state.tab}` : "New workflow";
    modal.querySelector("[type=submit]").textContent = mode === "rename" ? "Rename" : "Create";
    modal.querySelector("[data-from-field]").hidden = mode !== "new";
    mount(fromSelect, html`<option value="">one implement step</option>${data.names.map((name) => html`<option value="${name}" ${name === state.tab ? "selected" : ""}>a copy of ${name}</option>`)}`);
    nameInput.value = mode === "rename" ? state.tab : mode === "copy" ? `${state.tab}-copy`.slice(0, 31) : "";
    modal.showModal();
    nameInput.focus();
    nameInput.select();
  }
  modal.querySelector("[data-dialog-cancel]").addEventListener("click", () => modal.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = nameInput.value.trim();
    if (!NAME.test(name)) {
      error.textContent = "Start with a lowercase letter; use lowercase letters, digits, - and _ (at most 31).";
      return;
    }
    const scope = scopeOf(app);
    try {
      if (dialogMode === "rename") await post(`/api/workflows/${encodeURIComponent(state.tab)}/rename`, { project: scope, new: name });
      else await post("/api/workflows", { project: scope, name, from: dialogMode === "copy" ? state.tab : fromSelect.value || null });
      modal.close();
      app.toast(dialogMode === "rename" ? `Renamed ${state.tab} to ${name}.` : `Added workflow ${name}.`);
      state.tab = name;
      state.selected = "";
      app.dirty = false;
      await app.refresh();
    } catch (failure) {
      error.textContent = failure.message;
    }
  });

  box.addEventListener("click", (event) => {
    if (state.picking && !event.target.closest(".picker, [data-insert-at], [data-add-end]")) closePicker();
    const target = event.target.closest("[data-node], [data-ghost], [data-insert-at], [data-add-end], [data-move], [data-remove], [data-dry], [data-zoom], [data-autolayout]");
    if (!target) return;
    if (target.dataset.node) {
      state.selected = state.selected === target.dataset.node ? "" : target.dataset.node;
      redraw();
      return focusNode(target.dataset.node);
    }
    if (target.dataset.ghost) return insertAt(draftOf(data, state.tab).steps.length, target.dataset.ghost);
    if (target.dataset.insertAt !== undefined || target.dataset.addEnd !== undefined) {
      const at = target.dataset.addEnd !== undefined ? "end" : Number(target.dataset.insertAt);
      state.picking = state.picking?.at === at ? null : { at };
      return state.picking ? openPicker() : closePicker();
    }
    if (target.dataset.dry !== undefined) {
      state.dry = !state.dry;
      return redraw();
    }
    if (target.dataset.autolayout !== undefined || target.dataset.zoom === "fit") {
      fit();
      return redraw();
    }
    if (target.dataset.zoom) {
      state.zoom = Math.max(0.4, Math.min(1.5, Math.round((state.zoom + Number(target.dataset.zoom) * 0.1) * 10) / 10));
      return redraw();
    }
    if (target.dataset.move) {
      const step = state.selected;
      edit((draft) => moveStep(draft, step, draft.steps.indexOf(step) + Number(target.dataset.move)));
      return box.querySelector(`[data-move="${target.dataset.move}"]`)?.focus();
    }
    if (target.dataset.remove !== undefined) {
      const gone = state.selected;
      state.selected = "";
      edit((draft) => removeStep(draft, gone));
    }
  });

  box.addEventListener("keydown", (event) => {
    const node = event.target.closest("[data-node], [data-ghost]");
    if (!node) return;
    if (event.altKey && node.dataset.node && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      const step = node.dataset.node;
      state.selected = step;
      edit((draft) => moveStep(draft, step, draft.steps.indexOf(step) + (event.key === "ArrowUp" ? -1 : 1)));
      return focusNode(step);
    }
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    node.click();
  });

  let dragged = "";
  box.addEventListener("dragstart", (event) => {
    dragged = event.target.closest("[data-node]")?.dataset.node ?? "";
    event.dataTransfer?.setData("text/plain", dragged);
  });
  box.addEventListener("dragover", (event) => {
    if (dragged && event.target.closest("[data-node]")) event.preventDefault();
  });
  box.addEventListener("drop", (event) => {
    const target = event.target.closest("[data-node]");
    if (!dragged || !target || target.dataset.node === dragged) return;
    event.preventDefault();
    const step = dragged;
    dragged = "";
    state.selected = step;
    edit((draft) => moveStep(draft, step, draft.steps.indexOf(target.dataset.node)));
  });

  box.addEventListener("change", (event) => {
    const back = event.target.closest("[data-onfail]");
    if (back) {
      return edit((draft) => {
        const on_fail = { ...draft.on_fail };
        if (back.value) on_fail[back.dataset.onfail] = back.value;
        else delete on_fail[back.dataset.onfail];
        return { steps: draft.steps, on_fail };
      });
    }
    const swap = event.target.closest("[data-swap]");
    if (swap && swap.value !== state.selected) {
      const old = state.selected;
      state.selected = swap.value;
      return edit((draft) => swapStep(draft, old, swap.value, data.kinds));
    }
    const route = event.target.closest("[data-route]");
    if (route) {
      state.routing[route.dataset.route] = route.value;
      return redraw();
    }
    const flag = event.target.closest("[data-flag]");
    if (flag) {
      state.flags[flag.dataset.flag] = flag.checked;
      return dirty();
    }
  });
  box.addEventListener("input", (event) => {
    const loops = event.target.closest("[data-loops]");
    if (loops) {
      state.loops[loops.dataset.loops] = Number(loops.value);
      dirty();
    }
  });
  document.addEventListener("keydown", function close(event) {
    if (!box.isConnected) return document.removeEventListener("keydown", close);
    if (event.key === "Escape" && state.picking) closePicker();
  });
}
