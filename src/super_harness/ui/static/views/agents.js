// Agents and providers: which CLIs this machine has and their sign-in, the role roster
// (on or off, CLI and model, skill), session and token limits, and importance routing.
import { html } from "../html.js";
import { tokens } from "../format.js";
import { actions, bindScope, check, field, loadScoped, tabs } from "../scope.js";

const BLURBS = {
  planner: "writes the ticket's implementation plan",
  "plan-reviewer": "second opinion on the plan before any code is written",
  implementer: "writes the code in a worktree of its own",
  "code-reviewer": "reviews the ticket's changes",
  "security-reviewer": "secrets, authz and dependency surface",
  "test-runner": "runs project.test_cmd, no model call",
  "doc-writer": "syncs docs with the code",
  compactor: "keeps MEMORY.md under its cap",
};

let refresh = false;

export async function load(app) {
  const query = `&window=${app.window}${refresh ? "&refresh=1" : ""}`;
  refresh = false;
  return loadScoped(app, "/api/agents", query);
}

function state(card) {
  if (!card.supported) return html`<span class="badge warn">not supported yet</span>`;
  if (!card.installed) return html`<span class="badge danger">not installed</span>`;
  if (!card.signed_in) return html`<span class="badge warn">signed out</span>`;
  return html`<span class="badge ok">signed in</span>`;
}

function provider(card) {
  const ready = card.supported && card.installed && card.signed_in;
  return html`<div class="provider ${ready ? "" : "off"}">
    <div class="provider-head"><b class="mono">${card.name}</b>${state(card)}</div>
    <div class="provider-row"><span class="faint">sessions</span><span class="mono">${card.slots_used} / ${card.slots_total}</span></div>
    <div class="provider-row"><span class="faint">${card.version ? "version" : "plan"}</span><span class="mono">${card.version || "subscription"}</span></div>
    <div class="provider-row"><span class="faint">spend</span><span class="mono">${tokens(card.spend)}</span></div>
    ${!ready && card.hint ? html`<button class="btn small" type="button" data-copy="${card.hint}" data-note="Copied; run it in a terminal, then Check sign-in again.">${card.installed ? "Sign in" : "Install"}</button><div class="faint" style="font-size: 11px">harness never installs or signs in for you: run the command it copies.</div>` : ""}
  </div>`;
}

function role(item, setHere) {
  const set = (key) => setHere.includes(`agents.${item.role}.${key}`);
  const id = `cli-${item.role}`;
  return html`<div class="trow roster-row ${item.on ? "" : "muted-row"}">
    <div class="cell-on"><input type="checkbox" aria-label="${item.role} on" data-key="agents.${item.role}.on" data-kind="bool" data-initial="${item.on ? "1" : ""}" ${item.on ? "checked" : ""}></div>
    <div class="cell-grow"><b class="mono">${item.role}</b>${item.blocking ? html` <span class="badge danger">blocking</span>` : ""}<div class="faint" style="font-size: 12px">${BLURBS[item.role] ?? ""}</div>${set("on") ? html`<span class="set-note">on/off set here</span>` : ""}</div>
    <div class="cell-cli ${set("cli") ? "set" : ""}"><label class="sr-only" for="${id}">${item.role} CLI and model</label><input id="${id}" class="inline-input" list="clis" data-key="agents.${item.role}.cli" data-kind="text" data-initial="${item.cli}" value="${item.cli}"></div>
    <div class="cell-skill mono faint" title="${item.skill_file}">${item.skill_file ? `roles/${item.skill}/SKILL.md` : html`<span class="badge danger">missing</span> ${item.skill}`}</div>
    <div class="cell-used faint">${item.used_in.length ? item.used_in.join(", ") : "not in any flow"}</div>
    <div class="cell-num mono">${tokens(item.tokens)}</div>
  </div>`;
}

