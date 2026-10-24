// Configure screens (Settings, Agents, Workflow): the scope tabs (the defaults or one
// project, SP5 spec decision 8), set-here marks, and the edit → Save · Discard · Reset flow.
import { get } from "./api.js";
import { html } from "./html.js";
import { icon } from "./icons.js";

export function pick(values, key) {
  return key.split(".").reduce((node, part) => (node == null ? undefined : node[part]), values);
}

export function scopeOf(app) {
  return app.scope ?? app.project ?? "";
}

export async function loadScoped(app, path, query = "") {
  return get(`${path}?project=${encodeURIComponent(scopeOf(app))}${query}`);
}

function setMark(on) {
  return on ? html`<div class="set-note">set here</div>` : "";
}

export function field({ key, label, value, setHere, min = 0, max, step = 1, wide = false }) {
  const id = `f-${key.replaceAll(".", "-")}`;
  return html`<div class="field ${setHere ? "set" : ""} ${wide ? "wide" : ""}">
    <label for="${id}">${label}</label>
    <input id="${id}" class="mono" type="number" data-key="${key}" data-kind="number" data-initial="${value}" value="${value}" min="${min}" ${max === undefined ? "" : html`max="${max}"`} step="${step}">
    ${setMark(setHere)}
  </div>`;
}

export function text({ key, label, value, setHere, placeholder = "", list = "" }) {
  const id = `f-${key.replaceAll(".", "-")}`;
  return html`<div class="field wide ${setHere ? "set" : ""}">
    <label for="${id}">${label}</label>
    <input id="${id}" class="mono" type="text" data-key="${key}" data-kind="text" data-initial="${value ?? ""}" value="${value ?? ""}" placeholder="${placeholder}" ${list ? html`list="${list}"` : ""}>
    ${setMark(setHere)}
  </div>`;
}

export function check({ key, label, value, setHere }) {
  return html`<label class="check ${setHere ? "set" : ""}"><input type="checkbox" data-key="${key}" data-kind="bool" data-initial="${value ? "1" : ""}" ${value ? "checked" : ""}>${label}${setHere ? html`<span class="set-note inline">set here</span>` : ""}</label>`;
}

export function tabs(app, projects) {
  const current = scopeOf(app);
  return html`<div class="segmented" role="group" aria-label="Scope">${[["", "Defaults"], ...projects.map((p) => [p, p])].map(
    ([value, label]) => html`<button type="button" data-scope="${value}" aria-pressed="${value === current ? "true" : "false"}">${label}</button>`,
  )}</div>`;
}

// The canvas's config top bar: scope select, a note, the overrides badge, Discard/Reset, Save.
export function configBar(app, projects, setHere, { note, save = "Save to SETTINGS.md", reset = false } = {}) {
  const scope = scopeOf(app);
  const count = setHere.length;
  return html`<label class="sr-only" for="scope">Scope</label>
    <select id="scope" class="select" data-scope-select>${[["", "defaults"], ...projects.map((p) => [p, p])].map(([value, label]) => html`<option value="${value}" ${value === scope ? "selected" : ""}>${label}</option>`)}</select>
    ${scope ? html`<span class="pill ok">${icon("check", { size: 11, width: 1.8 })}${count} ${count === 1 ? "override" : "overrides"}</span>` : ""}
    <span class="note">${note ?? (scope ? "inherits defaults unless overridden" : "editing the defaults every new project copies")}</span>
    <span class="spacer"></span>
    ${reset && scope && count ? html`<button class="btn quiet" type="button" data-reset>Reset</button>` : ""}
    <button class="btn quiet" type="button" data-discard disabled>Discard</button>
    <button class="btn accent sans-btn" type="button" data-save disabled>${save}</button>`;
}

export function actions(app, setHere) {
  const scope = scopeOf(app);
  const count = setHere.length;
  return html`<div class="head-actions">
    <span class="faint" style="font-size: 12px">${scope ? `${count} ${count === 1 ? "override" : "overrides"}` : "editing the defaults every new project copies"}</span>
    ${scope && count ? html`<button class="btn ghost small" type="button" data-reset>Reset</button>` : ""}
    <button class="btn ghost small" type="button" data-discard disabled>Discard</button>
    <button class="btn primary small" type="button" data-save disabled>Save to SETTINGS.md</button>
  </div>`;
}

function current(input) {
  if (input.dataset.kind === "bool") return input.checked;
  if (input.dataset.kind === "number") return input.value === "" ? null : Number(input.value);
  return input.value;
}

function initial(input) {
  if (input.dataset.kind === "bool") return input.dataset.initial === "1";
  if (input.dataset.kind === "number") return Number(input.dataset.initial);
  return input.dataset.initial;
}

export function changes(root) {
  const found = {};
  root.querySelectorAll("[data-key]").forEach((input) => {
    const value = current(input);
    if (value !== initial(input) && value !== null) found[input.dataset.key] = value;
  });
  return found;
}

// extra(): further changes a screen tracks outside its inputs (the workflow graph);
// clear(): forget them, on Discard, a scope switch or a save.
export function bindScope(root, app, { setHere = [], extra = () => ({}), clear = () => {}, bar = null } = {}) {
  const find = (selector) => root.querySelector(selector) ?? bar?.querySelector(selector);
  const save = find("[data-save]");
  const discard = find("[data-discard]");
  const all = () => ({ ...changes(root), ...extra() });
  const dirty = () => {
    const count = Object.keys(all()).length;
    app.dirty = count > 0;
    if (save) save.disabled = !count;
    if (discard) discard.disabled = !count;
  };
  root.addEventListener("input", dirty);
  root.addEventListener("change", dirty);
  const switchTo = (scope) => {
    app.scope = scope;
    app.dirty = false;
    clear();
    app.refresh();
  };
  [root, bar].filter(Boolean).forEach((place) => {
    place.querySelectorAll("[data-scope]").forEach((button) => button.addEventListener("click", () => switchTo(button.dataset.scope)));
    place.querySelector("[data-scope-select]")?.addEventListener("change", (event) => switchTo(event.target.value));
  });
  discard?.addEventListener("click", () => {
    app.dirty = false;
    clear();
    app.refresh();
  });
  const post = async (body, message) => {
    const scope = encodeURIComponent(scopeOf(app));
    app.dirty = false;
    const done = await app.post(`/api/settings?project=${scope}`, body);
    if (done) {
      clear();
      app.toast(message);
    } else dirty();
  };
  save?.addEventListener("click", () => {
    const found = all();
    const keys = Object.keys(found);
    post({ changes: found }, `Saved ${keys.length} ${keys.length === 1 ? "setting" : "settings"} to SETTINGS.md.`);
  });
  const reset = find("[data-reset]");
  reset?.addEventListener("click", () => {
    if (!armed(reset, "Confirm reset")) return;
    post({ changes: Object.fromEntries(setHere.map((key) => [key, null])) }, "Overrides removed; the defaults apply.");
  });
  dirty();
  return { dirty };
}

// A destructive button acts on a second click within 4 s (plan Global Constraints).
export function armed(button, label) {
  if (button.dataset.armed === "1") return true;
  const text = button.textContent;
  button.dataset.armed = "1";
  button.textContent = label;
  setTimeout(() => {
    if (button.isConnected) {
      button.dataset.armed = "";
      button.textContent = text;
    }
  }, 4000);
  return false;
}
