// Form controls for the configure screens (SP10 spec §5.1): native elements under the
// theme, so keyboards, screen readers and phones work as they do everywhere. Each control
// is a template function; its bind function wires one rendered control. Free text only
// where the value is free: names, descriptions, instructions, commands.
import { esc, html } from "./html.js";
import { icon } from "./icons.js";

const CLIS = ["claude", "codex", "antigravity"];
const OTHER = "__other";

// `claude/opus` → ["claude", "opus"]; a bare CLI runs its default model.
export function splitCli(cli) {
  const at = cli.indexOf("/");
  return at < 0 ? [cli, "default"] : [cli.slice(0, at), cli.slice(at + 1) || "default"];
}

export function cliValue(provider, model) {
  return model && model !== "default" ? `${provider}/${model}` : provider;
}

// [value, label, disabled] per CLI. One not installed or signed out stays selectable and
// says so, since the agent runs once the user signs in; one the server never reported is
// disabled.
export function cliChoices(cards, current, allowShell = false) {
  const byName = Object.fromEntries(cards.map((card) => [card.name, card]));
  const rows = CLIS.map((name) => {
    const card = byName[name];
    if (!card) return [name, `${name} · not detected`, true];
    if (card.checked === false) return [name, `${name} · checking…`, false];
    if (!card.installed) return [name, `${name} · not installed`, false];
    return [name, card.signed_in ? name : `${name} · signed out`, false];
  });
  if (allowShell || current === "shell") rows.push(["shell", "shell · runs project.test_cmd", false]);
  return rows;
}

// [value, label] per model of a CLI: its default, what the CLI reported, the current value
// when it is none of those, and "Other…" for a name typed by hand.
export function modelChoices(cards, provider, current) {
  const card = cards.find((one) => one.name === provider);
  const names = ["default", ...(card?.models ?? [])];
  if (current && !names.includes(current)) names.push(current);
  return [...names.map((name) => [name, name]), [OTHER, "Other…"]];
}

export function moveItem(list, from, to) {
  if (to < 0 || to >= list.length || from === to) return [...list];
  const copy = [...list];
  const [item] = copy.splice(from, 1);
  copy.splice(to, 0, item);
  return copy;
}

export function counts(text) {
  const trimmed = text.replace(/\n$/, "");
  return { lines: trimmed ? trimmed.split("\n").length : 0, words: text.split(/\s+/).filter(Boolean).length };
}

export function select({ id, name = "", value, options, label = "", data = {} }) {
  return html`<select class="select full" id="${id}" ${name ? html`name="${name}"` : ""} ${label ? html`aria-label="${label}"` : ""} ${dataAttrs(data)}>${options.map(
    ([option, text, disabled]) => html`<option value="${option}" ${String(option) === String(value) ? "selected" : ""} ${disabled ? "disabled" : ""}>${text}</option>`,
  )}</select>`;
}

// A radio group drawn as a segmented control; each option may carry a one-line hint.
export function segmented({ name, value, options, label, disabled = false }) {
  return html`<div class="seg" role="radiogroup" aria-label="${label}">${options.map(
    ([option, text, hint]) => html`<label class="seg-option ${hint ? "has-hint" : ""}"><input type="radio" name="${name}" value="${option}" ${option === value ? "checked" : ""} ${disabled ? "disabled" : ""}><span><b>${text}</b>${hint ? html`<small>${hint}</small>` : ""}</span></label>`,
  )}</div>`;
}

export function toggle({ id, checked, label, hint = "", disabled = false, data = {} }) {
  return html`<label class="toggle" for="${id}"><span class="switch"><input type="checkbox" id="${id}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} ${dataAttrs(data)}><span></span></span><span class="toggle-text">${label}${hint ? html`<small>${hint}</small>` : ""}</span></label>`;
}

