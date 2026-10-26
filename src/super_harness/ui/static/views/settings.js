// Project settings (canvas board Settings): loop limits, token discipline, project commands
// and the status flow of one scope, its SETTINGS.md with this scope's overrides in amber, and
// the memory behind it: the files, the shared store and what the project sees of it.
import { get } from "../api.js";
import { clock } from "../format.js";
import { html } from "../html.js";
import { icon } from "../icons.js";
import { bindScope, check, configBar, field, loadScoped, pick, scopeOf, text } from "../scope.js";

const state = { relink: false };

export async function load(app) {
  const scope = scopeOf(app);
  const [data, memory] = await Promise.all([loadScoped(app, "/api/settings"), get(`/api/memory?project=${encodeURIComponent(scope)}`)]);
  return { ...data, memory };
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

// A YAML line in the canvas's colours: comment faint, key muted, an override amber, true green,
// false or off red, any other value white.
function colour(line, isSet) {
  if (line.trim().startsWith("#")) return html`<span class="faint">${line}</span>`;
  const m = /^(\s*[^:#]+:)(\s*)(.*?)(\s+#.*)?$/.exec(line);
  if (!m) return html`<span class="${isSet ? "y-set" : "y-val"}">${line || " "}</span>`;
  const value = m[3];
  const tone = isSet ? "y-set" : /^(true)$/.test(value) ? "y-true" : /^(false|off|null)$/.test(value) ? "y-false" : "y-val";
  return html`${m[1]}${m[2]}<span class="${tone}">${value}</span>${m[4] ? html`<span class="faint">${m[4]}</span>` : ""}`;
}

function fileView(data) {
  const keys = lineKeys(data.file);
  const isSet = (key) => key && data.set_here.some((k) => k === key || k.startsWith(`${key}.`) || key.startsWith(`${k}.`));
  const lines = data.file.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return html`<div class="yaml">${lines.map((line, i) => html`<span>${colour(line, isSet(keys[i]))}</span>`)}</div>`;
}

function flowChips(values, setHere) {
  const names = pick(values, "status.names") ?? {};
  const set = setHere.some((k) => k.startsWith("status.names"));
  return html`<div class="flow-chips">${Object.entries(names).map(
    ([step, name], i) => html`${i ? html`<span class="faint">→</span>` : ""}<span class="flow-chip ${set && setHere.includes(`status.names.${step}`) ? "set" : ""}" title="while ${step} runs">${name}</span>`,
  )}<a class="flow-chip add" href="#/agents/new" title="A new step comes with its agent">+ add</a></div>`;
}

const FILE_NOTES = {
  "MEMORY.md": "How you work, your standing goals, and what you have already turned down",
  "PROCESS.md": "How this codebase is built, tested and released",
  "DECISIONS.md": "Design calls worth keeping, each with why",
  "AGENTS.md": "Read first by every CLI, linked to CLAUDE.md and GEMINI.md",
};

function fileCards(memory, scope) {
  const byName = Object.fromEntries(memory.files.map((file) => [file.name, file]));
  return html`<div class="file-cards">${["MEMORY.md", "PROCESS.md", "DECISIONS.md", "AGENTS.md"].map((name) => {
    const file = byName[name];
    const scopeLabel = ["MEMORY.md", "DECISIONS.md"].includes(name) ? "GLOBAL" : "PROJECT";
    const stats = !file
      ? scope || scopeLabel === "GLOBAL"
        ? html`<span class="faint">not written yet</span>`
        : html`<span class="faint">pick a project to see it</span>`
      : name === "DECISIONS.md"
        ? html`<span>${file.entries} entries</span><span>edited ${clock(file.updated).slice(0, 5)}</span>`
        : name === "MEMORY.md"
          ? html`<span>${file.lines} lines</span><span>${file.compacted ? `compacted ${clock(file.compacted).slice(0, 5)}` : "never compacted"}</span>`
          : html`<span>${file.lines} lines</span><span>edited ${clock(file.updated).slice(0, 5)}</span>`;
    return html`<div class="file-card"><div class="file-card-head"><span class="mono">${name}</span><span class="scope-tag ${scopeLabel === "PROJECT" ? "project" : ""}">${scopeLabel}</span></div><p>${FILE_NOTES[name]}</p><div class="file-card-stats mono">${stats}</div></div>`;
  })}</div>`;
}

function storeTree(memory) {
  const counts = {};
  for (const row of memory.index) {
    const folder = row.status.split("/")[0];
    counts[row.project] ??= { in_queue: 0, in_process: 0, done: 0 };
    counts[row.project][folder] += 1;
  }
  const projects = memory.links.projects.map((p) => p.project);
  const lines = [html`memory/`, html`├── <span class="t-file">MEMORY.md</span>       the brain`, html`└── <span class="t-file">DECISIONS.md</span>    design calls`, html`projects/`];
  projects.forEach((name, i) => {
    const last = i === projects.length - 1;
    const c = counts[name] ?? { in_queue: 0, in_process: 0, done: 0 };
    const bar = last ? " " : "│";
    lines.push(html`${last ? "└" : "├"}── ${name}/tasks/`);
    lines.push(html`${bar}   ├── in_queue/     <span class="t-file">${c.in_queue}</span>`);
    lines.push(html`${bar}   ├── in_process/   <span class="t-busy">${c.in_process}</span>`);
    lines.push(html`${bar}   └── done/         <span class="t-ok">${c.done}</span>`);
  });
  if (!projects.length) lines.push(html`└── <span class="faint">no project yet: run harness init in a repo</span>`);
  return html`<div class="tree">${lines.map((l) => html`<span>${l}</span>`)}</div>`;
}

function projectTree(link) {
  if (!link) return html`<div class="tree"><span class="faint">Pick a project in the scope menu to see its folder link.</span></div>`;
  const ok = link.state === "ok";
  const lines = [
    html`<span class="${ok ? "t-ok" : "danger-text"}">.harness/</span>       ${ok ? "one folder link to the store" : `folder link: ${link.state}`}`,
    html`├── <span class="t-file">PROCESS.md</span>  this codebase`,
    html`├── <span class="t-file">SETTINGS.md</span> yours to edit`,
    html`├── <span class="t-file">memory/</span>     <span class="${link.memory === "ok" ? "t-ok" : "danger-text"}">→ ../../memory</span>  MEMORY.md, DECISIONS.md`,
    html`├── <span class="t-file">plans/</span>      this project's plans`,
    html`└── <span class="t-file">tasks/</span>      in_queue · in_process · done`,
    html`<span class="t-file">AGENTS.md</span>       in the repo; every CLI reads it`,
  ];
  return html`<div class="tree">${lines.map((l) => html`<span>${l}</span>`)}</div>`;
}

function memorySection(data, scope) {
  const memory = data.memory;
  const links = memory.links;
  const link = links.projects.find((p) => p.project === scope);
  const broken = links.total - links.intact;
  return html`<section class="settings-memory">
    <div class="mem-head"><h2>Memory</h2><p>One store outside the repos; each project sees it through one folder link, so both paths stay live.</p>
      ${links.total ? html`<span class="pill ${broken ? "danger" : "ok"}">${icon(broken ? "warning" : "check", { size: 12, width: 1.8 })}${links.intact} of ${links.total} links intact</span>` : html`<span class="pill plain-pill">no project linked yet</span>`}</div>
    ${fileCards(memory, scope)}
    <div class="tree-row">
      <div class="tree-panel"><div class="tree-head"><b>Shared store</b><span class="end mono faint">~/.harness/</span></div>${storeTree(memory)}</div>
      <div class="tree-panel"><div class="tree-head"><b>Inside the project</b><span class="end mono faint ellipsis" title="${link ? `${link.link} → ${link.target}` : ""}">${link ? `./${link.repo.split("/").pop()}/.harness → ~/.harness/projects/${link.project}/` : "pick a project"}</span></div>${projectTree(link)}
        <div class="tree-actions">
          ${link ? (state.relink ? html`<form class="relink" data-project="${link.project}"><label class="sr-only" for="relink-path">New path of ${link.project}</label><input id="relink-path" name="path" class="inline-input" placeholder="new path of the repo" required><button class="btn small" type="submit">Re-link</button></form>` : html`<button class="btn small" type="button" data-relink-open>Re-link</button>`) : ""}
          ${link?.fix === "repair" ? html`<button class="btn small" type="button" data-link="repair">Repair links</button>` : ""}
          <button class="btn small" type="button" data-link="adopt" data-path="${links.nearby[0]?.repo ?? ""}" ${links.nearby.length ? "" : html`disabled title="No real .harness folder found beside your repos"`}>Adopt a found store</button>
          <button class="btn small" type="button" data-compact ${memory.compacting ? "disabled" : ""}>${memory.compacting ? "Compacting…" : "Compact now"}</button>
        </div>
      </div>
    </div>
  </section>`;
}

export function top(data, app) {
  return configBar(app, data.projects, data.set_here, { reset: true, save: "Save" });
}

export function view(data, app) {
  const v = data.values;
  const scope = scopeOf(app);
  const on = (key) => data.set_here.includes(key);
  const num = (key, label, extra = {}) => field({ key, label, value: pick(v, key), setHere: on(key), ...extra });
  const box = (key, label) => check({ key, label, value: pick(v, key), setHere: on(key) });
  return html`<div class="page wide-page">
    <div style="max-width: 62ch"><h1 class="h1">Settings</h1><p class="lede">Defaults seed a project when it is registered. After that its file is yours: harness never overwrites it, and a save here changes only the lines you edited.</p></div>
    ${data.problem ? html`<div class="banner"><span class="badge danger">invalid</span>${data.problem}. Fix the file, or run harness settings check.</div>` : ""}
    <div class="settings-row">
      <div class="settings-form">
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
          <h2 class="section-title">Project commands</h2><p class="section-note">What test steps and reviewers run; empty means the project has none</p>
          <div class="fields">${text({ key: "project.test_cmd", label: "TEST COMMAND", value: pick(v, "project.test_cmd"), setHere: on("project.test_cmd"), placeholder: "uv run pytest -q" })}${text({ key: "project.lint_cmd", label: "LINT COMMAND", value: pick(v, "project.lint_cmd"), setHere: on("project.lint_cmd"), placeholder: "uv run ruff check" })}</div>
        </div></section>
        <section class="panel"><div class="panel-body">
          <h2 class="section-title">Status flow</h2><p class="section-note">Sub-statuses inside in_process, in the order a ticket passes them; the Workflow editor sets which steps run</p>
          ${flowChips(v, data.set_here)}
        </div></section>
      </div>
      <section class="panel settings-file">
        <div class="panel-head"><h2 class="mono" style="font-size: 12px">SETTINGS.md</h2><span class="end faint" style="font-size: 11px">${data.file.split("\n").length - 1} lines</span></div>
        <div class="file-paths mono"><div title="${data.path}"><span class="faint">store</span> ${data.path}</div>${data.repo_path ? html`<div title="${data.repo_path}"><span class="faint">repo</span> ${data.repo_path}</div>` : ""}</div>
        <div class="yaml-box" tabindex="0" role="region" aria-label="SETTINGS.md">${fileView(data)}</div>
        <div class="file-foot"><span class="y-set">Amber values</span> are set in this ${scope ? "project" : "scope"}; the rest ${scope ? "come from the defaults" : "match the package defaults"}.</div>
      </section>
    </div>
    ${memorySection(data, scope)}
  </div>`;
}

export function bind(root, app, data, bar) {
  bindScope(root, app, { setHere: data.set_here, bar });
  root.addEventListener("click", async (event) => {
    if (event.target.closest("[data-relink-open]")) {
      state.relink = true;
      await app.refresh();
      return document.getElementById("relink-path")?.focus();
    }
    const link = event.target.closest("[data-link]");
    if (link) {
      if (link.dataset.link === "adopt" && link.dataset.armed !== "1") {
        link.dataset.armed = "1";
        link.textContent = `Confirm: adopt ${link.dataset.path.split("/").pop()}`;
        return;
      }
      link.disabled = true;
      const done = await app.post(`/api/links/${link.dataset.link}`, link.dataset.link === "adopt" ? { path: link.dataset.path } : {});
      if (done) app.toast(link.dataset.link === "adopt" ? "Adopted and linked." : "Links repaired.");
      return;
    }
    const compact = event.target.closest("[data-compact]");
    if (compact) {
      compact.disabled = true;
      compact.textContent = "Compacting…";
      const done = await app.post("/api/memory/compact", {});
      if (done) app.toast("Compaction runs in the background; this page updates when it ends.");
    }
  });
  root.addEventListener("submit", async (event) => {
    const form = event.target.closest("form.relink");
    if (!form) return;
    event.preventDefault();
    const done = await app.post("/api/links/relink", { project: form.dataset.project, path: new FormData(form).get("path") });
    if (done) {
      state.relink = false;
      app.toast(`Re-linked ${form.dataset.project}.`);
    }
  });
}
