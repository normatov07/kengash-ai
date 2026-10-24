// Memory store (canvas board Memory): the store's size, the memory files with a viewer,
// how each project sees the store (system spec §4.2) with the fix for each broken link,
// stores found nearby, every ticket, and who wrote what; backends as the sidebar card.
import { get } from "../api.js";
import { clock, tokens } from "../format.js";
import { html, mount } from "../html.js";
import { icon } from "../icons.js";

const state = { file: "MEMORY.md", show: "all", find: "", relink: "" };
const FILE_NOTES = { "MEMORY.md": "the brain every session reads first", "DECISIONS.md": "design calls and what was turned down", "PROCESS.md": "how this codebase is built and tested", "SETTINGS.md": "this project's settings", "AGENTS.md": "read first by every CLI" };
const STATES = { "points elsewhere": "it points somewhere else", missing: "the folder link is missing", "real folder": "a real .harness folder sits where the link belongs", "blocked by a file": "a file blocks the link", "repo missing": "the repo folder moved or was deleted" };

export async function load(app) {
  return get(`/api/memory?project=${encodeURIComponent(app.project)}`);
}

function size(bytes) {
  if (bytes >= 1e6) return [(bytes / 1e6).toFixed(1), "MB"];
  if (bytes >= 1e3) return [(bytes / 1e3).toFixed(1), "KB"];
  return [String(bytes), "B"];
}

function when(ts) {
  if (!ts) return "never";
  const days = Math.floor((Date.now() - Date.parse(ts)) / 86400000);
  return days >= 1 ? `${days}d ago` : clock(ts).slice(0, 5);
}

function filtered(data) {
  const find = state.find.trim().toLowerCase();
  return data.index.filter((row) => {
    if (state.show === "running" && !row.status.startsWith("in_process/")) return false;
    if (state.show === "done" && !row.status.startsWith("done/")) return false;
    return !find || `${row.id} ${row.title} ${row.project}`.toLowerCase().includes(find);
  });
}

function indexBody(data) {
  const rows = filtered(data);
  const shown = rows.slice(0, 50);
  return html`${shown.length
    ? shown.map((row) => {
        const done = row.status.startsWith("done/");
        const atCap = row.loop >= row.loop_max && !done;
        return html`<a class="trow idx-row" href="#/ticket/${row.id}"><span class="i-id mono">${row.id}</span><span class="i-title ellipsis" title="${row.title}">${row.title}</span><span class="i-proj ellipsis muted">${row.project}</span><span class="i-folder mono ${done ? "ok-text" : row.status.startsWith("in_process/") ? "warn-text" : "faint"}">${row.status.replace("in_process/under_", "in_process/")}</span><span class="i-loops mono ${atCap ? "danger-text" : ""}">${row.loop}/${row.loop_max}</span><span class="i-models">${row.models.map((m) => html`<span class="mchip mono">${m.split("/").pop()}</span>`)}</span><span class="i-closed mono faint">${row.closed ? clock(row.closed).slice(0, 5) : "—"}</span></a>`;
      })
    : html`<div class="empty">${data.index.length ? "No ticket matches." : "No ticket yet: plans become tickets with /to-ticket."}</div>`}
    <div class="trow idx-foot"><span class="faint">${shown.length} of ${rows.length} shown</span><a class="end" href="#/board">Open the board</a></div>`;
}

