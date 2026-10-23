// Memory store: how each project sees the one store (system spec §4.2), and the fix for
// each broken link. Memory files, the ticket index and memory writes arrive in M2.
import { get } from "../api.js";
import { html } from "../html.js";

const STATES = { ok: ["ok", "ok"], missing: ["missing", "danger"], "points elsewhere": ["points elsewhere", "warn"], "real folder": ["real folder", "warn"], "blocked by a file": ["blocked by a file", "danger"], "repo missing": ["repo missing", "danger"] };

export async function load() {
  return get("/api/links");
}

function badge(state) {
  const [label, tone] = STATES[state] ?? [state, "warn"];
  return html`<span class="badge ${tone}">${label}</span>`;
}

function action(item) {
  if (item.fix === "repair") return html`<button class="btn primary small" type="button" data-link="repair">Repair</button>`;
  if (item.fix === "adopt") return html`<button class="btn small" type="button" data-link="adopt" data-path="${item.repo}">Adopt its folder</button>`;
  if (item.fix === "relink")
    return html`<form class="relink" data-project="${item.project}"><label class="sr-only" for="to-${item.project}">New path of ${item.project}</label><input id="to-${item.project}" name="path" placeholder="new path of the repo" required><button class="btn primary small" type="submit">Re-link</button></form>`;
  if (item.fix === "manual") return html`<span class="faint mono" style="font-size: 11px">${item.hint}</span>`;
  return "";
}

export function project(item) {
  return html`<div class="link-row">
    <div class="link-name"><b>${item.project}</b><span class="faint mono">${item.tickets} tickets</span></div>
    <div class="link-paths mono">
      <div>${badge(item.state)}<span>${item.link}</span><span class="faint">→</span><span class="muted">${item.target}</span></div>
      <div>${badge(item.memory)}<span>memory</span><span class="faint">→</span><span class="muted">../../memory</span>${item.excluded === false ? html`<span class="badge warn">not in .git/info/exclude</span>` : ""}</div>
    </div>
    <div class="link-fix">${action(item)}${item.hint && item.fix !== "manual" ? html`<span class="faint mono" style="font-size: 11px">${item.hint}</span>` : ""}</div>
  </div>`;
}

function nearby(found) {
  return html`<div class="link-row">
    <div class="link-name"><b>${found.repo.split("/").pop()}</b><span class="faint mono">${found.tickets} tickets · ${found.plans} plans</span></div>
    <div class="link-paths mono"><div><span class="badge warn">not linked</span><span>${found.path}</span></div></div>
    <div class="link-fix"><button class="btn small" type="button" data-link="adopt" data-path="${found.repo}">Adopt</button><span class="faint mono" style="font-size: 11px">harness adopt ${found.repo}</span></div>
  </div>`;
}

export function view(data) {
  const tickets = data.projects.reduce((sum, item) => sum + item.tickets, 0);
  const broken = data.total - data.intact;
  return html`<div class="page">
    <div class="page-head"><div><h1>Memory store</h1><p>One store outside every repo. Each project sees it through one folder link, so the store and the repo show the same files.</p></div></div>
    <div class="tiles">
      <div class="tile ${broken ? "alert" : ""}"><div class="label">FOLDER LINKS</div><div class="value">${data.intact}<span class="faint" style="font-size: 18px">/${data.total}</span></div><div class="note">${broken ? `${broken} need a fix` : "every link intact"}</div></div>
      <div class="tile"><div class="label">TICKETS</div><div class="value">${tickets}</div><div class="note">in the store, across ${data.total} ${data.total === 1 ? "project" : "projects"}</div></div>
      <div class="tile"><div class="label">STORES NEARBY</div><div class="value">${data.nearby.length}</div><div class="note">real .harness folders beside your repos</div></div>
    </div>
    <section class="panel">
      <div class="panel-head"><h2>Link health</h2><span class="faint" style="font-size: 12px">&lt;repo&gt;/.harness → the project's folder in the store; inside it, memory → the global memory</span></div>
      ${data.projects.length ? data.projects.map(project) : html`<div class="empty">No project yet: run harness init inside a repo.</div>`}
    </section>
    ${data.nearby.length
      ? html`<section class="panel"><div class="panel-head"><h2>Stores found nearby</h2><span class="faint" style="font-size: 12px">adopting merges a folder's plans and tickets into the store, archives the original, and links it</span></div>${data.nearby.map(nearby)}</section>`
      : ""}
    <p class="faint" style="font-size: 12px; margin: 0">Why a folder link and not hard links: folders cannot be hard-linked, and a hard-linked file goes stale on every atomic save or status move. The folder link keeps both paths live, works across disks, and <span class="mono">harness doctor --fix</span> restores it.</p>
  </div>`;
}

export function bind(root, app) {
  bindLinks(root, app);
}

export function bindLinks(root, app) {
  root.querySelectorAll("[data-link]").forEach((button) =>
    button.addEventListener("click", async () => {
      const kind = button.dataset.link;
      if (kind === "adopt" && button.dataset.armed !== "1") {
        button.dataset.armed = "1";
        button.textContent = "Confirm adopt";
        return;
      }
      button.disabled = true;
      const done = await app.post(`/api/links/${kind}`, kind === "adopt" ? { path: button.dataset.path } : {});
      if (done) app.toast(kind === "adopt" ? "Adopted and linked." : "Links repaired.");
    }),
  );
  root.querySelectorAll("form.relink").forEach((form) =>
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const path = new FormData(form).get("path");
      const done = await app.post("/api/links/relink", { project: form.dataset.project, path });
      if (done) app.toast(`Re-linked ${form.dataset.project}.`);
    }),
  );
}
