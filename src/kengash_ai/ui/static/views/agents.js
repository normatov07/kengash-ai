// Agents and providers (canvas board Agents): which CLIs this machine has and their sign-in,
// the role roster (on or off, CLI and model, skill, where it is used, tokens) with a row
// editor, session and token limits, and importance routing. Provider detection runs the
// CLIs' sign-in checks, so the page renders first and the cards fill in after. "New agent"
// (SP6) adds a user's role and its step through `kengash agent new`'s ops call.
import { get, post } from "../api.js";
import { tokens } from "../format.js";
import { LABELS } from "../graph.js";
import { html, mount } from "../html.js";
import { icon } from "../icons.js";
import { armed, bindScope, loadScoped, scopeOf, tabs } from "../scope.js";

const BLURBS = {
  planner: "writes the ticket's implementation plan",
  "plan-reviewer": "second opinion on the plan before any code is written",
  implementer: "writes the code in a worktree of its own",
  "code-reviewer": "reviews the ticket's changes, the diff only by default",
  "security-reviewer": "secrets, authz and dependency surface",
  "test-runner": "runs project.test_cmd, no model call",
  "doc-writer": "keeps docs in step with the code",
  compactor: "keeps MEMORY.md under its cap",
};
const IMP = { critical: "#EF7A72", standard: "#D8B24C", simple: "#68A4E0" };
const SHORT = { plan: "plan", review_plan: "review plan", implement: "implement", review_code: "review", security: "security", run_tests: "tests", docs: "docs", approve: "approve" };
const COMMON_CLIS = ["claude", "claude/opus", "claude/sonnet", "claude/haiku", "codex", "antigravity", "shell"];
const KINDS = [
  ["review", "Reviewer", "Reads the changes; a fail sends the ticket back and burns a loop"],
  ["edit", "Worker", "Edits code in the ticket's worktree; kengash commits"],
  ["read", "Advisor", "Reads only and hands notes to the next step"],
];
const state = { open: new Set(), creating: false };
const label = (step) => SHORT[step] ?? (LABELS[step] ?? step.replace(/_/g, " ")).toLowerCase();

export async function load(app, arg) {
  state.creating = arg === "new"; // #/agents/new, from Settings' status flow
  return loadScoped(app, "/api/agents", `&window=${app.window}&detect=0`);
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
    return html`<div class="prov off">${head}<p class="prov-why">${why}</p>${card.hint ? html`<button class="prov-btn strong" type="button" data-copy="${card.hint}" data-note="Copied: run it in a terminal, then check sign-in again.">${card.installed ? "Sign in" : "Install"}</button><div class="prov-hint mono" title="${card.hint}">${card.hint}</div>` : ""}</div>`;
  }
  return html`<div class="prov">${head}<div class="prov-rows">
      <div><span>sessions</span><span class="end mono">${card.slots_used} / ${card.slots_total}</span></div>
      <div><span>${card.version ? "version" : "plan"}</span><span class="end mono">${card.version || "subscription"}</span></div>
      <div><span>spend</span><span class="end mono">${tokens(card.spend)}</span></div>
    </div></div>`;
}

function usedIn(item) {
  if (!item.used_in.length) return html`<span class="faint" style="font-size: 11px">not in any flow</span>`;
  const all = ["critical", "standard", "simple"].every((imp) => item.used_in.includes(imp));
  return html`<span class="used">${item.used_in.map((name) => html`<span style="background: ${IMP[name] ?? "#78828F"}"></span>`)}<em>${all ? "all levels" : item.used_in.join(", ")}</em></span>`;
}

