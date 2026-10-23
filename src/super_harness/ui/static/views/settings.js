// Project settings: loop limits, token discipline and the status flow of one scope, its
// SETTINGS.md with this scope's overrides marked, and the folder links behind the memory.
import { get } from "../api.js";
import { html } from "../html.js";
import { actions, bindScope, check, field, loadScoped, pick, tabs } from "../scope.js";
import { bindLinks, project } from "./memory.js";

export async function load(app) {
  const [data, links] = await Promise.all([loadScoped(app, "/api/settings"), get("/api/links")]);
  return { ...data, links };
}

// The dotted key each line of SETTINGS.md sets, from indentation; continuation lines of a
// multi-line flow value belong to the line above.
function lineKeys(file) {
  const stack = [];
  let last = null;
  return file.split("\n").map((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) return null;
    const indent = line.length - line.trimStart().length;
    const match = /^([^\s:#{}[\],][^:#{}[\],]*):(\s|$)/.exec(trimmed);
    if (!match) return last && indent > last.indent ? last.key : null;
    while (stack.length && stack[stack.length - 1].indent >= indent) stack.pop();
    if (last && indent > last.indent && !last.block) return last.key;
    const key = [...stack.map((s) => s.key), match[1].trim()].join(".");
    const block = trimmed.slice(match[0].length).trim() === "";
    if (block) stack.push({ indent, key: match[1].trim() });
    last = { indent, key, block };
    return block ? null : key;
  });
}

function fileView(data) {
  const keys = lineKeys(data.file);
  const isSet = (key) => key && data.set_here.some((k) => k === key || k.startsWith(`${key}.`) || key.startsWith(`${k}.`));
  const lines = data.file.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return html`<pre class="file-view mono">${lines.map(
    (line, i) => html`<span class="${isSet(keys[i]) ? "line set" : line.trim().startsWith("#") ? "line note" : "line"}">${line || " "}</span>`,
  )}</pre>`;
}

function flowChips(values) {
  const names = pick(values, "status.names") ?? {};
  return html`<div class="flow-chips">${Object.entries(names).map(
    ([step, name], i) => html`${i ? html`<span class="faint">→</span>` : ""}<span class="chip mono" title="${step}">${name}</span>`,
  )}</div>`;
}

export function view(data, app) {
  const v = data.values;
  const on = (key) => data.set_here.includes(key);
  const num = (key, label, extra = {}) => field({ key, label, value: pick(v, key), setHere: on(key), ...extra });
  const box = (key, label) => check({ key, label, value: pick(v, key), setHere: on(key) });
  const links = data.links;
  const shown = data.scope ? links.projects.filter((p) => p.project === data.scope) : links.projects;
  return html`<div class="page">
    <div class="page-head">
      <div><h1>Settings</h1><p>Defaults seed a project when it is registered. After that its file is yours: harness never overwrites it, and a save here changes only the lines you edited.</p></div>
      <div class="head-stack">${tabs(app, data.projects)}${actions(app, data.set_here)}</div>
    </div>
    ${data.problem ? html`<div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix the file, or run harness settings check.</div>` : ""}
    <div class="split">
      <div class="grow stack">
        <section class="panel"><div class="panel-body">
          <h2 class="section-title">Loop limits</h2><p class="section-note">How many times a ticket may go round before it needs you</p>
          <div class="fields">${num("loop_max.simple", "SIMPLE", { min: 1 })}${num("loop_max.standard", "STANDARD", { min: 1 })}${num("loop_max.critical", "CRITICAL", { min: 1 })}${num("loop_grant", "GRANT ON ASK", { min: 1 })}</div>
          <div class="checks">${box("loop_ask_at_cap", "Ask me when a ticket hits its cap (off: park it instead)")}${box("loop_count_rejected_review", "Count a rejected plan review as a full loop")}</div>
        </div></section>
        <section class="panel"><div class="panel-body">
          <h2 class="section-title">Token discipline</h2><p class="section-note">Caps checked when a skill or memory file is written, so reads stay cheap</p>
          <div class="fields">${num("skill.max_lines", "SKILL LINES", { min: 1 })}${num("skill.max_words", "SKILL WORDS", { min: 1 })}${num("memory.compact_at_lines", "COMPACT AT", { min: 10 })}</div>
          <div class="checks">${box("review.diff_only", "Reviewers read the diff only")}${box("sessions.reuse", "Reuse each ticket's CLI session per role across loops")}</div>
        </div></section>
        <section class="panel"><div class="panel-body">
          <h2 class="section-title">Status flow</h2><p class="section-note">Sub-statuses inside in_process, in the order a ticket passes them; the Workflow editor sets which steps run</p>
          ${flowChips(v)}
        </div></section>
      </div>
      <div class="side">
        <section class="panel">
          <div class="panel-head"><h2>SETTINGS.md</h2><span class="end faint mono">${data.file.split("\n").length - 1} lines</span></div>
          <div class="panel-body">
            <div class="paths mono"><div><span class="faint">store</span> ${data.path}</div>${data.repo_path ? html`<div><span class="faint">repo</span> ${data.repo_path}</div>` : ""}</div>
            ${fileView(data)}
            <p class="faint" style="font-size: 12px; margin: 10px 0 0">Amber lines are set in this ${data.scope ? "project" : "scope"}; the rest ${data.scope ? "come from the defaults" : "match the package defaults"}.</p>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>Memory links</h2><span class="end faint">${links.intact} of ${links.total} intact</span></div>
          <div class="panel-body"><p class="faint" style="font-size: 12px; margin: 0">One store outside the repos; each project sees it through one folder link, so both paths stay live.</p></div>
          ${shown.length ? shown.map(project) : html`<div class="empty">No project yet: run harness init inside a repo.</div>`}
          <div class="panel-body"><a href="#/memory">Open the memory store</a></div>
        </section>
      </div>
    </div>
  </div>`;
}

export function bind(root, app, data) {
  bindScope(root, app, { setHere: data.set_here });
  bindLinks(root, app);
}
