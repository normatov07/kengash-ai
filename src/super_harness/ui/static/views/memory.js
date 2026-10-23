// Memory store: the store's size and memory files, MEMORY.md with its cap and Compact, how
// each project sees the store (system spec §4.2) with the fix for each broken link, every
// ticket, and who wrote what.
import { get } from "../api.js";
import { clock, tokens } from "../format.js";
import { html, mount } from "../html.js";

const STATES = { ok: ["ok", "ok"], missing: ["missing", "danger"], "points elsewhere": ["points elsewhere", "warn"], "real folder": ["real folder", "warn"], "blocked by a file": ["blocked by a file", "danger"], "repo missing": ["repo missing", "danger"] };

export async function load(app) {
  return get(`/api/memory?project=${encodeURIComponent(app.project)}`);
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

const filters = { show: "all", find: "" };

function size(bytes) {
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} B`;
}

function when(ts) {
  if (!ts) return "never";
  const days = Math.floor((Date.now() - Date.parse(ts)) / 86400000);
  return days >= 1 ? `${days}d ago` : clock(ts);
}

function indexRows(data) {
  const find = filters.find.toLowerCase();
  const rows = data.index.filter((row) => {
    if (filters.show === "running" && !row.status.startsWith("in_process/")) return false;
    if (filters.show === "done" && !row.status.startsWith("done/")) return false;
    return !find || `${row.id} ${row.title} ${row.project}`.toLowerCase().includes(find);
  });
  return { rows: rows.slice(0, 50), total: rows.length };
}

function indexBody(data) {
  const { rows, total } = indexRows(data);
  return html`${rows.length
    ? rows.map(
        (row) => html`<div class="trow"><div class="cell-id mono"><a href="#/ticket/${row.id}">${row.id}</a></div><div class="cell-grow">${row.title}</div><div class="cell-proj faint">${row.project}</div><div class="cell-agent mono faint">${row.status}</div><div class="cell-num mono">${row.loop}/${row.loop_max}</div><div class="cell-models mono faint">${row.models.join(" ")}</div><div class="cell-num mono faint">${row.closed ? clock(row.closed) : "—"}</div></div>`,
      )
    : html`<div class="empty">No ticket matches.</div>`}
    <div class="trow faint" style="font-size: 12px">${rows.length} of ${total} shown<a class="end" href="#/board" style="margin-left: auto">Open the board</a></div>`;
}

function write(event) {
  const what = event.type === "memory.compacted"
    ? `compacted ${event.before} → ${event.after} lines${event.accepted ? "" : ` (refused: ${event.reason})`}`
    : event.type === "ticket.moved" ? `${event.from ?? ""} → ${event.to ?? ""}` : event.line;
  const file = event.type === "ticket.moved" ? `tasks/${event.ticket}` : event.file;
  return html`<div class="journal-row"><span class="time">${clock(event.ts)}</span><span class="kind mono">${file}</span><span class="id mono faint">${event.by ?? "harness"}</span><span class="text">${what}${event.why ? html` <span class="faint">· ${event.why}</span>` : ""}</span></div>`;
}

export function view(data, app) {
  const links = data.links;
  const broken = links.total - links.intact;
  const memory = data.files.find((file) => file.name === "MEMORY.md");
  const lines = memory?.lines ?? 0;
  const t = data.tickets;
  return html`<div class="page">
    <div class="page-head">
      <div><h1>Memory store</h1><p>One store outside every repo. Agents in separate CLI sessions read and write it to hand work over; each project sees it through one folder link.</p></div>
      <div class="backends"><span class="chip">markdown files · active</span><span class="chip plain">sqlite index · planned</span><span class="chip plain">vector recall · planned</span></div>
    </div>
    <div class="tiles">
      <div class="tile"><div class="label">STORE SIZE</div><div class="value">${size(data.size_bytes)}</div><div class="note">${data.ticket_files} ticket files · ${data.files.length} memory files shown</div></div>
      <div class="tile"><div class="label">TICKETS</div><div class="value">${data.ticket_files}</div><div class="note">${t.in_queue} queued · ${t.in_process} in process · ${t.done} done</div></div>
      <div class="tile ${broken ? "alert" : ""}"><div class="label">FOLDER LINKS</div><div class="value">${links.intact}<span class="faint" style="font-size: 18px">/${links.total}</span></div><div class="note">${broken ? `${broken} need a fix` : "every link intact"}</div></div>
      <div class="tile"><div class="label">READ COST</div><div class="value">${tokens(memory?.tokens ?? 0)}</div><div class="note">tokens for MEMORY.md per agent start (characters ÷ 4)</div></div>
    </div>
    <div class="split">
      <div class="grow stack">
        <section class="panel"><div class="panel-head"><h2>Memory files</h2><span class="faint" style="font-size: 12px">${app.project ? `global files and ${app.project}'s own` : "global files reach every project through its folder link; pick a project above for its files"}</span></div>
          <div class="table"><div class="rows">
            <div class="thead"><div class="cell-grow">FILE</div><div class="cell-scope">SCOPE</div><div class="cell-num">SIZE</div><div class="cell-num">PER READ</div><div class="cell-when">COMPACTED</div><div class="cell-when">EDITED</div></div>
            ${data.files.length ? data.files.map((file) => html`<div class="trow"><div class="cell-grow mono" title="${file.path}">${file.name}</div><div class="cell-scope"><span class="badge ${file.scope === "global" ? "info" : ""}">${file.scope}</span></div><div class="cell-num mono">${file.name === "DECISIONS.md" ? `${file.entries} e` : `${file.lines} L`}</div><div class="cell-num mono">${tokens(file.tokens)}</div><div class="cell-when mono faint">${file.name === "MEMORY.md" ? when(file.compacted) : "n/a"}</div><div class="cell-when mono faint">${when(file.updated)}</div></div>`) : html`<div class="empty">No memory files yet: run harness init.</div>`}
          </div></div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>MEMORY.md</h2><span class="faint" style="font-size: 12px">the brain every session reads first</span><button class="btn small end" type="button" data-compact ${data.compacting || !memory ? "disabled" : ""}>${data.compacting ? "Compacting…" : "Compact now"}</button></div>
          <div class="panel-body">
            <pre class="file-view wrap mono">${data.memory_text.split("\n").filter((line, i, all) => i < all.length - 1 || line).map((line) => html`<span class="${line.startsWith("#") ? "line note" : "line"}">${line || " "}</span>`)}</pre>
            <div class="cap"><div class="cap-bar"><span style="width: ${Math.min(100, Math.round((lines / data.cap) * 100))}%" class="${lines > data.cap ? "over" : ""}"></span></div><span class="mono faint" style="font-size: 11px">${lines} / ${data.cap} lines · compacts at ${data.cap} · linked into ${links.total} ${links.total === 1 ? "project" : "projects"}</span></div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h2>Ticket index</h2><span class="faint" style="font-size: 12px">every ticket in the store</span>
            <div class="segmented end" role="group" aria-label="Show">${[["all", "All"], ["running", "Running"], ["done", "Done"]].map(([key, label]) => html`<button type="button" data-show="${key}" aria-pressed="${filters.show === key ? "true" : "false"}">${label}</button>`)}</div></div>
          <div class="panel-body" style="padding-bottom: 0"><label class="sr-only" for="find">Find a ticket</label><input id="find" class="inline-input" type="search" placeholder="Find a ticket by id, title or project" value="${filters.find}"></div>
          <div class="table"><div class="rows index-rows">${indexBody(data)}</div></div>
        </section>
      </div>
      <div class="side">
        <section class="panel">
          <div class="panel-head"><h2>Link health</h2>${broken ? html`<span class="badge danger end">${broken} broken</span>` : html`<span class="badge ok end">intact</span>`}</div>
          ${links.projects.length ? links.projects.map(project) : html`<div class="empty">No project yet: run harness init inside a repo.</div>`}
        </section>
        ${links.nearby.length ? html`<section class="panel"><div class="panel-head"><h2>Stores found nearby</h2></div><div class="panel-body"><p class="faint" style="font-size: 12px; margin: 0">Adopting merges a folder's plans and tickets into the store, archives the original, and links it.</p></div>${links.nearby.map(nearby)}</section>` : ""}
        <section class="panel"><div class="panel-head"><h2>Writes to memory</h2><span class="end faint" style="font-size: 12px">who changed the shared files, and why</span></div>
          <div class="journal">${data.writes.length ? data.writes.map(write) : html`<div class="empty">Nothing written yet.</div>`}</div></section>
        <p class="faint" style="font-size: 12px; margin: 0">Why a folder link and not hard links: folders cannot be hard-linked, and a hard-linked file goes stale on every atomic save or status move. The folder link keeps both paths live, works across disks, and <span class="mono">harness doctor --fix</span> restores it.</p>
      </div>
    </div>
  </div>`;
}

export function bind(root, app, data) {
  bindLinks(root, app);
  root.querySelector("[data-compact]")?.addEventListener("click", async (event) => {
    event.currentTarget.disabled = true;
    event.currentTarget.textContent = "Compacting…";
    const result = await app.post("/api/memory/compact", {});
    if (result) app.toast("Compaction runs in the background; this page updates when it ends.");
  });
  const rows = root.querySelector(".index-rows");
  root.querySelectorAll("[data-show]").forEach((button) =>
    button.addEventListener("click", () => {
      filters.show = button.dataset.show;
      root.querySelectorAll("[data-show]").forEach((other) => other.setAttribute("aria-pressed", other === button ? "true" : "false"));
      mount(rows, indexBody(data));
    }),
  );
  root.querySelector("#find")?.addEventListener("input", (event) => {
    filters.find = event.target.value;
    mount(rows, indexBody(data));
  });
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