// CLI, then that CLI's models; "Other…" opens a text field for a model the list lacks.
export function modelPicker({ id, cards, value, allowShell = false, label = "CLI and model" }) {
  const [provider, model] = splitCli(value);
  const models = modelChoices(cards, provider, model);
  return html`<div class="model-picker" data-model-picker id="${id}" role="group" aria-label="${label}">
    ${select({ id: `${id}-cli`, value: provider, options: cliChoices(cards, provider, allowShell), label: "CLI", data: { part: "cli" } })}
    ${select({ id: `${id}-model`, value: model, options: models, label: "Model", data: { part: "model" } })}
    <input class="text-input mono" id="${id}-other" data-part="other" placeholder="model name (empty: the default)" aria-label="Model name" autocomplete="off" spellcheck="false" hidden>
  </div>`;
}

export function modelValue(picker) {
  const provider = picker.querySelector("[data-part=cli]").value;
  const chosen = picker.querySelector("[data-part=model]").value;
  const model = chosen === OTHER ? picker.querySelector("[data-part=other]").value.trim() : chosen;
  return provider === "shell" ? "shell" : cliValue(provider, model);
}

export function bindModelPicker(picker, cards, onChange) {
  const cli = picker.querySelector("[data-part=cli]");
  const model = picker.querySelector("[data-part=model]");
  const other = picker.querySelector("[data-part=other]");
  const sync = () => {
    other.hidden = model.value !== OTHER;
    model.disabled = cli.value === "shell";
  };
  cli.addEventListener("change", () => {
    model.innerHTML = modelChoices(cards, cli.value, "default").map(([value, text]) => `<option value="${esc(value)}">${esc(text)}</option>`).join("");
    sync();
    onChange(modelValue(picker));
  });
  model.addEventListener("change", () => {
    sync();
    if (model.value === OTHER) other.focus();
    else onChange(modelValue(picker));
  });
  other.addEventListener("input", () => onChange(modelValue(picker))); // empty: the CLI's default
  sync();
}

// An ordered list of chips (fallback CLIs): ✕ removes one, the select adds one, a drag or
// Alt+↑/↓ on a focused chip moves it.
export function chipList({ id, items, options, label, empty = "none" }) {
  const left = options.filter(([value]) => !items.includes(value));
  return html`<div class="chip-list" data-chip-list id="${id}" role="group" aria-label="${label}">
    <ol>${items.length ? items.map(
      (item, i) => html`<li class="chip-item" draggable="true" tabindex="0" data-value="${item}" aria-label="${i + 1}: ${item}. Alt and arrow keys move it."><span class="chip-n">${i + 1}</span><span class="mono">${item.replace("/", " · ")}</span><button type="button" class="chip-x" data-remove aria-label="Remove ${item}">${icon("close", { size: 11, width: 1.8 })}</button></li>`,
    ) : html`<li class="chip-empty">${empty}</li>`}</ol>
    ${left.length ? html`<select class="select chip-add" data-part="add" aria-label="Add to ${label}"><option value="">+ add</option>${left.map(([value, text]) => html`<option value="${value}">${text}</option>`)}</select>` : ""}
  </div>`;
}

export function chipValues(list) {
  return [...list.querySelectorAll(".chip-item")].map((chip) => chip.dataset.value);
}

// `render(items)` redraws the list (the caller keeps its state); `onChange(items)` saves.
export function bindChipList(list, onChange) {
  const items = () => chipValues(list);
  list.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove]");
    if (remove) onChange(items().filter((value) => value !== remove.closest(".chip-item").dataset.value));
  });
  list.addEventListener("change", (event) => {
    if (event.target.dataset.part === "add" && event.target.value) onChange([...items(), event.target.value]);
  });
  list.addEventListener("keydown", (event) => {
    const chip = event.target.closest(".chip-item");
    if (!chip || !event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown" && event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const all = items();
    const from = all.indexOf(chip.dataset.value);
    const to = from + (event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 1);
    if (to >= 0 && to < all.length) onChange(moveItem(all, from, to), chip.dataset.value);
  });
  let dragged = null;
  list.addEventListener("dragstart", (event) => {
    dragged = event.target.closest(".chip-item")?.dataset.value ?? null;
    event.dataTransfer?.setData("text/plain", dragged ?? "");
  });
  list.addEventListener("dragover", (event) => dragged && event.preventDefault());
  list.addEventListener("drop", (event) => {
    const target = event.target.closest(".chip-item");
    if (!dragged || !target) return;
    event.preventDefault();
    const all = items();
    onChange(moveItem(all, all.indexOf(dragged), all.indexOf(target.dataset.value)));
    dragged = null;
  });
}

