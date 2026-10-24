// Workflow editor (canvas board Workflow, SP5 spec decision 10): importance tabs over a
// top-to-bottom graph, edited structurally (add, move, remove a step, retarget its send-back
// edge, pick its agent's CLI and skill), with the loop caps beside it; a save writes each
// edited workflows.<name> whole to SETTINGS.md.
import { LABELS, TONES, canvas, layout } from "../graph.js";
import { html, mount } from "../html.js";
import { STEP_ICONS, icon } from "../icons.js";
import { bindScope, configBar, loadScoped, scopeOf } from "../scope.js";

const state = { scope: null, tab: "", selected: "", drafts: {}, cli: {}, skill: {}, loops: {}, flags: {}, dry: false, zoom: 1, library: false };
const IMP = { simple: "#68A4E0", standard: "#D8B24C", critical: "#EF7A72" };
const OUTS = { plan: "1 out", review_plan: "2 out", implement: "1 out", review_code: "2 out", security: "2 out", run_tests: "shell", docs: "1 out", approve: "pause" };
const COMMON_CLIS = ["claude", "claude/opus", "claude/sonnet", "claude/haiku", "codex", "antigravity", "shell"];

export async function load(app) {
  if (state.scope !== scopeOf(app)) Object.assign(state, { scope: scopeOf(app), tab: "", selected: "", drafts: {}, cli: {}, skill: {}, loops: {}, flags: {}, dry: false, library: false });
  return loadScoped(app, "/api/workflows");
}

const clone = (flow) => ({ steps: [...flow.steps], on_fail: { ...flow.on_fail } });
const draftOf = (data, name) => state.drafts[name] ?? clone(data.workflows[name]);
const cliOf = (data, role) => state.cli[role] ?? data.agents[role] ?? "";
const skillOf = (data, role) => state.skill[role] ?? data.skills[role] ?? "";
const loopsOf = (data, name) => state.loops[name] ?? data.loop_max[name];
const FLAGS = { "review.diff_only": "review_diff_only", "sessions.reuse": "sessions_reuse", loop_ask_at_cap: "loop_ask_at_cap" };
const flagOf = (data, key) => (key in state.flags ? state.flags[key] : data[FLAGS[key]]);

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

function cliChoices(data, role) {
  const current = cliOf(data, role);
  return [...new Set([current, ...Object.values(data.agents), ...COMMON_CLIS].filter(Boolean))];
}

function selectedPanel(data, draft) {
  const step = state.selected;
  if (!draft.steps.includes(step)) {
    return html`<section class="panel"><div class="panel-body"><h2 class="section-title">No step selected</h2><p class="section-note" style="margin: 0">Click a step on the canvas to choose its agent's CLI and skill, where a failing verdict sends the ticket, or to move or remove it.</p></div></section>`;
  }
  const role = data.roles[step];
  const index = draft.steps.indexOf(step);
  const [tile, stroke] = TONES[step] ?? TONES.trigger;
  const targets = draft.steps.filter((other) => other !== step);
  const review = ["review_plan", "review_code", "security"].includes(step);
  return html`<section class="panel"><div class="panel-body">
    <div class="sel-head"><span class="wf-icon small" style="background: ${tile}">${icon(STEP_ICONS[step] ?? "plan", { size: 13, stroke, width: 1.6 })}</span><h2>${index + 1} · ${LABELS[step] ?? step}</h2><button class="icon-btn wide" type="button" data-remove aria-label="Remove ${LABELS[step]} from the workflow" title="Remove the step">${icon("trash", { size: 13, width: 1.6 })}</button></div>
    <p class="section-note" style="margin: 0 0 16px">Selected node · saved under workflows.${state.tab}</p>
    <div class="sel-fields">
      <div class="field"><label for="wf-agent">AGENT</label><select id="wf-agent" class="select sans full" disabled><option>${role ?? "you (the loop pauses for approval)"}</option></select></div>
      ${role
        ? html`<div class="field"><label for="wf-cli">CLI · MODEL</label><select id="wf-cli" class="select full" data-cli="${role}">${cliChoices(data, role).map((cli) => html`<option value="${cli}" ${cli === cliOf(data, role) ? "selected" : ""}>${cli.replace("/", " · ")}</option>`)}</select></div>
          <div class="field"><label for="wf-skill">SKILL READ AT START</label><input id="wf-skill" class="mono full-input" data-skill="${role}" value="${skillOf(data, role)}" title="roles/<skill>/SKILL.md"></div>`
        : ""}
      <div class="field-row">
        <div class="field"><label for="wf-back">DASHED PORT GOES TO</label><select id="wf-back" class="select sans full" data-onfail="${step}">${targets.map((other) => html`<option value="${other}" ${draft.on_fail[step] === other ? "selected" : ""}>${draft.steps.indexOf(other) + 1} · ${LABELS[other] ?? other}</option>`)}<option value="" ${draft.on_fail[step] ? "" : "selected"}>stop and ask me</option></select></div>
        ${state.tab in IMP ? html`<div class="field" style="flex: 0 0 88px"><label for="wf-loops">MAX LOOPS</label><input id="wf-loops" class="mono full-input" type="number" min="1" max="20" data-loops="${state.tab}" value="${loopsOf(data, state.tab)}"></div>` : ""}
      </div>
      ${review ? html`<label class="boxed-check"><input type="checkbox" data-flag="review.diff_only" ${flagOf(data, "review.diff_only") ? "checked" : ""}>Reads the diff only, never the whole tree</label>` : ""}
      ${role ? html`<label class="boxed-check"><input type="checkbox" data-flag="sessions.reuse" ${flagOf(data, "sessions.reuse") ? "checked" : ""}>Reuse the open CLI session, no cold start</label>` : ""}
      <div class="sel-move"><button class="btn small" type="button" data-move="-1" ${index === 0 ? "disabled" : ""}>Move up</button><button class="btn small" type="button" data-move="1" ${index === draft.steps.length - 1 ? "disabled" : ""}>Move down</button></div>
    </div>
  </div></section>`;
}

