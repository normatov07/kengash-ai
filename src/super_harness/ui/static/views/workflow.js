// Workflow editor (SP5 spec decision 10): one step graph per workflow, edited structurally
// (add, move, remove a step, retarget its send-back edge, pick its agent's CLI), with the
// loop caps beside it; a save writes workflows.<name> whole to SETTINGS.md.
import { LABELS, layout, svg } from "../graph.js";
import { html, mount } from "../html.js";
import { actions, bindScope, check, field, loadScoped, scopeOf, tabs } from "../scope.js";

const state = { scope: null, tab: "", selected: "", drafts: {}, cli: {}, dry: false };

export async function load(app) {
  if (state.scope !== scopeOf(app)) Object.assign(state, { scope: scopeOf(app), tab: "", selected: "", drafts: {}, cli: {}, dry: false });
  return loadScoped(app, "/api/workflows");
}

const clone = (flow) => ({ steps: [...flow.steps], on_fail: { ...flow.on_fail } });
const draftOf = (data, name) => state.drafts[name] ?? clone(data.workflows[name]);
const cliOf = (data, role) => state.cli[role] ?? data.agents[role] ?? "";

function effective(data, steps) {
  return steps.filter((step) => {
    const role = data.roles[step];
    if (role && data.off.includes(role)) return false;
    return !(step === "review_plan" && !data.plan_review);
  });
}

function selectedPanel(data, draft) {
  const step = state.selected;
  if (!draft.steps.includes(step)) {
    return html`<section class="panel"><div class="panel-body"><h2 class="section-title">Selected step</h2><p class="section-note">Click a step in the graph to pick its agent's CLI, where a failing verdict sends the ticket, or to move or remove it.</p></div></section>`;
  }
  const role = data.roles[step];
  const index = draft.steps.indexOf(step);
  const targets = draft.steps.filter((other) => other !== step);
  return html`<section class="panel"><div class="panel-body">
    <h2 class="section-title">${index + 1} · ${LABELS[step] ?? step}</h2><p class="section-note">saved under workflows.${state.tab}</p>
    <div class="fields">
      <div class="field wide"><label>AGENT</label><div class="mono muted">${role ?? "you: the loop pauses for your approval"}${role && data.off.includes(role) ? html` <span class="badge warn">off</span>` : ""}</div></div>
      ${role
        ? html`<div class="field wide ${state.cli[role] !== undefined && state.cli[role] !== data.agents[role] ? "set" : ""}"><label for="wf-cli">CLI · MODEL (agents.${role}.cli)</label><input id="wf-cli" class="mono" data-cli="${role}" value="${cliOf(data, role)}" list="wf-clis"></div>
          <div class="field wide"><label>SKILL READ AT START</label><div class="mono muted">roles/${data.skills[role] ?? "?"}/SKILL.md</div></div>`
        : ""}
      <div class="field wide"><label for="wf-back">A FAILING VERDICT SENDS IT TO</label><select id="wf-back" data-onfail="${step}"><option value="">nowhere: stop and ask me</option>${targets.map(
        (other) => html`<option value="${other}" ${draft.on_fail[step] === other ? "selected" : ""}>${draft.steps.indexOf(other) + 1} · ${LABELS[other] ?? other}</option>`,
      )}</select></div>
    </div>
    <div class="head-actions" style="justify-content: flex-start; margin-top: 14px">
      <button class="btn small" type="button" data-move="-1" ${index === 0 ? "disabled" : ""}>← Move left</button>
      <button class="btn small" type="button" data-move="1" ${index === draft.steps.length - 1 ? "disabled" : ""}>Move right →</button>
      <button class="btn small danger" type="button" data-remove>Remove step</button>
    </div>
  </div></section>`;
}

function editor(data) {
  const name = state.tab;
  const draft = draftOf(data, name);
  const graph = layout(draft.steps, draft.on_fail);
  const runs = effective(data, draft.steps);
  const changed = state.drafts[name] !== undefined && JSON.stringify(draft) !== JSON.stringify(clone(data.workflows[name]));
  const missing = data.library.filter((step) => !draft.steps.includes(step));
  return html`<div class="split">
    <section class="panel grow">
      <div class="panel-head">
        <div class="segmented" role="group" aria-label="Workflow">${data.names.map(
          (flow) => html`<button type="button" data-flow="${flow}" aria-pressed="${flow === name ? "true" : "false"}">${flow}${data.loop_max[flow] ? ` · ${data.loop_max[flow]}` : ""}${state.drafts[flow] ? " •" : ""}</button>`,
        )}</div>
        <span class="faint" style="font-size: 12px">${draft.steps.length} steps · ${Object.keys(draft.on_fail).length} send-back edges${changed ? " · unsaved" : ""}</span>
        <button class="btn ghost small end" type="button" data-dry>${state.dry ? "Hide dry run" : "Dry run"}</button>
      </div>
      ${data.warnings[name] ? html`<div class="banner" style="margin: 14px 18px 0"><span class="badge danger">blocking</span>${data.warnings[name]}</div>` : ""}
      ${state.dry ? html`<div class="panel-body dry"><span class="faint">A ${name} ticket runs</span> <span class="mono">${runs.length ? runs.join(" → ") : "no step"}</span>${runs.length < draft.steps.length ? html`<span class="faint"> (skipped: ${draft.steps.filter((s) => !runs.includes(s)).join(", ")})</span>` : ""}</div>` : ""}
      <div class="graph-wrap">${svg(graph, { selected: state.selected, sub: (id) => (id === "trigger" ? "in_queue · /to-loop" : id === "done" ? "tasks/done/" : data.roles[id] ? cliOf(data, data.roles[id]) : "you approve"), off: (id) => draft.steps.includes(id) && !runs.includes(id) })}</div>
      <div class="legend faint"><span><i class="solid"></i>pass forward</span><span><i class="dashed"></i>send back · counts as a loop</span><span>Layout is automatic; edit from the step panel.</span></div>
    </section>
    <div class="side">
      ${selectedPanel(data, draft)}
      <section class="panel"><div class="panel-body">
        <h2 class="section-title">Step library</h2><p class="section-note">${missing.length ? "Add a step after the selected one, or at the end" : "Every step is in this workflow"}</p>
        <div class="library">${missing.map((step) => html`<button class="btn small" type="button" data-add="${step}">${LABELS[step] ?? step}<span class="faint mono">${data.roles[step] ?? "pause"}</span></button>`)}</div>
      </div></section>
    </div>
  </div>
  <datalist id="wf-clis">${[...new Set(Object.values(data.agents))].map((cli) => html`<option value="${cli}"></option>`)}</datalist>`;
}