// Instructions with live counts against the caps kengash checks on save.
export function instructions({ id, value, caps, readonly = false, label = "Instructions" }) {
  const found = counts(value);
  const [lines, words] = caps ?? [0, 0];
  return html`<div class="instructions ${readonly ? "is-readonly" : ""}">
    <textarea class="text-area mono" id="${id}" aria-label="${label}" spellcheck="false" ${readonly ? "readonly" : ""} rows="${Math.min(18, Math.max(8, found.lines + 1))}">${value}</textarea>
    ${readonly ? "" : html`<div class="counts mono" data-counts aria-live="polite">${countText(found, lines, words)}</div>`}
  </div>`;
}

export function bindInstructions(box, caps, onInput) {
  const area = box.querySelector("textarea");
  const out = box.querySelector("[data-counts]");
  const [lines, words] = caps;
  area.addEventListener("input", () => {
    const found = counts(area.value);
    out.textContent = countText(found, lines, words);
    out.classList.toggle("over", found.lines > lines || found.words > words);
    onInput(area.value);
  });
}

function countText(found, lines, words) {
  return `${found.lines} / ${lines} lines · ${found.words} / ${words} words`;
}

// A popover listing agents to insert: a search box, then yours and the built-in ones.
export function agentPicker({ agents, title = "Insert an agent" }) {
  const groups = [["Yours", agents.filter((a) => !a.builtin)], ["Built-in", agents.filter((a) => a.builtin)]];
  return html`<div class="picker" role="dialog" aria-label="${title}" data-agent-picker>
    <label class="picker-search">${icon("search", { size: 13 })}<input type="search" placeholder="${title}…" aria-label="Search agents" data-part="search" autocomplete="off"></label>
    <div class="picker-list" role="listbox" aria-label="Agents">${groups.map(([name, rows]) => rows.length ? html`<div class="picker-group" role="presentation">${name}</div>${rows.map(
      (agent) => html`<button type="button" class="picker-item ${agent.used ? "is-used" : ""}" role="option" data-pick="${agent.step}" data-search="${`${agent.label} ${agent.role} ${agent.kind}`.toLowerCase()}" ${agent.used ? "disabled" : ""}><span class="picker-name">${agent.label}</span><span class="faint">${agent.used ? "in use" : agent.kind}</span></button>`,
    )}` : "")}</div>
    <a class="picker-new" href="#/agents/new">${icon("plus", { size: 12, width: 1.9 })}New agent…</a>
  </div>`;
}

export function bindAgentPicker(picker, onPick, onClose) {
  const search = picker.querySelector("[data-part=search]");
  const options = () => [...picker.querySelectorAll("[data-pick]:not([hidden]):not(:disabled)")];
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    for (const item of picker.querySelectorAll("[data-pick]")) item.hidden = Boolean(query) && !item.dataset.search.includes(query);
  });
  picker.addEventListener("click", (event) => {
    const item = event.target.closest("[data-pick]");
    if (item) onPick(item.dataset.pick);
  });
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape") return onClose();
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Enter") return;
    const list = options();
    const at = list.indexOf(document.activeElement);
    if (event.key === "Enter" && document.activeElement === search && list[0]) {
      event.preventDefault();
      return onPick(list[0].dataset.pick);
    }
    if (event.key === "Enter") return;
    event.preventDefault();
    list[Math.max(0, Math.min(list.length - 1, at + (event.key === "ArrowDown" ? 1 : -1)))]?.focus();
  });
  search.focus();
}

function dataAttrs(data) {
  return Object.entries(data).map(([key, value]) => html` data-${key}="${value}"`);
}