function library(data, draft) {
  return html`<section class="panel ${state.library ? "flash" : ""}" id="wf-library"><div class="panel-body">
    <h2 class="section-title">Node library</h2><p class="section-note">Add a step after the selected one, or before done</p>
    <div class="lib">${data.library.map((step) => {
      const used = draft.steps.includes(step);
      const [tile, stroke] = TONES[step] ?? TONES.trigger;
      return html`<button class="lib-item" type="button" data-add="${step}" ${used ? "disabled" : ""} title="${used ? "Already in this workflow" : `Add ${LABELS[step]}`}"><span class="wf-icon tiny" style="background: ${tile}">${icon(STEP_ICONS[step] ?? "plan", { size: 12, stroke, width: 1.7 })}</span>${LABELS[step] ?? step}<span class="end mono faint">${used ? "in use" : OUTS[step] ?? ""}</span></button>`;
    })}</div>
  </div></section>`;
}

function guardRails(data) {
  return html`<section class="panel"><div class="panel-body">
    <h2 class="section-title" style="margin-bottom: 14px">Loop guard rails</h2>
    <div class="rails">${["simple", "standard", "critical"].map((imp) => html`<div><span class="muted">${imp}</span><span class="end mono">${loopsOf(data, imp)} loops</span></div>`)}
      <div class="rule"></div>
      <label class="check"><input type="checkbox" data-flag="loop_ask_at_cap" ${flagOf(data, "loop_ask_at_cap") ? "checked" : ""}>Ask me before granting extra loops (off: park the ticket)</label>
    </div>
  </div></section>`;
}

