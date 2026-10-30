// Agents (SP10 spec §5.3, mock-up A): the CLI providers, then one scope's agents beside the
// selected one's editor (role, model, fallbacks, instructions, behaviour, where it runs), then
// the session limits. Edits stay as drafts per agent, so moving between agents loses none,
// until the save bar posts them; a new agent, or a copy, is created at once. Built-in agents
// keep their role and instructions; copying one is how its behaviour changes.
import { get, post } from "../api.js";
import * as c from "../controls.js";
import { tokens } from "../format.js";
import { LABELS, TONES, learnSteps } from "../graph.js";
import { html, mount } from "../html.js";
import { STEP_ICONS, icon } from "../icons.js";
import { armed, changes, scopeOf, tabs } from "../scope.js";

const NEW = "__new";
const KINDS = {
  review: ["Reviewer", "Passes or fails the changes; a fail sends the ticket back", "review"],
  edit: ["Worker", "Edits code in the ticket's worktree; kengash commits", "implement"],
  read: ["Advisor", "Reads the code and hands notes to the next step", "plan"],
};
const KIND_OPTIONS = Object.entries(KINDS).map(([kind, [label, hint]]) => [kind, label, hint]);
const FIELDS = { cli: "model", fallback: "fallbacks", on: "on/off", blocking: "blocking", bypass_permissions: "permissions", kind: "role", does: "description", skill: "skill", instructions: "instructions" };
const ROLE = /^(?=.{2,31}$)[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;
const state = { scope: null, selected: "", view: "list", drafts: {}, flows: {}, fresh: null, adding: "", query: "", texts: {} };

export async function load(app, arg) {
  if (state.scope !== scopeOf(app)) Object.assign(state, { scope: scopeOf(app), selected: "", view: "list", drafts: {}, flows: {}, fresh: null, adding: "" });
  if (arg === "new") Object.assign(state, { fresh: blank(), selected: NEW, view: "editor" });
  else if (arg) Object.assign(state, { selected: arg, view: "editor" });
  const query = `?project=${encodeURIComponent(scopeOf(app))}`;
  const [agents, flows] = await Promise.all([get(`/api/agents${query}&window=${app.window}&detect=0`), get(`/api/workflows${query}`)]);
  learnSteps(flows.kinds ?? {});
  return { ...agents, flows };
}

function blank(from = null) {
  return {
    role: from ? `${from.role}-copy`.slice(0, 31) : "",
    does: from?.does ?? "",
    kind: from && KINDS[from.kind] ? from.kind : "review",
    cli: from?.cli ?? "claude",
    fallback: from?.fallback ?? [],
    mode: from ? "own" : "starter",
    skill: from?.skill ?? "review-code",
    instructions: from?.instructions ?? "",
    blocking: false,
    bypass_permissions: false,
    workflows: [],
    after: "",
    send_back: "implement",
    from: from?.role ?? "",
    error: "",
  };
}

// --- reading an agent through its draft ------------------------------------------------
const draftOf = (role) => state.drafts[role] ?? {};
const val = (agent, key) => (key in draftOf(agent.role) ? draftOf(agent.role)[key] : agent[key]);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function setDraft(agent, key, value) {
  const draft = { ...draftOf(agent.role) };
  const original = key === "instructions" ? (agent.instructions_own ? agent.instructions : undefined) : agent[key];
  if (same(value, original)) delete draft[key];
  else draft[key] = value;
  if (Object.keys(draft).length) state.drafts[agent.role] = draft;
  else delete state.drafts[agent.role];
}

function mode(agent) {
  if (agent.builtin) return "builtin";
  const draft = draftOf(agent.role);
  if ("instructions" in draft) return "own";
  if ("skill" in draft) return "skill";
  return agent.instructions_own ? "own" : "skill";
}

const flowOf = (data, name) => state.flows[name] ?? data.flows.workflows[name];
const setHere = (data, role, key) => data.set_here.some((k) => k === `agents.${role}` || k === `agents.${role}.${key}`);

// --- pieces ------------------------------------------------------------------------------
function tile(step, kind, size = 26) {
  const [bg, stroke] = TONES[step] ?? TONES[KINDS[kind]?.[2]] ?? TONES.trigger;
  const name = STEP_ICONS[step] ?? (kind ? KINDS[kind]?.[2] : null) ?? "agents";
  return html`<span class="ag-tile" style="background: ${bg}; width: ${size}px; height: ${size}px">${icon(name, { size: Math.round(size / 2), stroke, width: 1.6 })}</span>`;
}

function badge(card) {
  if (!card.checked) return html`<span class="pstate plain"><span></span>checking…</span>`;
  if (!card.installed) return html`<span class="pstate plain">not installed</span>`;
  if (!card.signed_in) return html`<span class="pstate warn"><span></span>signed out</span>`;
  return html`<span class="pstate ok"><span></span>signed in</span>`;
}

function provider(card) {
  const ready = card.checked && card.installed && card.signed_in;
  const head = html`<div class="prov-head"><span class="mono prov-name ${ready || !card.checked ? "" : "muted"}">${card.name}</span>${badge(card)}</div>`;
  if (card.checked && !ready) {
    const why = !card.installed
      ? `The ${card.name} CLI is not on this machine's PATH.`
      : `The ${card.name} CLI${card.version ? ` ${card.version}` : ""} is installed but no session has been signed in.`;
    return html`<div class="prov off">${head}<p class="prov-why">${why}</p>${card.hint ? html`<button class="prov-btn strong" type="button" data-copy="${card.hint}" data-note="Copied: run it in a terminal, then check sign-in again.">${card.installed ? "Copy the sign-in command" : "Copy the install command"}</button><div class="prov-hint mono" title="${card.hint}">${card.hint}</div>` : ""}</div>`;
  }
  return html`<div class="prov">${head}<div class="prov-rows">
      <div><span>sessions</span><span class="end mono">${card.slots_used} / ${card.slots_total}</span></div>
      <div><span>${card.version ? "version" : "plan"}</span><span class="end mono">${card.version || "subscription"}</span></div>
      <div><span>models</span><span class="end mono">${card.models?.length ? card.models.length : "default"}</span></div>
      <div><span>spend</span><span class="end mono">${tokens(card.spend)}</span></div>
    </div></div>`;
}

function listItem(agent) {
  const [provider, model] = c.splitCli(val(agent, "cli"));
  const on = val(agent, "on");
  const current = state.selected === agent.role;
  return html`<li class="ag-item ${current ? "is-current" : ""} ${on ? "" : "is-off"}">
    <button type="button" class="ag-pick" data-pick-agent="${agent.role}" ${current ? html`aria-current="true"` : ""}>${tile(agent.step, agent.kind)}<span class="ag-pick-text"><b>${agent.role}</b><small class="mono">${provider === "shell" ? "shell" : `${provider} · ${model}`}</small></span>${state.drafts[agent.role] ? html`<span class="ag-dirty" title="Unsaved changes"></span>` : ""}</button>
    <label class="switch" title="${on ? "Switch off: the loop skips its step" : "Switch on"}"><input type="checkbox" aria-label="${agent.role} on" data-agent-on="${agent.role}" ${on ? "checked" : ""}><span></span></label>
  </li>`;
}

function list(data) {
  const query = state.query.toLowerCase();
  const shown = data.agents.filter((agent) => !query || `${agent.role} ${agent.does} ${agent.cli}`.toLowerCase().includes(query));
  const yours = shown.filter((agent) => !agent.builtin);
  const builtin = shown.filter((agent) => agent.builtin);
  const on = data.agents.filter((agent) => val(agent, "on")).length;
  return html`<div class="ag-list panel">
    <div class="ag-list-head"><h2>Agents</h2><span class="faint">${on} of ${data.agents.length} on</span><button class="btn small" type="button" data-new-agent>${icon("plus", { size: 12, width: 1.9 })}New</button></div>
    <label class="ag-search">${icon("search", { size: 13 })}<span class="sr-only">Search agents</span><input type="search" placeholder="Search agents" value="${state.query}" data-ag-search autocomplete="off"></label>
    <div class="ag-group">Yours</div>
    ${yours.length ? html`<ul class="ag-items">${yours.map(listItem)}</ul>` : html`<p class="ag-none">${query ? "None match." : html`No agent of yours yet. <button class="linkish" type="button" data-new-agent>Add one</button> or copy a built-in one.`}</p>`}
    <div class="ag-group">Built-in</div>
    ${builtin.length ? html`<ul class="ag-items">${builtin.map(listItem)}</ul>` : html`<p class="ag-none">None match.</p>`}
  </div>`;
}

function section(title, body, { note = "", locked = false } = {}) {
  return html`<section class="ag-sec" ${locked ? "data-locked" : ""}><div class="ag-sec-head"><h3>${title}</h3>${locked ? html`<span class="ag-lock">${icon("lock", { size: 12 })}fixed</span>` : ""}${note ? html`<span class="set-note inline">${note}</span>` : ""}</div>${body}</section>`;
}

function fallbackOptions(data) {
  return data.providers.flatMap((card) => [[card.name, card.name], ...(card.models ?? []).map((model) => [`${card.name}/${model}`, `${card.name} · ${model}`])]);
}

function usedIn(data, agent) {
  const step = agent.step;
  const names = data.flows.names ?? Object.keys(data.flows.workflows);
  const uses = names.filter((name) => flowOf(data, name).steps.includes(step));
  const open = names.filter((name) => !uses.includes(name));
  const adding = state.adding === agent.role;
  const target = adding ? (state.addTo && open.includes(state.addTo) ? state.addTo : open[0]) : "";
  const steps = target ? flowOf(data, target).steps : [];
  return html`<div class="ag-uses">
    ${uses.map((name) => html`<span class="ag-use ${state.flows[name] ? "is-draft" : ""}"><a href="#/workflow" data-flow-link="${name}">${name} · step ${flowOf(data, name).steps.indexOf(step) + 1}</a><button type="button" class="chip-x" data-unuse="${name}" aria-label="Take ${agent.role} out of ${name}">${icon("close", { size: 11, width: 1.8 })}</button></span>`)}
    ${uses.length ? "" : html`<span class="faint">Not in any workflow: tickets never run it.</span>`}
    ${open.length && !adding ? html`<button type="button" class="ag-use add" data-adding>${icon("plus", { size: 11, width: 1.9 })}Add to a workflow</button>` : ""}
  </div>
  ${adding ? html`<div class="ag-add-flow">
    ${c.select({ id: "ag-add-flow", value: target, options: open.map((name) => [name, name]), label: "Workflow", data: { "add-flow": "1" } })}
    ${c.select({ id: "ag-add-after", value: steps[steps.length - 1] ?? "", options: [["", "first"], ...steps.map((s, i) => [s, `after ${i + 1} · ${LABELS[s] ?? s.replace(/_/g, " ")}`])], label: "Position" })}
    <button class="btn small" type="button" data-add-flow-go>Add</button><button class="btn small quiet" type="button" data-adding-cancel>Cancel</button>
  </div>` : ""}`;
}

function instructionsSection(data, agent) {
  const caps = data.instruction_caps;
  if (agent.builtin) {
    return section("Instructions", html`<p class="ag-note">Built-in instructions are fixed so every project gets the same ${agent.role}. Copy the agent to change what it does.</p>${c.instructions({ id: "ag-text", value: agent.instructions, caps, readonly: true, label: `${agent.role} instructions` })}<button class="btn small" type="button" data-copy-agent>${icon("copy", { size: 12 })}Copy as my agent</button>`, { locked: true });
  }
  const now = mode(agent);
  const skill = val(agent, "skill") === agent.role ? "" : val(agent, "skill");
  const own = "instructions" in draftOf(agent.role) ? draftOf(agent.role).instructions : agent.instructions_own ? agent.instructions : "";
  const preview = skill === agent.skill ? agent.instructions : state.texts[skill];
  const body = now === "own"
    ? html`${c.instructions({ id: "ag-text", value: own, caps, label: `${agent.role} instructions` })}<p class="ag-note">Saved as roles/${agent.role}/SKILL.md in ${state.scope ? state.scope : "the defaults"}; kengash adds the reply format for its role.</p>`
    : html`${c.select({ id: "ag-skill", value: skill, options: data.skills.filter((s) => s.name !== agent.role).map((s) => [s.name, `${s.name}${s.source === "package" ? " · built-in" : ` · ${s.source}`}`]), label: "Skill" })}${c.instructions({ id: "ag-preview", value: preview ?? "Loading…", caps, readonly: true, label: "Skill preview" })}`;
  return section("Instructions", html`${c.segmented({ name: "ag-mode", value: now, label: "Instructions source", options: [["skill", "Use a skill"], ["own", "Write my own"]] })}${body}`, { note: setHere(data, agent.role, "skill") ? "set here" : "" });
}

function editor(data, agent) {
  const kind = val(agent, "kind");
  const cli = val(agent, "cli");
  const shell = cli === "shell";
  const draft = draftOf(agent.role);
  return html`<div class="ag-editor panel" aria-labelledby="ag-title">
    <header class="ag-head">
      <button class="icon-btn ag-back" type="button" data-back aria-label="Back to the agents">${icon("back", { size: 14, width: 1.8 })}</button>
      ${tile(agent.step, agent.kind, 34)}
      <div class="ag-title"><div class="ag-title-row"><h2 id="ag-title" tabindex="-1">${agent.role}</h2><span class="cbadge ${agent.builtin ? "builtin" : "custom"}">${agent.builtin ? "BUILT-IN" : "YOURS"}</span></div><p class="faint">${val(agent, "does") || "No description yet."}</p></div>
      ${c.toggle({ id: "ag-on", checked: val(agent, "on"), label: val(agent, "on") ? "On" : "Off", data: { field: "on" } })}
      <details class="ag-menu"><summary class="icon-btn wide" aria-label="More for ${agent.role}">${icon("more", { size: 14 })}</summary><div class="ag-menu-list" role="menu">
        ${shell ? "" : html`<button type="button" role="menuitem" data-copy-agent>${icon("copy", { size: 13 })}Copy as my agent</button>`}
        ${agent.builtin ? "" : html`<button type="button" role="menuitem" class="danger-text" data-remove-agent title="Removes the agent, its step and every workflow use of it; its skill file stays">${icon("trash", { size: 13 })}Remove agent</button>`}
      </div></details>
    </header>
    ${section("Role", html`${c.segmented({ name: "ag-kind", value: kind, label: "Role", disabled: agent.builtin, options: agent.builtin && !KINDS[kind] ? [[kind, "Check", "Runs project.test_cmd; passes when it exits 0"]] : KIND_OPTIONS })}${agent.builtin ? "" : html`<div class="field ag-does"><label for="ag-does">Description</label><input id="ag-does" class="text-input" maxlength="200" value="${val(agent, "does")}" data-field="does" placeholder="One line: what it checks or does"></div>`}${!agent.builtin && kind !== "review" && agent.kind === "review" ? html`<p class="ag-note warn-text">Only reviewers send tickets back: saving drops this step's send-back edges.</p>` : ""}`, { locked: agent.builtin })}
    ${section("Model", html`${c.modelPicker({ id: "ag-model", cards: data.providers, value: cli, allowShell: shell })}${shell ? html`<p class="ag-note">Runs project.test_cmd with no model.</p>` : html`<div class="ag-field-label">Fallbacks, tried in order when the CLI is out or rate limited</div>${c.chipList({ id: "ag-fallback", items: val(agent, "fallback"), options: fallbackOptions(data), label: "Fallbacks", empty: "no fallback" })}`}`, { note: setHere(data, agent.role, "cli") ? "set here" : "" })}
    ${instructionsSection(data, agent)}
    ${section("Behaviour", html`<div class="ag-toggles">${c.toggle({ id: "ag-blocking", checked: val(agent, "blocking"), label: "Blocking gate", hint: "A ticket stops here until this agent passes, and fails if it is switched off.", data: { field: "blocking" } })}${shell ? "" : c.toggle({ id: "ag-bypass", checked: val(agent, "bypass_permissions"), label: "Skip permission prompts", hint: "Adds the CLI's bypass flag: it edits and runs commands without asking.", data: { field: "bypass_permissions" } })}</div>`)}
    ${section("Used in", usedIn(data, agent))}
    <footer class="ag-foot"><span class="faint">${tokens(agent.tokens)} tokens ${data.window ?? ""}</span>${Object.keys(draft).length ? html`<span class="ag-foot-note">Unsaved: ${Object.keys(draft).map((k) => FIELDS[k]).join(", ")}</span>` : ""}</footer>
  </div>`;
}

function common(data, names) {
  const lists = names.map((name) => flowOf(data, name).steps);
  return lists.length ? lists[0].filter((step) => lists.every((list) => list.includes(step))) : [];
}

function newEditor(data) {
  const f = state.fresh;
  const names = data.flows.names ?? Object.keys(data.flows.workflows);
  const steps = common(data, f.workflows);
  return html`<form class="ag-editor panel" aria-labelledby="ag-title" data-new-form novalidate>
    <header class="ag-head">
      <button class="icon-btn ag-back" type="button" data-back aria-label="Back to the agents">${icon("back", { size: 14, width: 1.8 })}</button>
      ${tile(null, f.kind, 34)}
      <div class="ag-title"><div class="ag-title-row"><h2 id="ag-title" tabindex="-1">${f.from ? `Copy of ${f.from}` : "New agent"}</h2><span class="cbadge custom">YOURS</span></div><p class="faint">Written to ${state.scope ? `${state.scope}'s` : "the defaults'"} SETTINGS.md.</p></div>
    </header>
    ${section("Name", html`<div class="ag-name-row"><div class="field"><label for="ag-new-role">Role name</label><input id="ag-new-role" class="text-input mono" maxlength="31" value="${f.role}" data-new="role" placeholder="perf-reviewer" autocomplete="off" spellcheck="false" aria-describedby="ag-new-role-hint"><small id="ag-new-role-hint" class="faint">lowercase words joined by hyphens</small></div>
      <div class="field"><label for="ag-new-does">Description</label><input id="ag-new-does" class="text-input" maxlength="200" value="${f.does}" data-new="does" placeholder="Flag N+1 queries and hot loops in the changed code."></div></div>`)}
    ${section("Role", c.segmented({ name: "ag-new-kind", value: f.kind, label: "Role", options: KIND_OPTIONS }))}
    ${section("Model", html`${c.modelPicker({ id: "ag-model", cards: data.providers, value: f.cli })}<div class="ag-field-label">Fallbacks, tried in order</div>${c.chipList({ id: "ag-fallback", items: f.fallback, options: fallbackOptions(data), label: "Fallbacks", empty: "no fallback" })}`)}
    ${section("Instructions", html`${c.segmented({ name: "ag-new-mode", value: f.mode, label: "Instructions source", options: [["starter", "Starter"], ["skill", "Use a skill"], ["own", "Write my own"]] })}
      ${f.mode === "starter" ? html`<p class="ag-note">kengash writes a starter for this role in roles/${f.role || "<name>"}/SKILL.md; edit it here afterwards.</p>` : ""}
      ${f.mode === "skill" ? html`${c.select({ id: "ag-skill", value: f.skill, options: data.skills.map((s) => [s.name, `${s.name}${s.source === "package" ? " · built-in" : ` · ${s.source}`}`]), label: "Skill" })}${c.instructions({ id: "ag-preview", value: state.texts[f.skill] ?? "Loading…", caps: data.instruction_caps, readonly: true, label: "Skill preview" })}` : ""}
      ${f.mode === "own" ? c.instructions({ id: "ag-text", value: f.instructions, caps: data.instruction_caps, label: "Instructions" }) : ""}`)}
    ${section("Behaviour", html`<div class="ag-toggles">${c.toggle({ id: "ag-blocking", checked: f.blocking, label: "Blocking gate", hint: "A ticket stops here until this agent passes.", data: { new: "blocking" } })}${c.toggle({ id: "ag-bypass", checked: f.bypass_permissions, label: "Skip permission prompts", hint: "Adds the CLI's bypass flag: it edits and runs commands without asking.", data: { new: "bypass_permissions" } })}</div>`)}
    ${section("Add its step to", html`<div class="ag-flows">${names.map((name) => html`<label class="check"><input type="checkbox" data-new-flow="${name}" ${f.workflows.includes(name) ? "checked" : ""}>${name}</label>`)}</div>
      ${f.workflows.length ? html`<div class="ag-name-row"><div class="field"><label for="ag-new-after">Position</label>${c.select({ id: "ag-new-after", value: f.after, options: [["", "last, before approval"], ...steps.map((s) => [s, `after ${LABELS[s] ?? s.replace(/_/g, " ")}`])], data: { new: "after" } })}</div>
      ${f.kind === "review" ? html`<div class="field"><label for="ag-new-back">A fail sends the ticket to</label>${c.select({ id: "ag-new-back", value: f.send_back, options: [["", "stop and ask me"], ...steps.map((s) => [s, LABELS[s] ?? s.replace(/_/g, " ")])], data: { new: "send_back" } })}</div>` : ""}</div>` : html`<p class="ag-note">Leave every box clear to add it to workflows later.</p>`}`)}
    <footer class="ag-foot"><span class="danger-text" role="alert">${f.error}</span><button class="btn quiet" type="button" data-back>Cancel</button><button class="btn accent" type="submit">${f.from ? "Create the copy" : "Create agent"}</button></footer>
  </form>`;
}

function limits(data) {
  const field = (key, label, value, extra = "") => html`<div class="field ${data.set_here.includes(key) ? "set" : ""}"><label for="lim-${key}">${label}</label><input id="lim-${key}" class="mono lim" type="number" min="${key === "tokens.per_ticket_max" ? 1000 : 0}" ${extra} data-key="${key}" data-kind="number" data-initial="${value}" value="${value}"></div>`;
  return html`<section class="panel ag-limits" data-limits><div class="panel-body">
    <h2 class="section-title">Parallelism and limits</h2><p class="section-note">How many CLI sessions run at once, and how many tokens a ticket may spend before it asks you.</p>
    <div class="lim-fields">${field("sessions.max", "Concurrent CLI sessions", data.sessions_max)}${field("tokens.per_ticket_max", "Token ceiling per ticket", data.tokens_per_ticket, 'step="1000"')}${Object.entries(data.per_provider).map(([name, total]) => field(`sessions.per_provider.${name}`, `${name} sessions`, total))}</div>
    <div class="checks"><label class="check"><input type="checkbox" data-key="fallback_on_rate_limit" data-kind="bool" data-initial="${data.fallback_on_rate_limit ? "1" : ""}" ${data.fallback_on_rate_limit ? "checked" : ""}>Fall back to the next CLI when one is rate limited</label></div>
  </div></section>`;
}

function split(data) {
  const agent = data.agents.find((one) => one.role === state.selected);
  const pane = state.selected === NEW && state.fresh ? newEditor(data) : agent ? editor(data, agent) : html`<div class="ag-editor panel ag-empty"><div class="empty">Pick an agent to see and change its role, model, instructions and where it runs, or add one of your own.</div></div>`;
  return html`${list(data)}${pane}`;
}

export function top(data, app) {
  return html`${tabs(app, data.projects ?? [])}<span class="note">${scopeOf(app) ? "inherits the defaults unless set here" : "editing the defaults every new project copies"}</span><span class="spacer"></span><button class="btn accent sans-btn" type="button" data-new-agent ${data.problem ? "disabled" : ""}>${icon("plus", { size: 13, width: 1.9 })}New agent</button>`;
}

export function view(data, app) {
  if (data.problem) {
    return html`<div class="page"><div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix SETTINGS.md, or run kengash settings check.</div></div>`;
  }
  if (state.selected && state.selected !== NEW && !data.agents.some((agent) => agent.role === state.selected)) state.selected = "";
  data.window = app.window === "all" ? "all time" : app.window === "7d" ? "in 7 days" : "today";
  return html`<div class="page wide-page agents-page">
    <div><h1 class="h1">Agents</h1><p class="lede">Each agent is a role bound to one CLI and model. Built-in agents keep their role and instructions; add your own, or copy one, to change what runs.</p></div>
    <section>
      <div class="sec-head"><h2>CLI providers</h2><span class="faint">detected on this machine · spend ${data.window}</span><button class="btn small quiet end" type="button" data-redetect>Check sign-in again</button></div>
      <div class="prov-grid">${data.providers.map(provider)}</div>
    </section>
    <div class="ag-split" data-view="${state.view}">${split(data)}</div>
    ${limits(data)}
    <div class="save-bar" data-save-bar hidden><span data-save-summary></span><button class="btn quiet" type="button" data-discard>Discard</button><button class="btn accent" type="button" data-save>Save</button></div>
  </div>`;
}

// --- behaviour -----------------------------------------------------------------------------
export function bind(root, app, data, bar) {
  if (data.problem) return;
  const box = root.querySelector(".ag-split");
  const limitsBox = root.querySelector("[data-limits]");
  const saveBar = root.querySelector("[data-save-bar]");
  const agentOf = (role) => data.agents.find((agent) => agent.role === role);
  const settingsChanges = () => {
    const found = changes(limitsBox);
    for (const [name, flow] of Object.entries(state.flows)) if (!same(flow, data.flows.workflows[name])) found[`workflows.${name}`] = flow;
    return found;
  };
  const sync = () => {
    const roles = Object.keys(state.drafts);
    const settings = Object.keys(settingsChanges());
    const parts = [...roles.map((role) => `${role} (${Object.keys(state.drafts[role]).map((k) => FIELDS[k]).join(", ")})`), ...(settings.length ? [settings.some((k) => k.startsWith("workflows.")) ? "workflows" : "limits"] : [])];
    saveBar.hidden = !parts.length;
    root.querySelector("[data-save-summary]").textContent = parts.length ? `Unsaved: ${parts.join("; ")}` : "";
    app.dirty = parts.length > 0 || Boolean(state.fresh);
  };
  const go = (hash) => history.replaceState(null, "", hash);
  const redraw = () => {
    mount(box, split(data));
    box.dataset.view = state.view;
    wire();
    sync();
  };
  const fetchText = async (name) => {
    if (!name || name in state.texts) return;
    try {
      state.texts[name] = (await get(`/api/skills/${encodeURIComponent(name)}?project=${encodeURIComponent(scopeOf(app))}`)).text;
    } catch (error) {
      state.texts[name] = `Could not read ${name}: ${error.message}`;
    }
    redraw();
  };

  // controls that bind per render: the model picker, fallback chips, instructions
  function wire() {
    const agent = agentOf(state.selected);
    const fresh = state.selected === NEW ? state.fresh : null;
    const picker = box.querySelector("[data-model-picker]");
    if (picker && (agent || fresh)) {
      c.bindModelPicker(picker, data.providers, (value) => {
        if (fresh) fresh.cli = value;
        else setDraft(agent, "cli", value);
        sync();
      });
    }
    const chips = box.querySelector("[data-chip-list]");
    if (chips && (agent || fresh)) {
      c.bindChipList(chips, (items, moved) => {
        if (fresh) fresh.fallback = items;
        else setDraft(agent, "fallback", items);
        redraw();
        if (moved) box.querySelector(`.chip-item[data-value="${CSS.escape(moved)}"]`)?.focus();
      });
    }
    const text = box.querySelector("#ag-text")?.closest(".instructions");
    if (text) {
      c.bindInstructions(text, data.instruction_caps, (value) => {
        if (fresh) fresh.instructions = value;
        else setDraft(agent, "instructions", value);
        sync();
      });
    }
    if (agent && mode(agent) === "skill") fetchText(val(agent, "skill"));
    if (fresh && fresh.mode === "skill") fetchText(fresh.skill);
  }

  const select = (role) => {
    state.selected = role;
    state.view = "editor";
    state.adding = "";
    if (role !== NEW) state.fresh = null;
    go(`#/agents/${encodeURIComponent(role === NEW ? "new" : role)}`);
    redraw();
    box.querySelector(".ag-editor h2")?.focus?.();
  };
  const startNew = (from = null) => {
    state.fresh = blank(from);
    select(NEW);
    box.querySelector("#ag-new-role")?.focus();
  };

  box.addEventListener("click", async (event) => {
    const t = event.target;
    const pick = t.closest("[data-pick-agent]");
    if (pick) return select(pick.dataset.pickAgent);
    if (t.closest("[data-new-agent]")) return startNew();
    if (t.closest("[data-back]")) {
      state.view = "list";
      if (state.selected === NEW) Object.assign(state, { fresh: null, selected: "" });
      go("#/agents");
      return redraw();
    }
    const agent = agentOf(state.selected);
    if (t.closest("[data-copy-agent]") && agent) return startNew({ ...agent, cli: val(agent, "cli"), fallback: val(agent, "fallback") });
    const remove = t.closest("[data-remove-agent]");
    if (remove && agent) {
      if (!armed(remove, "Click again to remove")) return;
      delete state.drafts[agent.role];
      state.selected = "";
      go("#/agents");
      const done = await app.post(`/api/agents/${encodeURIComponent(agent.role)}/remove`, { project: scopeOf(app) });
      if (done) app.toast(`Removed ${agent.role}, its step and its workflow uses; its skill file stays.`);
      return;
    }
    if (t.closest("[data-adding]") && agent) {
      state.adding = agent.role;
      return redraw();
    }
    if (t.closest("[data-adding-cancel]")) {
      state.adding = "";
      return redraw();
    }
    if (t.closest("[data-add-flow-go]") && agent) {
      const name = box.querySelector("#ag-add-flow").value;
      const after = box.querySelector("#ag-add-after").value;
      const flow = flowOf(data, name);
      const steps = [...flow.steps];
      steps.splice(after ? steps.indexOf(after) + 1 : 0, 0, agent.step);
      const on_fail = { ...flow.on_fail };
      if (val(agent, "kind") === "review" && steps.includes("implement") && steps.indexOf("implement") < steps.indexOf(agent.step)) on_fail[agent.step] = "implement";
      state.flows[name] = { steps, on_fail };
      state.adding = "";
      return redraw();
    }
    const unuse = t.closest("[data-unuse]");
    if (unuse && agent) {
      const name = unuse.dataset.unuse;
      const flow = flowOf(data, name);
      state.flows[name] = { steps: flow.steps.filter((s) => s !== agent.step), on_fail: Object.fromEntries(Object.entries(flow.on_fail).filter(([a, b]) => a !== agent.step && b !== agent.step)) };
      return redraw();
    }
  });

  box.addEventListener("change", (event) => {
    const t = event.target;
    if (t.dataset.agentOn) {
      setDraft(agentOf(t.dataset.agentOn), "on", t.checked);
      return redraw();
    }
    if (t.id === "ag-add-flow") {
      state.addTo = t.value;
      return redraw();
    }
    const fresh = state.selected === NEW ? state.fresh : null;
    if (fresh) {
      if (t.name === "ag-new-kind") fresh.kind = t.value;
      else if (t.name === "ag-new-mode") fresh.mode = t.value;
      else if (t.id === "ag-skill") fresh.skill = t.value;
      else if (t.dataset.newFlow) fresh.workflows = [...box.querySelectorAll("[data-new-flow]:checked")].map((b) => b.dataset.newFlow);
      else if (t.dataset.new) fresh[t.dataset.new] = t.type === "checkbox" ? t.checked : t.value;
      else return;
      return redraw();
    }
    const agent = agentOf(state.selected);
    if (!agent) return;
    if (t.dataset.field === "on" || t.dataset.field === "blocking" || t.dataset.field === "bypass_permissions") setDraft(agent, t.dataset.field, t.checked);
    else if (t.name === "ag-kind") setDraft(agent, "kind", t.value);
    else if (t.id === "ag-skill") setDraft(agent, "skill", t.value);
    else if (t.name === "ag-mode") {
      const draft = { ...draftOf(agent.role) };
      if (t.value === "own") {
        const from = mode(agent) === "skill" ? (val(agent, "skill") === agent.skill ? agent.instructions : state.texts[val(agent, "skill")]) : agent.instructions;
        delete draft.skill;
        draft.instructions = agent.instructions_own ? agent.instructions : from ?? "";
        state.drafts[agent.role] = draft;
        if (same(draft.instructions, agent.instructions) && agent.instructions_own) delete state.drafts[agent.role].instructions;
      } else {
        delete draft.instructions;
        const fallback = { review: "review-code", edit: "implement", read: "plan" }[val(agent, "kind")] ?? "review-code";
        draft.skill = agent.skill === agent.role ? fallback : agent.skill;
        state.drafts[agent.role] = draft;
        if (draft.skill === agent.skill) delete state.drafts[agent.role].skill;
      }
      if (!Object.keys(state.drafts[agent.role]).length) delete state.drafts[agent.role];
    } else return;
    redraw();
  });

  box.addEventListener("input", (event) => {
    const t = event.target;
    if (t.matches("[data-ag-search]")) {
      state.query = t.value;
      const at = t.selectionStart;
      redraw();
      const search = box.querySelector("[data-ag-search]");
      search.focus();
      search.setSelectionRange(at, at);
      return;
    }
    if (state.selected === NEW && state.fresh && (t.dataset.new === "role" || t.dataset.new === "does")) {
      state.fresh[t.dataset.new] = t.value;
      return;
    }
    if (t.dataset.field === "does") {
      setDraft(agentOf(state.selected), "does", t.value.trim());
      sync();
    }
  });

  box.addEventListener("submit", async (event) => {
    event.preventDefault();
    const f = state.fresh;
    const problem = !ROLE.test(f.role) ? "Name it with lowercase words joined by hyphens, 2 to 31 characters." : data.agents.some((a) => a.role === f.role) ? `An agent called ${f.role} exists.` : !f.does.trim() ? "Say in one line what it does." : f.mode === "own" && !f.instructions.trim() ? "Write its instructions, or pick the starter." : "";
    if (problem) {
      f.error = problem;
      return redraw();
    }
    const body = { project: scopeOf(app), role: f.role, kind: f.kind, does: f.does.trim(), cli: f.cli, fallback: f.fallback, workflows: f.workflows, after: f.workflows.length && f.after ? f.after : null, send_back: f.kind === "review" && f.workflows.length && f.send_back ? f.send_back : null };
    if (f.mode === "skill") body.skill = f.skill;
    if (f.mode === "own") body.instructions = f.instructions;
    const submit = box.querySelector("[type=submit]");
    submit.disabled = true;
    try {
      await post("/api/agents", body);
      if (f.blocking || f.bypass_permissions) await post(`/api/agents/${encodeURIComponent(f.role)}`, { project: scopeOf(app), patch: { blocking: f.blocking, bypass_permissions: f.bypass_permissions } });
      app.toast(`Added ${f.role}${f.workflows.length ? ` to ${f.workflows.join(", ")}` : ""}.`);
      Object.assign(state, { fresh: null, selected: f.role, view: "editor" });
      go(`#/agents/${encodeURIComponent(f.role)}`);
      app.dirty = false;
      await app.refresh();
    } catch (failure) {
      f.error = failure.message;
      redraw();
    }
  });

  limitsBox.addEventListener("input", sync);
  limitsBox.addEventListener("change", sync);
  root.querySelector("[data-discard]").addEventListener("click", () => {
    Object.assign(state, { drafts: {}, flows: {}, adding: "" });
    app.dirty = false;
    app.refresh();
  });
  root.querySelector("[data-save]").addEventListener("click", async (event) => {
    event.target.disabled = true;
    const scope = scopeOf(app);
    const failed = [];
    for (const [role, patch] of Object.entries(state.drafts)) {
      try {
        await post(`/api/agents/${encodeURIComponent(role)}`, { project: scope, patch });
        delete state.drafts[role];
      } catch (error) {
        failed.push(`${role}: ${error.message}`);
      }
    }
    const found = settingsChanges();
    if (Object.keys(found).length) {
      try {
        await post(`/api/settings?project=${encodeURIComponent(scope)}`, { changes: found });
        state.flows = {};
      } catch (error) {
        failed.push(error.message);
      }
    }
    app.dirty = false;
    if (failed.length) app.toast(`Not saved: ${failed.join("; ")}`, true);
    else app.toast("Saved to SETTINGS.md.");
    await app.refresh();
  });

  const switchTo = (scope) => {
    app.scope = scope;
    app.dirty = false;
    app.refresh();
  };
  bar?.querySelectorAll("[data-scope]").forEach((button) => button.addEventListener("click", () => switchTo(button.dataset.scope)));
  bar?.querySelector("[data-new-agent]")?.addEventListener("click", () => startNew());

  const grid = root.querySelector(".prov-grid");
  const fill = async (refresh) => {
    try {
      const fresh = await get(`/api/agents?project=${encodeURIComponent(scopeOf(app))}&window=${app.window}${refresh ? "&refresh=1" : ""}`);
      data.providers = fresh.providers;
      if (grid.isConnected) mount(grid, data.providers.map(provider));
      if (box.isConnected && !box.contains(document.activeElement)) redraw();
    } catch (error) {
      app.toast(error.message, true);
    }
  };
  if (data.providers.some((card) => !card.checked)) fill(false);
  const again = root.querySelector("[data-redetect]");
  again.addEventListener("click", async () => {
    again.disabled = true;
    again.textContent = "Checking…";
    mount(grid, data.providers.map((card) => provider({ ...card, checked: false })));
    await fill(true);
    if (again.isConnected) {
      again.disabled = false;
      again.textContent = "Check sign-in again";
    }
  });
  wire();
  sync();
}