function viewer(data) {
  const file = data.files.find((f) => f.name === state.file) ?? data.files[0];
  if (!file) return html`<section class="panel"><div class="empty">No memory file yet: run harness init.</div></section>`;
  const memory = file.name === "MEMORY.md";
  const pass = data.last_before ? Math.round(((data.last_after - data.last_before) / data.last_before) * 100) : 0;
  return html`<section class="panel">
    <div class="panel-head"><h2 class="mono" style="font-size: 12px">${file.name}</h2><span class="faint" style="font-size: 12px">${FILE_NOTES[file.name] ?? ""}</span>${memory ? html`<button class="btn small end" type="button" data-compact ${data.compacting ? "disabled" : ""}>${data.compacting ? "Compacting…" : "Compact"}</button>` : html`<span class="end mono faint" style="font-size: 11px" title="${file.path}">${file.scope}</span>`}</div>
    <div class="viewer"><div class="viewer-lines">${file.text.split("\n").filter((line, i, all) => i < all.length - 1 || line).map((line) => html`<span class="${line.startsWith("#") ? "faint" : line.startsWith("- ") ? "v-entry" : ""}">${line || " "}</span>`)}</div></div>
    <div class="viewer-foot mono">${memory
      ? html`<span><b>${file.lines}</b> / ${data.cap} lines</span><span>compacts at ${data.cap}</span><span>linked into <b>${data.links.total}</b> ${data.links.total === 1 ? "project" : "projects"}</span>${data.last_before ? html`<span class="ok-text">last pass ${pass}%</span>` : html`<span>never compacted</span>`}`
      : html`<span><b>${file.lines}</b> lines</span><span>${file.entries} entries</span><span>~${tokens(file.tokens)} tokens per read</span>`}</div>
  </section>`;
}

function linkCard(item) {
  const broken = Boolean(item.fix);
  if (!broken) {
    return html`<div class="lh-row">${icon("link", { size: 14, stroke: "var(--ok)", width: 1.6 })}<span class="ellipsis" title="${item.link} → ${item.target}">${item.project}</span><span class="end mono faint">${item.tickets} tickets</span></div>`;
  }
  const why = STATES[item.state] ?? (item.memory !== "ok" ? `its memory link is ${item.memory}` : item.excluded === false ? ".harness is not in .git/info/exclude" : item.state);
  const action = {
    repair: html`<button class="btn small accent" type="button" data-link="repair">Repair</button>`,
    adopt: html`<button class="btn small accent" type="button" data-link="adopt" data-path="${item.repo}">Adopt its folder</button>`,
    relink: state.relink === item.project
      ? html`<form class="relink" data-project="${item.project}"><label class="sr-only" for="to-${item.project}">New path of ${item.project}</label><input id="to-${item.project}" name="path" class="inline-input" placeholder="new path of the repo" required><button class="btn small accent" type="submit">Re-link</button></form>`
      : html`<button class="btn small accent" type="button" data-relink-open="${item.project}">Re-link</button>`,
    manual: html`<span class="mono faint" style="font-size: 11px">${item.hint}</span>`,
  }[item.fix];
  return html`<div class="lh-broken"><div class="lh-row tight">${icon("link-broken", { size: 14, stroke: "var(--danger)", width: 1.7 })}<b class="ellipsis">${item.project}</b><span class="end cbadge" style="background: #3A2024; color: #EF7A72">BROKEN</span></div>
    <p>${why[0].toUpperCase() + why.slice(1)}${item.tickets ? `, so its ${item.tickets} tickets are only in the shared store` : ""}.</p>${action}</div>`;
}

function write(event) {
  const what = event.type === "memory.compacted"
    ? html`compacted ${event.before} → ${event.after} lines ${event.accepted ? html`<span class="ok-text">${Math.round(((event.after - event.before) / Math.max(1, event.before)) * 100)}%</span>` : html`<span class="danger-text">refused: ${event.reason}</span>`}`
    : event.type === "ticket.moved"
      ? `moved ${event.from ?? ""} → ${event.to ?? ""}`
      : String(event.line ?? "").replace(/^- /, "");
  const file = event.type === "ticket.moved" ? `tasks/${String(event.ticket ?? "").slice(0, 4)}…` : event.file;
  return html`<div class="w-row"><span class="faint">${clock(event.ts)}</span><span class="w-file">${file}</span><span class="w-who">${event.by ?? "system"}</span><span class="w-what ellipsis">${what}${event.why && !String(what).includes(event.why) ? html` <span class="faint">· ${event.why}</span>` : ""}</span></div>`;
}

export function top(data, app) {
  const projects = app.overview?.projects ?? [];
  return html`<label class="sr-only" for="project">Store or project</label>
    <select id="project" class="select">${[["", "~/.harness/memory"], ...projects.map((p) => [p, `~/.harness/projects/${p}`])].map(([value, label]) => html`<option value="${value}" ${value === app.project ? "selected" : ""}>${label}</option>`)}</select>
    <label class="sr-only" for="mq">Find a ticket or memory entry</label>
    <input id="mq" class="search" type="search" placeholder="Find by id, title or project…" value="${state.find}">
    <button class="btn quiet" type="button" data-verify>Verify links</button>
    <button class="btn accent sans-btn" type="button" data-compact ${data.compacting ? "disabled" : ""}>${data.compacting ? "Compacting…" : "Compact all"}</button>`;
}

export function view(data, app) {
  const links = data.links;
  const broken = links.total - links.intact;
  const [value, unit] = size(data.size_bytes);
  const memory = data.files.find((f) => f.name === "MEMORY.md");
  const t = data.tickets;
  const tile = (label, v, u, note, alert = false) => html`<div class="tile ${alert ? "alert" : ""}"><div class="label">${label}</div><div class="value">${v}${u ? html`<span class="unit">${u}</span>` : ""}</div><div class="note">${note}</div></div>`;
  const brokenNames = links.projects.filter((p) => p.fix).map((p) => p.project);
  return html`<div class="page wide-page">
    <div style="max-width: 62ch"><h1 class="h1">Memory store</h1><p class="lede">One store outside every repo. Agents in separate CLI sessions read and write it to hand work over.</p></div>
    <div class="tiles">
      ${tile("STORE SIZE", value, ` ${unit}`, `${data.ticket_files} ticket files · ${data.files.length} md files`)}
      ${tile("TICKETS", data.ticket_files, "", `${t.in_queue} queued · ${t.in_process} running · ${t.done} done`)}
      ${tile("FOLDER LINKS", links.intact, `/${links.total}`, broken ? `${broken} broken · ${brokenNames.join(", ")}` : "every link intact", broken > 0)}
      ${tile("READ COST", tokens(memory?.tokens ?? 0), "", "tokens of MEMORY.md per agent start")}
    </div>
    <div class="mem-row">
      <div class="mem-main">
        <section class="panel">
          <div class="panel-head"><h2>Memory files</h2><span class="faint" style="font-size: 12px">${app.project ? `global files and ${app.project}'s own` : "global files reach every project through its folder link; pick a project above for its own files"}</span></div>
          <div class="table"><div class="rows">
            <div class="thead file-row"><div class="m-file">FILE</div><div class="m-scope">SCOPE</div><div class="m-size">SIZE</div><div class="m-read">PER READ</div><div class="m-when">COMPACTED</div></div>
            ${data.files.length
              ? data.files.map((file) => html`<button type="button" class="trow file-row ${file.name === (state.file ?? "MEMORY.md") ? "on" : ""}" data-file="${file.name}"><span class="m-file mono">${file.name}</span><span class="m-scope"><span class="scope-tag ${file.scope === "project" ? "project" : ""}" style="margin: 0">${file.scope.toUpperCase()}</span></span><span class="m-size mono">${file.name === "DECISIONS.md" ? `${file.entries} e` : `${file.lines} L`}</span><span class="m-read mono">${tokens(file.tokens)}</span><span class="m-when mono ${file.compacted ? "ok-text" : "faint"}">${file.name === "MEMORY.md" ? when(file.compacted) : file.name === "AGENTS.md" ? "n/a" : "never"}</span></button>`)
              : html`<div class="empty">No memory files yet: run harness init.</div>`}
          </div></div>
        </section>
        <div class="viewer-slot">${viewer(data)}</div>
      </div>
      <div class="mem-side">
        <section class="panel">
          <div class="panel-head"><h2>Link health</h2><span class="end mono ${broken ? "danger-text" : "ok-text"}" style="font-size: 11px">${broken ? `${broken} broken` : "intact"}</span></div>
          <div class="lh-list">${links.projects.length ? links.projects.map(linkCard) : html`<div class="empty">No project yet: run harness init inside a repo.</div>`}</div>
        </section>
        ${links.nearby.map((found) => html`<section class="nearby"><div class="nb-head">${icon("folder", { size: 15, stroke: "var(--warn)", width: 1.6 })}<h2>Store found nearby</h2></div><p><span class="mono">${found.repo.split("/").pop()}/.harness/</span> holds ${found.tickets} ticket files and ${found.plans} plans this store does not know about.</p><button class="btn small" type="button" data-link="adopt" data-path="${found.repo}">Adopt and link</button></section>`)}
        <p class="faint" style="font-size: 12px; margin: 0">Why a folder link and not hard links: folders cannot be hard-linked, and a hard-linked file goes stale on every atomic save or status move. The folder link keeps both paths live, works across disks, and <span class="mono">harness doctor --fix</span> restores it.</p>
      </div>
    </div>
    <section class="panel">
      <div class="panel-head"><h2>Ticket index</h2><span class="faint" style="font-size: 12px">every ticket in the store, by id</span>
        <div class="segmented end" role="group" aria-label="Show">${[["all", "All"], ["running", "Running"], ["done", "Done"]].map(([key, label]) => html`<button type="button" data-show="${key}" aria-pressed="${state.show === key ? "true" : "false"}">${label}</button>`)}</div></div>
      <div class="table"><div class="rows idx-rows">
        <div class="thead idx-row"><span class="i-id">ID</span><span class="i-title">TITLE</span><span class="i-proj">PROJECT</span><span class="i-folder">FOLDER</span><span class="i-loops">LOOPS</span><span class="i-models">MODELS THAT TOUCHED IT</span><span class="i-closed">CLOSED</span></div>
        <div class="idx-body">${indexBody(data)}</div>
      </div></div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2>Writes to memory</h2><span class="faint" style="font-size: 12px">who changed the shared files, and why</span></div>
      <div class="writes">${data.writes.length ? data.writes.map(write) : html`<div class="empty" style="padding: 0">Nothing written yet. Agents add facts with harness memory add; compaction and ticket moves show here too.</div>`}</div>
    </section>
  </div>`;
}

export function foot() {
  return html`<div class="foot-card"><div class="nav-title">BACKEND</div><div class="foot-rows sans">
    <div><span class="dot" style="background: var(--ok)"></span>markdown files<span class="end mono ok-text" style="font-size: 10px">active</span></div>
    <div><span class="dot" style="background: #4a525c"></span>sqlite index<span class="end mono faint" style="font-size: 10px">planned</span></div>
    <div><span class="dot" style="background: #4a525c"></span>vector recall<span class="end mono faint" style="font-size: 10px">planned</span></div>
  </div></div>`;
}

export function bind(root, app, data, bar) {
  const body = root.querySelector(".idx-body");
  const compact = async (button) => {
    button.disabled = true;
    button.textContent = "Compacting…";
    const done = await app.post("/api/memory/compact", {});
    if (done) app.toast("Compaction runs in the background; this page updates when it ends.");
  };
  bar.querySelector("#mq")?.addEventListener("input", (event) => {
    state.find = event.target.value;
    mount(body, indexBody(data));
  });
  bar.querySelector("[data-compact]")?.addEventListener("click", (event) => compact(event.currentTarget));
  bar.querySelector("[data-verify]")?.addEventListener("click", async () => {
    const links = await get("/api/links").catch((error) => app.toast(error.message, true));
    if (!links) return;
    app.toast(`Links checked: ${links.intact} of ${links.total} intact${links.nearby.length ? `, ${links.nearby.length} store found nearby` : ""}.`);
    app.refresh();
  });
  root.addEventListener("click", async (event) => {
    const file = event.target.closest("[data-file]");
    if (file) {
      state.file = file.dataset.file;
      root.querySelectorAll("[data-file]").forEach((row) => row.classList.toggle("on", row === file));
      return mount(root.querySelector(".viewer-slot"), viewer(data));
    }
    const show = event.target.closest("[data-show]");
    if (show) {
      state.show = show.dataset.show;
      root.querySelectorAll("[data-show]").forEach((b) => b.setAttribute("aria-pressed", b === show ? "true" : "false"));
      return mount(body, indexBody(data));
    }
    const button = event.target.closest("button[data-compact]");
    if (button) return compact(button);
    const open = event.target.closest("[data-relink-open]");
    if (open) {
      state.relink = open.dataset.relinkOpen;
      await app.refresh();
      return document.getElementById(`to-${state.relink}`)?.focus();
    }
    const link = event.target.closest("[data-link]");
    if (link) {
      if (link.dataset.link === "adopt" && link.dataset.armed !== "1") {
        link.dataset.armed = "1";
        link.textContent = "Confirm adopt";
        return;
      }
      link.disabled = true;
      const done = await app.post(`/api/links/${link.dataset.link}`, link.dataset.link === "adopt" ? { path: link.dataset.path } : {});
      if (done) app.toast(link.dataset.link === "adopt" ? "Adopted and linked." : "Links repaired.");
    }
  });
  root.addEventListener("submit", async (event) => {
    const form = event.target.closest("form.relink");
    if (!form) return;
    event.preventDefault();
    const done = await app.post("/api/links/relink", { project: form.dataset.project, path: new FormData(form).get("path") });
    if (done) {
      state.relink = "";
      app.toast(`Re-linked ${form.dataset.project}.`);
    }
  });
}