function editor(data) {
  const name = state.tab;
  const draft = draftOf(data, name);
  const graph = layout(draft.steps, draft.on_fail);
  const runs = effective(data, draft.steps);
  const issue = problem(draft);
  const connections = graph.edges.length;
  const ghost = !draft.steps.includes("run_tests") && data.library.includes("run_tests") ? "run_tests" : "";
  return html`<div class="wf-row">
    <section class="panel wf-panel">
      <div class="panel-head"><h2>${name}</h2><span class="mono faint" style="font-size: 11px">${graph.nodes.length} nodes · ${connections} connections · max ${loopsOf(data, name) ?? "?"} loops</span>
        ${issue ? html`<span class="pill danger end">${icon("warning", { size: 12, width: 1.8 })}${issue}</span>` : html`<span class="pill ok end">${icon("check", { size: 12, width: 1.8 })}every step reachable</span>`}</div>
      ${data.warnings[name] ? html`<div class="banner" style="margin: 14px 18px 0"><span class="badge danger">blocking</span>${data.warnings[name]}</div>` : ""}
      <div class="wf-tools">
        <button class="btn small" type="button" data-library>${icon("plus", { size: 13, width: 1.9 })}Add node</button>
        <button class="btn small quiet" type="button" data-autolayout title="The layout is always automatic; this resets the zoom">Auto-layout</button>
        <button class="btn small quiet" type="button" data-dry aria-pressed="${state.dry ? "true" : "false"}">${state.dry ? "Hide dry run" : "Dry run"}</button>
        <div class="zoom"><button type="button" data-zoom="-1" aria-label="Zoom out">${icon("minus", { size: 13, width: 1.9 })}</button><span class="mono">${Math.round(state.zoom * 100)}%</span><button type="button" data-zoom="1" aria-label="Zoom in">${icon("plus", { size: 13, width: 1.9 })}</button><button type="button" data-zoom="fit" aria-label="Fit to view">${icon("fit", { size: 13, width: 1.6 })}</button></div>
      </div>
      ${state.dry ? html`<div class="wf-dry"><span class="faint">A ${name} ticket runs</span> <span class="mono">${runs.length ? runs.join(" → ") : "no step"}</span>${runs.length < draft.steps.length ? html`<span class="faint"> · skipped: ${draft.steps.filter((s) => !runs.includes(s)).join(", ")}</span>` : ""}</div>` : ""}
      <div class="wf-stage"><div class="wf-zoom" style="transform: scale(${state.zoom}); width: ${100 / state.zoom}%">${canvas(graph, {
        selected: state.selected,
        sub: (id) => (id === "trigger" ? "in_queue · /to-loop" : id === "done" ? "tasks/<project>/done/" : !data.roles[id] ? "you approve" : data.blocking.includes(data.roles[id]) ? "blocking gate" : cliOf(data, data.roles[id]).replace("/", " · ")),
        off: (id) => draft.steps.includes(id) && !runs.includes(id),
        gate: (id) => data.blocking.includes(data.roles[id]),
        ghost,
      })}</div></div>
      <div class="legend"><span><i class="solid"></i>pass forward</span><span><i class="dashed"></i>send back · counts as a loop</span><span><i class="portdot"></i>port</span></div>
    </section>
    <div class="wf-side">${selectedPanel(data, draft)}${library(data, draft)}${guardRails(data)}</div>
  </div>`;
}

export function top(data, app) {
  return configBar(app, data.projects, data.set_here, {});
}

