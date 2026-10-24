// Templates that escape every interpolated value; only html`` results and raw() pass through.
class Raw {
  constructor(text) {
    this.text = text;
  }
}

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

function part(value) {
  if (value instanceof Raw) return value.text;
  if (Array.isArray(value)) return value.map(part).join("");
  if (value === null || value === undefined || value === false) return "";
  return esc(value);
}

export function html(strings, ...values) {
  let out = strings[0];
  values.forEach((value, i) => {
    out += part(value) + strings[i + 1];
  });
  return new Raw(out);
}

export function raw(text) {
  return new Raw(String(text));
}

export function render(template) {
  return part(template);
}

export function mount(element, template) {
  element.innerHTML = part(template);
}