function role(item, setHere) {
  const set = (key) => setHere.includes(`agents.${item.role}.${key}`);
  const open = state.open.has(item.role);
  return html`<div class="roster-item ${item.on ? "" : "is-off"} ${item.blocking ? "is-blocking" : ""}">
    <div class="trow roster-row">
      <div class="r-on"><label class="switch big" title="${item.on ? "Switch off: the loop skips its step" : "Switch on"}"><input type="checkbox" aria-label="${item.role} on" data-key="agents.${item.role}.on" data-kind="bool" data-initial="${item.on ? "1" : ""}" ${item.on ? "checked" : ""}><span></span></label></div>
      <div class="r-name"><div><b>${item.role}</b>${item.custom ? html`<span class="cbadge custom" title="Your agent: runs the step ${item.step ?? ""}">CUSTOM</span>` : ""}${item.blocking ? html`<span class="cbadge" style="background: #2A2320; color: #D8B24C">BLOCKING</span>` : ""}${set("on") || set("cli") || set("skill") ? html`<span class="set-note inline">set here</span>` : ""}</div><div class="faint ellipsis" title="${item.custom ? item.does : ""}">${item.custom ? item.does || `runs ${label(item.step ?? "")}` : BLURBS[item.role] ?? ""}</div></div>
      <div class="r-cli mono muted ellipsis" title="${item.cli}">${item.provider} · ${item.model}</div>
      <div class="r-skill mono faint ellipsis" title="${item.skill_file || "missing"}">${item.skill_file ? `roles/${item.skill}/SKILL.md` : html`<span class="danger-text">missing: ${item.skill}</span>`}</div>
      <div class="r-used">${usedIn(item)}</div>
      <div class="r-tokens mono muted">${tokens(item.tokens)}</div>
      <div class="r-edit"><button class="icon-btn wide" type="button" data-edit="${item.role}" aria-expanded="${open ? "true" : "false"}" aria-label="Edit ${item.role}" title="Edit ${item.role}">${icon("pencil", { size: 13, width: 1.5 })}</button></div>
    </div>
    <div class="roster-editor" ${open ? "" : "hidden"}>
      <div class="field ${set("cli") ? "set" : ""}"><label for="cli-${item.role}">CLI · MODEL</label><input id="cli-${item.role}" class="mono" list="agent-clis" data-key="agents.${item.role}.cli" data-kind="text" data-initial="${item.cli}" value="${item.cli}"></div>
      <div class="field ${set("skill") ? "set" : ""}"><label for="skill-${item.role}">SKILL</label><input id="skill-${item.role}" class="mono" data-key="agents.${item.role}.skill" data-kind="text" data-initial="${item.skill}" value="${item.skill}"></div>
      <div class="field wide ${set("fallback") ? "set" : ""}"><label for="fb-${item.role}">FALLBACK CLIS (COMMA-SEPARATED)</label><input id="fb-${item.role}" class="mono" data-key="agents.${item.role}.fallback" data-kind="list" data-initial="${item.fallback.join(", ")}" value="${item.fallback.join(", ")}" placeholder="claude/sonnet, antigravity"></div>
      <label class="check"><input type="checkbox" data-key="agents.${item.role}.blocking" data-kind="bool" data-initial="${item.blocking ? "1" : ""}" ${item.blocking ? "checked" : ""}>Blocking: a ticket stops here until this role passes</label>
      ${item.custom ? html`<button class="btn small danger end" type="button" data-remove-agent="${item.role}" title="Removes the agent, its step and every workflow use of it; its skill file stays">Remove agent</button>` : ""}
    </div>
  </div>`;
}

function routing(data) {
  const names = Object.keys(data.routing);
  return names.map((name, i) => {
    const steps = data.routing[name];
    const before = i ? data.routing[names[i - 1]] : [];
    const added = steps.filter((s) => !before.includes(s));
    let text = i === 0 || !added.length ? steps.map(label).join(" → ") : `+ ${added.map(label).join(", ")}`;
    if (name === "critical" && data.loop_max?.[name]) text += `, ${data.loop_max[name]} loops`; // as the canvas shows it
    return html`<div class="route ${name === "critical" ? "is-crit" : ""}"><span class="bar" style="background: ${IMP[name] ?? "#78828F"}"></span><span>${name}</span><span class="end mono muted">${text}</span></div>`;
  });
}

const providersGrid = (data) => data.providers.map(provider);

// Steps every chosen workflow has, in the first one's order: where the new step can go.
function common(data, flows) {
  const lists = flows.map((name) => data.routing[name] ?? []);
  return lists.length ? lists[0].filter((step) => lists.every((list) => list.includes(step))) : [];
}