export function view(data, app) {
  if (data.problem) {
    return html`<div class="page"><div class="page-head"><div><h1>Workflow</h1></div><div class="head-stack">${tabs(app, data.projects)}</div></div><div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix SETTINGS.md, or run harness settings check.</div></div>`;
  }
  if (!data.names.includes(state.tab)) state.tab = data.names[0] ?? "";
  const on = (key) => data.set_here.includes(key);
  return html`<div class="page">
    <div class="page-head">
      <div><h1>Workflow</h1><p>One step graph per workflow. A ticket enters at the trigger and leaves through done; a dashed edge sends it back and burns a loop.</p></div>
      <div class="head-stack">${tabs(app, data.projects)}${actions(app, data.set_here)}</div>
    </div>
    <div class="wf-editor">${data.names.length ? editor(data) : html`<div class="panel"><div class="empty">No workflow in these settings.</div></div>`}</div>
    <section class="panel"><div class="panel-body">
      <h2 class="section-title">Loop guard rails</h2><p class="section-note">How many loops a ticket of each importance may take before it needs you</p>
      <div class="fields">${["simple", "standard", "critical"].map((imp) => field({ key: `loop_max.${imp}`, label: imp.toUpperCase(), value: data.loop_max[imp], setHere: on(`loop_max.${imp}`), min: 1 }))}</div>
      <div class="checks">${check({ key: "loop_ask_at_cap", label: "Ask me before granting extra loops (off: park the ticket)", value: data.loop_ask_at_cap, setHere: on("loop_ask_at_cap") })}</div>
    </div></section>
  </div>`;
}

export function bind(root, app, data) {
  if (data.problem || !data.names.length) return;
  const extra = () => {
    const found = {};
    for (const [name, draft] of Object.entries(state.drafts)) {
      if (JSON.stringify(draft) !== JSON.stringify(clone(data.workflows[name]))) found[`workflows.${name}`] = draft;
    }
    for (const [role, cli] of Object.entries(state.cli)) if (cli !== data.agents[role]) found[`agents.${role}.cli`] = cli;
    return found;
  };
  const { dirty } = bindScope(root, app, { setHere: data.set_here, extra, clear: () => Object.assign(state, { drafts: {}, cli: {} }) });
  const box = root.querySelector(".wf-editor");
  const redraw = () => {
    mount(box, editor(data));
    dirty();
  };
  const edit = (change) => {
    const draft = draftOf(data, state.tab);
    change(draft);
    state.drafts[state.tab] = draft;
    redraw();
  };
  const select = (node) => {
    if (!node?.dataset.node) return;
    state.selected = node.dataset.node;
    redraw();
  };
  box.addEventListener("click", (event) => {
    const target = event.target.closest("[data-node], [data-flow], [data-add], [data-move], [data-remove], [data-dry]");
    if (!target) return;
    if (target.dataset.node !== undefined) return select(target);
    if (target.dataset.flow) {
      state.tab = target.dataset.flow;
      state.selected = "";
      return redraw();
    }
    if (target.dataset.dry !== undefined) {
      state.dry = !state.dry;
      return redraw();
    }
    if (target.dataset.add) {
      return edit((draft) => {
        const at = draft.steps.indexOf(state.selected);
        draft.steps.splice(at < 0 ? draft.steps.length : at + 1, 0, target.dataset.add);
        state.selected = target.dataset.add;
      });
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
    if ((event.key === "Enter" || event.key === " ") && event.target.closest("[data-node]")) {
      event.preventDefault();
      select(event.target.closest("[data-node]"));
    }
  });
  box.addEventListener("change", (event) => {
    const back = event.target.closest("[data-onfail]");
    if (!back) return;
    edit((draft) => {
      if (back.value) draft.on_fail[back.dataset.onfail] = back.value;
      else delete draft.on_fail[back.dataset.onfail];
    });
  });
  box.addEventListener("input", (event) => {
    const cli = event.target.closest("[data-cli]");
    if (!cli) return;
    state.cli[cli.dataset.cli] = cli.value;
    dirty();
  });
}