export function view(data, app) {
  if (data.problem) {
    return html`<div class="page"><div class="page-head"><div><h1>Agents</h1></div><div class="head-stack">${tabs(app, data.projects)}</div></div><div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix SETTINGS.md, or run harness settings check.</div></div>`;
  }
  const on = data.roster.filter((item) => item.on).length;
  const clis = new Set(["claude", "claude/opus", "claude/sonnet", "claude/haiku", "codex", "antigravity", "shell"]);
  data.roster.forEach((item) => clis.add(item.cli));
  const slots = Object.entries(data.per_provider);
  return html`<div class="page">
    <div class="page-head">
      <div><h1>Agents</h1><p>Every agent is a role bound to one CLI and one model. Switch a role off and the loop skips its step.</p></div>
      <div class="head-stack">${tabs(app, data.projects)}${actions(app, data.set_here)}</div>
    </div>
    <section class="panel">
      <div class="panel-head"><h2>CLI providers</h2><span class="faint" style="font-size: 12px">detected on this machine · spend ${app.window === "all" ? "all time" : app.window === "7d" ? "last 7 days" : "today"}</span><button class="btn ghost small end" type="button" data-redetect>Check sign-in again</button></div>
      <div class="providers">${data.providers.map(provider)}</div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2>Agent roster</h2><span class="faint" style="font-size: 12px">${on} of ${data.roster.length} enabled · written to SETTINGS.md on save</span></div>
      <div class="table"><div class="rows">
        <div class="thead roster-row"><div class="cell-on">ON</div><div class="cell-grow">AGENT</div><div class="cell-cli">CLI · MODEL</div><div class="cell-skill">SKILL</div><div class="cell-used">USED IN</div><div class="cell-num">TOKENS</div></div>
        ${data.roster.map((item) => role(item, data.set_here))}
      </div></div>
      <datalist id="clis">${[...clis].map((cli) => html`<option value="${cli}"></option>`)}</datalist>
    </section>
    <div class="split">
      <section class="panel grow"><div class="panel-body">
        <h2 class="section-title">Parallelism and limits</h2><p class="section-note">Tickets whose touches overlap run one at a time, and a ticket without touches claims the whole repo; fallback moves a step to the agent's next CLI when one is rate limited</p>
        <div class="fields">${field({ key: "sessions.max", label: "MAX CONCURRENT CLI SESSIONS", value: data.sessions_max, setHere: data.set_here.includes("sessions.max"), min: 1, wide: true })}${field({ key: "tokens.per_ticket_max", label: "TOKEN CEILING PER TICKET", value: data.tokens_per_ticket, setHere: data.set_here.includes("tokens.per_ticket_max"), min: 1, step: 1000, wide: true })}</div>
        <div class="fields" style="margin-top: 12px">${slots.map(([name, total]) => field({ key: `sessions.per_provider.${name}`, label: `${name.toUpperCase()} SESSIONS`, value: total, setHere: data.set_here.includes(`sessions.per_provider.${name}`) }))}</div>
        <div class="checks">${check({ key: "fallback_on_rate_limit", label: "Fall back to the next provider when one is rate limited", value: data.fallback_on_rate_limit, setHere: data.set_here.includes("fallback_on_rate_limit") })}</div>
      </div></section>
      <section class="panel side"><div class="panel-body">
        <h2 class="section-title">Importance routing</h2><p class="section-note">Which loop shape a freshly cut ticket gets</p>
        <div class="routing">${Object.entries(data.routing).map(
          ([name, steps]) => html`<div class="route"><span class="imp imp-${name}">${name}</span><span class="mono muted">${steps.join(" → ")}</span></div>`,
        )}</div>
        <a href="#/workflow">Edit the loop shapes</a>
      </div></section>
    </div>
  </div>`;
}

export function bind(root, app, data) {
  bindScope(root, app, { setHere: data.set_here });
  root.querySelector("[data-redetect]")?.addEventListener("click", (event) => {
    event.currentTarget.disabled = true;
    event.currentTarget.textContent = "Checking…";
    refresh = true;
    app.refresh();
  });
}