function newAgentDialog(data, app) {
  const flows = Object.keys(data.routing);
  const scope = scopeOf(app);
  return html`<dialog class="na-dialog" id="new-agent" aria-labelledby="na-title"><form class="na-form" method="dialog" novalidate>
    <div class="na-head"><h2 id="na-title">New agent</h2><p class="faint">A role, the step it runs and where that step sits. Written to ${scope ? `${scope}'s` : "the defaults'"} SETTINGS.md, with a starter skill you can edit.</p></div>
    <div class="na-body">
      <div class="na-row">
        <div class="field"><label for="na-role">ROLE NAME</label><input id="na-role" name="role" required maxlength="31" pattern="[a-z][a-z0-9]*(-[a-z0-9]+)*" placeholder="perf-reviewer" autocomplete="off" spellcheck="false"></div>
        <div class="field"><label for="na-cli">CLI · MODEL</label><input id="na-cli" name="cli" class="mono" list="agent-clis" value="claude" autocomplete="off"></div>
      </div>
      <div class="field"><label for="na-does">WHAT ITS STEP DOES</label><input id="na-does" name="does" class="sans-input" required maxlength="200" placeholder="Flag N+1 queries and hot loops in the changed code."></div>
      <fieldset class="na-kinds"><legend>KIND</legend>${KINDS.map(
        ([value, title, note], i) => html`<label class="na-kind"><input type="radio" name="kind" value="${value}" ${i === 0 ? "checked" : ""}><b>${title}</b><span>${note}</span></label>`,
      )}</fieldset>
      <fieldset class="na-flows"><legend>ADD ITS STEP TO</legend>${flows.map(
        (name) => html`<label class="check"><input type="checkbox" name="workflows" value="${name}" ${name === "critical" ? "checked" : ""}><span class="bar" style="background: ${IMP[name] ?? "#78828F"}"></span>${name}</label>`,
      )}</fieldset>
      <div class="na-row">
        <div class="field"><label for="na-after">AFTER STEP</label><select id="na-after" name="after"></select></div>
        <div class="field" data-review-only><label for="na-back">A FAIL SENDS THE TICKET TO</label><select id="na-back" name="send_back"></select></div>
      </div>
    </div>
    <div class="na-foot"><span class="na-error danger-text" role="alert"></span><button class="btn quiet" type="button" data-na-cancel>Cancel</button><button class="btn accent sans-btn" type="submit">Add agent</button></div>
  </form></dialog>`;
}

export function top(data, app) {
  return html`${tabs(app, data.projects)}<span class="note">${scopeOf(app) ? "inherits defaults unless overridden" : "editing the defaults copied into every new project"}</span><span class="spacer"></span><button class="btn sans-btn new-agent" type="button" data-new-agent ${data.problem ? "disabled" : ""}>${icon("plus", { size: 13, width: 1.9 })}New agent</button><button class="btn quiet" type="button" data-discard disabled>Discard</button><button class="btn accent sans-btn" type="button" data-save disabled>Save to SETTINGS.md</button>`;
}

export function view(data, app) {
  if (data.problem) {
    return html`<div class="page"><div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix SETTINGS.md, or run kengash settings check.</div></div>`;
  }
  const on = data.roster.filter((item) => item.on).length;
  const clis = [...new Set([...data.roster.map((item) => item.cli), ...COMMON_CLIS])];
  const field = (key, label, value, extra = "") => html`<div class="field ${data.set_here.includes(key) ? "set" : ""}" style="flex: 0 0 auto"><label for="lim-${key}">${label}</label><input id="lim-${key}" class="mono lim" type="number" min="${key === "tokens.per_ticket_max" ? 1000 : 0}" ${extra} data-key="${key}" data-kind="number" data-initial="${value}" value="${value}"></div>`;
  return html`<div class="page wide-page agents-page">
    <div><h1 class="h1">Agents</h1><p class="lede">Every agent is a role bound to one CLI and one model. Switch a role off and the loop skips its step.</p></div>
    <section>
      <div class="sec-head"><h2>CLI providers</h2><span class="faint" style="font-size: 12px">detected on this machine · sessions are reused, never restarted per step · spend ${app.window === "all" ? "all time" : app.window === "7d" ? "last 7 days" : "today"}</span><button class="btn small quiet end" type="button" data-redetect>Check sign-in again</button></div>
      <div class="prov-grid">${providersGrid(data)}</div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2>Agent roster</h2><span class="faint" style="font-size: 12px">${on} of ${data.roster.length} enabled</span><span class="end mono faint" style="font-size: 11px">written to SETTINGS.md on save</span></div>
      <div class="table"><div class="rows roster-rows">
        <div class="thead roster-row"><div class="r-on">ON</div><div class="r-name">AGENT</div><div class="r-cli">CLI · MODEL</div><div class="r-skill">SKILL</div><div class="r-used">USED IN</div><div class="r-tokens">TOKENS</div><div class="r-edit"></div></div>
        ${data.roster.map((item) => role(item, data.set_here))}
      </div></div>
      <datalist id="agent-clis">${clis.map((cli) => html`<option value="${cli}"></option>`)}</datalist>
    </section>
    ${newAgentDialog(data, app)}
    <div class="agents-row">
      <section class="panel"><div class="panel-body">
        <h2 class="section-title" style="margin-bottom: 16px">Parallelism and limits</h2>
        <div class="lim-fields">${field("sessions.max", "MAX CONCURRENT CLI SESSIONS", data.sessions_max)}${field("tokens.per_ticket_max", "TOKEN CEILING PER TICKET", data.tokens_per_ticket, 'step="1000"')}</div>
        <div class="lim-fields">${Object.entries(data.per_provider).map(([name, total]) => field(`sessions.per_provider.${name}`, `${name.toUpperCase()} SESSIONS`, total))}</div>
        <div class="checks">
          <label class="check"><input type="checkbox" checked disabled>Hold serial tickets until the module is free <span class="faint">(the scheduler always does)</span></label>
          <label class="check"><input type="checkbox" data-key="fallback_on_rate_limit" data-kind="bool" data-initial="${data.fallback_on_rate_limit ? "1" : ""}" ${data.fallback_on_rate_limit ? "checked" : ""}>Fall back to the next provider when one is rate limited</label>
        </div>
      </div></section>
      <section class="panel"><div class="panel-body">
        <h2 class="section-title">Importance routing</h2><p class="section-note">Which loop shape a freshly cut ticket gets</p>
        <div class="routes">${routing(data)}</div>
        <a href="#/workflow" style="font-size: 12px; font-weight: 500">Edit the loop shapes</a>
      </div></section>
    </div>
  </div>`;
}

export function bind(root, app, data, bar) {
  if (data.problem) return;
  bindScope(root, app, { setHere: data.set_here, bar });
  const grid = root.querySelector(".prov-grid");
  const fill = async (refresh) => {
    try {
      const fresh = await get(`/api/agents?project=${encodeURIComponent(scopeOf(app))}&window=${app.window}${refresh ? "&refresh=1" : ""}`);
      if (grid.isConnected) mount(grid, providersGrid(fresh));
    } catch (error) {
      app.toast(error.message, true);
    }
  };
  if (data.providers.some((card) => !card.checked)) fill(false);
  const again = root.querySelector("[data-redetect]");
  again?.addEventListener("click", async () => {
    again.disabled = true;
    again.textContent = "Checking…";
    mount(grid, providersGrid({ providers: data.providers.map((card) => ({ ...card, checked: false })) }));
    await fill(true);
    if (again.isConnected) {
      again.disabled = false;
      again.textContent = "Check sign-in again";
    }
  });
  bindNewAgent(root, app, data, bar);
  root.addEventListener("click", async (event) => {
    const remove = event.target.closest("[data-remove-agent]");
    if (remove) {
      if (!armed(remove, "Click again to remove")) return;
      const role = remove.dataset.removeAgent;
      state.open.delete(role);
      const done = await app.post(`/api/agents/${encodeURIComponent(role)}/remove`, { project: scopeOf(app) });
      if (done) app.toast(`Removed ${role}, its step and its workflow edges; its skill file stays.`);
      return;
    }
    const edit = event.target.closest("[data-edit]");
    if (!edit) return;
    const editor = edit.closest(".roster-item").querySelector(".roster-editor");
    const open = editor.hidden;
    editor.hidden = !open;
    edit.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) state.open.add(edit.dataset.edit);
    else state.open.delete(edit.dataset.edit);
  });
}

function bindNewAgent(root, app, data, bar) {
  const dialog = root.querySelector("#new-agent");
  const form = dialog.querySelector("form");
  const f = form.elements; // not form.role: a form's own properties (role, …) would win
  const error = dialog.querySelector(".na-error");
  const options = (select, steps, keep, empty = "") => {
    const current = select.value || keep;
    mount(select, html`${empty ? html`<option value="">${empty}</option>` : ""}${steps.map((step) => html`<option value="${step}">${label(step)}</option>`)}`);
    select.value = steps.includes(current) ? current : empty ? "" : steps[0] ?? "";
  };
  const sync = () => {
    const flows = [...form.querySelectorAll("[name=workflows]:checked")].map((box) => box.value);
    const steps = common(data, flows);
    const review = f.kind.value === "review";
    options(f.after, steps, steps.includes("review_code") ? "review_code" : "", "last, before approval");
    options(f.send_back, steps, "implement");
    f.after.disabled = !flows.length;
    dialog.querySelector("[data-review-only]").hidden = !review;
  };
  const open = () => {
    form.reset();
    error.textContent = "";
    sync();
    dialog.showModal();
    f.role.focus();
  };
  form.addEventListener("change", sync);
  dialog.querySelector("[data-na-cancel]").addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const flows = [...form.querySelectorAll("[name=workflows]:checked")].map((box) => box.value);
    const review = f.kind.value === "review";
    const body = {
      project: scopeOf(app),
      role: f.role.value.trim(),
      kind: f.kind.value,
      does: f.does.value.trim(),
      cli: f.cli.value.trim() || "claude",
      workflows: flows,
      after: flows.length && f.after.value ? f.after.value : null,
      send_back: review && flows.length && f.send_back.value ? f.send_back.value : null,
    };
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    try {
      await post("/api/agents", body);
      dialog.close();
      app.toast(`Added ${body.role}${flows.length ? ` to ${flows.join(", ")}` : ""}; its starter skill is in roles/${body.role}/SKILL.md.`);
      await app.refresh();
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      submit.disabled = false;
    }
  });
  bar?.querySelector("[data-new-agent]")?.addEventListener("click", open);
  if (state.creating) {
    state.creating = false;
    history.replaceState(null, "", "#/agents"); // a refresh does not reopen it
    open();
  }
}