export function view(data) {
  if (data.problem) {
    return html`<div class="page"><div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix SETTINGS.md, or run harness settings check.</div></div>`;
  }
  if (!data.names.includes(state.tab)) state.tab = data.names.includes("critical") ? "critical" : data.names[0] ?? "";
  return html`<div class="page wide-page">
    <div class="page-head">
      <div><h1>Collaboration workflow</h1><p>One step graph per workflow. A ticket enters at the trigger and only leaves through done; a dashed edge sends it back and burns a loop.</p></div>
      <div class="imp-tabs" role="tablist" aria-label="Workflow">${data.names.map((name) => html`<button type="button" role="tab" data-flow="${name}" aria-selected="${name === state.tab ? "true" : "false"}"><span style="background: ${IMP[name] ?? "#78828F"}"></span>${name}${data.loop_max[name] ? ` · ${loopsOf(data, name)}` : ""}${state.drafts[name] ? " •" : ""}</button>`)}</div>
    </div>
    <div class="wf-editor">${data.names.length ? editor(data) : html`<div class="panel"><div class="empty">No workflow in these settings yet: add one to SETTINGS.md under workflows.</div></div>`}</div>
  </div>`;
}

export function bind(root, app, data, bar) {
  if (data.problem || !data.names.length) return;
  const extra = () => {
    const found = {};
    for (const [name, draft] of Object.entries(state.drafts)) {
      if (JSON.stringify(draft) !== JSON.stringify(clone(data.workflows[name]))) found[`workflows.${name}`] = draft;
    }
    for (const [role, cli] of Object.entries(state.cli)) if (cli !== data.agents[role]) found[`agents.${role}.cli`] = cli;
    for (const [role, skill] of Object.entries(state.skill)) if (skill && skill !== data.skills[role]) found[`agents.${role}.skill`] = skill;
    for (const [name, loops] of Object.entries(state.loops)) if (loops !== data.loop_max[name] && loops >= 1) found[`loop_max.${name}`] = loops;
    for (const [key, value] of Object.entries(state.flags)) if (value !== data[FLAGS[key]]) found[key] = value;
    return found;
  };
  const { dirty } = bindScope(root, app, { setHere: data.set_here, extra, bar, clear: () => Object.assign(state, { drafts: {}, cli: {}, skill: {}, loops: {}, flags: {} }) });
  const box = root.querySelector(".wf-editor");
  const tabs = root.querySelector(".imp-tabs");
  const redraw = () => {
    mount(box, editor(data));
    tabs?.querySelectorAll("[data-flow]").forEach((t) => t.setAttribute("aria-selected", t.dataset.flow === state.tab ? "true" : "false"));
    dirty();
  };
  const edit = (change) => {
    const draft = draftOf(data, state.tab);
    change(draft);
    state.drafts[state.tab] = draft;
    redraw();
  };
  const add = (step) =>
    edit((draft) => {
      const at = draft.steps.indexOf(state.selected);
      draft.steps.splice(at < 0 ? draft.steps.length : at + 1, 0, step);
      state.selected = step;
      state.library = false;
    });
  tabs?.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-flow]");
    if (!tab) return;
    state.tab = tab.dataset.flow;
    state.selected = "";
    redraw();
  });
  box.addEventListener("click", (event) => {
    const target = event.target.closest("[data-node], [data-ghost], [data-add], [data-move], [data-remove], [data-dry], [data-zoom], [data-library], [data-autolayout]");
    if (!target) return;
    if (target.dataset.node) {
      state.selected = state.selected === target.dataset.node ? "" : target.dataset.node;
      return redraw();
    }
    if (target.dataset.ghost) return add(target.dataset.ghost);
    if (target.dataset.add) return add(target.dataset.add);
    if (target.dataset.dry !== undefined) {
      state.dry = !state.dry;
      return redraw();
    }
    if (target.dataset.library !== undefined) {
      state.library = true;
      redraw();
      return root.querySelector("#wf-library")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    if (target.dataset.autolayout !== undefined) {
      state.zoom = 1;
      return redraw();
    }
    if (target.dataset.zoom) {
      const stage = root.querySelector(".wf-stage");
      const inner = root.querySelector(".wf-canvas");
      if (target.dataset.zoom === "fit") state.zoom = Math.max(0.4, Math.min(1.5, (stage.clientWidth - 40) / inner.offsetWidth, (window.innerHeight - 260) / inner.offsetHeight));
      else state.zoom = Math.max(0.4, Math.min(1.5, Math.round((state.zoom + Number(target.dataset.zoom) * 0.1) * 10) / 10));
      return redraw();
    }
    if (target.dataset.move) {
      return edit((draft) => {
        const from = draft.steps.indexOf(state.selected);
        const to = from + Number(target.dataset.move);
        [draft.steps[from], draft.steps[to]] = [draft.steps[to], draft.steps[from]];
      });
    }
    if (target.dataset.remove !== undefined) {
      edit((draft) => {
        const gone = state.selected;
        draft.steps = draft.steps.filter((step) => step !== gone);
        draft.on_fail = Object.fromEntries(Object.entries(draft.on_fail).filter(([from, to]) => from !== gone && to !== gone));
        state.selected = "";
      });
    }
  });
  box.addEventListener("keydown", (event) => {
    const node = event.target.closest("[data-node], [data-ghost]");
    if (!node || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    node.click();
  });
  box.addEventListener("change", (event) => {
    const back = event.target.closest("[data-onfail]");
    if (back) {
      return edit((draft) => {
        if (back.value) draft.on_fail[back.dataset.onfail] = back.value;
        else delete draft.on_fail[back.dataset.onfail];
      });
    }
    const cli = event.target.closest("[data-cli]");
    if (cli) {
      state.cli[cli.dataset.cli] = cli.value;
      return redraw();
    }
    const flag = event.target.closest("[data-flag]");
    if (flag) {
      state.flags[flag.dataset.flag] = flag.checked;
      return dirty();
    }
  });
  box.addEventListener("input", (event) => {
    const skill = event.target.closest("[data-skill]");
    if (skill) state.skill[skill.dataset.skill] = skill.value.trim();
    const loops = event.target.closest("[data-loops]");
    if (loops) state.loops[loops.dataset.loops] = Number(loops.value);
    if (skill || loops) dirty();
  });
}
