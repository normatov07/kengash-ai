// The canvas's icons (16-unit grid, stroked), drawn inline so nothing is fetched.
import { raw } from "./html.js";

const PATHS = {
  overview: '<rect x="2.3" y="2.3" width="5" height="5" rx="1"/><rect x="8.7" y="2.3" width="5" height="5" rx="1"/><rect x="2.3" y="8.7" width="5" height="5" rx="1"/><rect x="8.7" y="8.7" width="5" height="5" rx="1"/>',
  board: '<rect x="2" y="2.5" width="3.4" height="11" rx="1"/><rect x="6.3" y="2.5" width="3.4" height="7.4" rx="1"/><rect x="10.6" y="2.5" width="3.4" height="9.2" rx="1"/>',
  workflow: '<rect x="1.4" y="5.6" width="5" height="5" rx="1.2"/><rect x="9.6" y="5.6" width="5" height="5" rx="1.2"/><path d="M6.4 8.1h3.2"/>',
  agents: '<circle cx="8" cy="5.6" r="2.6"/><path d="M3.2 13.6c0-2.5 2.2-4.1 4.8-4.1s4.8 1.6 4.8 4.1"/>',
  memory: '<rect x="2.4" y="3" width="11.2" height="10" rx="1.6"/><path d="M5.4 6.2h5.2M5.4 9.2h3"/>',
  settings: '<circle cx="8" cy="8" r="2.5"/><path d="M8 1.6v2.2M8 12.2v2.2M1.6 8h2.2M12.2 8h2.2M3.5 3.5l1.5 1.5M11 11l1.5 1.5M12.5 3.5 11 5M5 11l-1.5 1.5"/>',
  plus: '<path d="M8 3.4v9.2M3.4 8h9.2"/>',
  "plus-square": '<rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="M5.5 8h5M8 5.5v5"/>',
  play: '<path d="M4 3.2 12.4 8 4 12.8z"/>',
  stop: '<rect x="4" y="4" width="8" height="8" rx="1.5"/>',
  chevron: '<path d="M4 6.5 8 10.5l4-4"/>',
  more: '<circle cx="4" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12" cy="8" r="1.3"/>',
  warning: '<path d="M8 2.2 14.4 13H1.6z"/><path d="M8 6.4v3M8 11.2h.01"/>',
  bang: '<path d="M8 3.4v6M8 12.2h.01"/>',
  check: '<path d="M3.4 8.4 6.6 11.6 12.8 5"/>',
  close: '<path d="M4 4l8 8M12 4l-8 8"/>',
  pencil: '<path d="M11 2.6 13.4 5 5.4 13H3v-2.4z"/>',
  trash: '<path d="M3.4 5h9.2M6.4 5V3.4h3.2V5M5 5l.6 8h4.8L11 5"/>',
  link: '<path d="M6.4 9.6 9.6 6.4"/><path d="M4.8 7.2 3.6 8.4a2.3 2.3 0 0 0 3.2 3.2l1.2-1.2M11.2 8.8l1.2-1.2a2.3 2.3 0 0 0-3.2-3.2L8 5.6"/>',
  "link-broken": '<path d="M6.6 9.4 9.4 6.6"/><path d="M5 7.4 3.6 8.8a2.3 2.3 0 0 0 3.2 3.2l1-1M11 8.6l1.4-1.4a2.3 2.3 0 0 0-3.2-3.2l-1 1"/><path d="M2 2l12 12"/>',
  folder: '<path d="M2.4 4.4h4l1.2 1.6h6v6.4a1 1 0 0 1-1 1h-10a1 1 0 0 1-1-1z"/>',
  minus: '<path d="M3.4 8h9.2"/>',
  fit: '<path d="M3 6V3h3M13 10v3h-3M13 6V3h-3M3 10v3h3"/>',
  trigger: '<path d="M8.8 1.6 3.6 9.2h3.2l-.8 5.2 5.4-7.8H8.2z"/>',
  plan: '<path d="M4 2.4h5.2L12 5.2v8.4H4z"/><path d="M6.2 7.4h3.6M6.2 10h2.4"/>',
  review: '<path d="M1.8 8S4 4.2 8 4.2 14.2 8 14.2 8 12 11.8 8 11.8 1.8 8 1.8 8z"/><circle cx="8" cy="8" r="1.8"/>',
  implement: '<path d="M5.8 5.4 3 8l2.8 2.6M10.2 5.4 13 8l-2.8 2.6"/>',
  security: '<path d="M8 1.8 13.4 3.6v4.6c0 3-2.4 5-5.4 6-3-1-5.4-3-5.4-6V3.6z"/>',
  person: '<circle cx="8" cy="5.4" r="2.4"/><path d="M3.4 13.4c0-2.3 2-3.8 4.6-3.8s4.6 1.5 4.6 3.8"/>',
};

// Which icon each workflow step shows.
export const STEP_ICONS = {
  trigger: "trigger",
  plan: "plan",
  review_plan: "review",
  implement: "implement",
  review_code: "review",
  security: "security",
  run_tests: "check",
  docs: "plan",
  approve: "person",
  done: "check",
};

export function icon(name, { size = 16, stroke = "currentColor", width = 1.5, label = "" } = {}) {
  const a11y = label ? `role="img" aria-label="${label.replace(/"/g, "&quot;")}"` : 'aria-hidden="true"';
  return raw(`<svg width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${a11y}>${PATHS[name] ?? ""}</svg>`);
}

export function brand() {
  return raw('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F0883E" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M12 2.6 20.4 7.3v9.4L12 21.4 3.6 16.7V7.3z"/><path d="M12 21.4v-9.2M3.6 7.3 12 12.2l8.4-4.9"/></svg>');
}
