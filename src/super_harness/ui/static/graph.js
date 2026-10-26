// The workflow graph (SP5 spec decision 10, canvas board Workflow): automatic layout from the
// trigger down through each step to done on a dotted canvas; solid edges pass forward, dashed
// on_fail edges leave a step's right port and run up a lane on the right to an earlier step.
import { html } from "./html.js";
import { STEP_ICONS, icon } from "./icons.js";

const X = 112;
const W = 240;
const H = 76;
const PITCH = 140;
const TOP = 24;
const LANE = 80;

export const LABELS = {
  trigger: "Trigger",
  done: "Done",
  plan: "Plan",
  review_plan: "Review plan",
  implement: "Implement",
  review_code: "Review code",
  security: "Security review",
  run_tests: "Run tests",
  docs: "Docs",
  approve: "Human approval",
};

// Icon tile colours per step: [tile background, stroke].
export const TONES = {
  trigger: ["#22262C", "#A7B0BC"],
  plan: ["#1B2733", "#68A4E0"],
  review_plan: ["#241F33", "#B191E8"],
  implement: ["#2A1E10", "#F0883E"],
  review_code: ["#241F33", "#B191E8"],
  security: ["#2A2320", "#D8B24C"],
  run_tests: ["#1E2A20", "#5FC08B"],
  docs: ["#1E2A20", "#5FC08B"],
  approve: ["#3A2024", "#EF7A72"],
  done: ["#1E2A20", "#5FC08B"],
};

const PASS = { review_plan: "pass", review_code: "pass", security: "signed off", run_tests: "green" };
const BACK = { review_plan: "revise", review_code: "findings", security: "blocked", run_tests: "failing", approve: "rejected" };

// Rows from the trigger to done, one pass edge between neighbours, one back edge per on_fail.
// Custom steps (SP6) borrow the label style, colours and icon of their kind's built-in step.
const KIND_STEP = { review: "review_code", edit: "implement", read: "plan" };
export function learnSteps(kinds = {}) {
  for (const [step, kind] of Object.entries(kinds)) {
    if (step in LABELS || !KIND_STEP[kind]) continue;
    LABELS[step] = step.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
    TONES[step] = TONES[KIND_STEP[kind]];
    STEP_ICONS[step] = STEP_ICONS[KIND_STEP[kind]];
  }
}

export function layout(steps, onFail) {
  const ids = ["trigger", ...steps, "done"];
  const nodes = ids.map((id, col) => ({ id, col, x: X, y: TOP + col * PITCH }));
  const edges = [];
  for (let i = 0; i + 1 < ids.length; i++) edges.push({ from: ids[i], to: ids[i + 1], kind: "pass" });
  for (const [from, to] of Object.entries(onFail)) edges.push({ from, to, kind: "back" });
  return { columns: ids.length, nodes, edges };
}

function geometry(graph) {
  const at = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
  const backs = graph.edges
    .filter((edge) => edge.kind === "back" && at[edge.from] && at[edge.to])
    .map((edge) => ({ ...edge, span: Math.abs(at[edge.from].col - at[edge.to].col) }))
    .sort((a, b) => a.span - b.span)
    .map((edge, lane) => ({ ...edge, lane: X + W + 40 + lane * LANE }));
  const width = Math.max(720, (backs.at(-1)?.lane ?? X + W) + 140);
  const height = TOP * 2 + (graph.nodes.length - 1) * PITCH + H;
  return { at, backs, width, height };
}

// sub(id): the node's second line; off(id): the step is skipped; ghost: a step shown as
// "not wired in" beside done.
export function canvas(graph, { selected = "", sub = () => "", off = () => false, gate = () => false, ghost = "" } = {}) {
  const { at, backs, width, height } = geometry(graph);
  const pass = graph.edges.filter((edge) => edge.kind === "pass");
  const done = at.done;
  return html`<div class="wf-canvas" style="width: ${width}px; height: ${height}px">
    <svg class="wf-edges" width="${width}" height="${height}" aria-hidden="true">
      <defs><marker id="wf-pass" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill="#5A646F"/></marker>
      <marker id="wf-back" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6 Z" fill="#8E6B5E"/></marker></defs>
      ${pass.map((edge) => {
        const [a, b] = [at[edge.from], at[edge.to]];
        return html`<line x1="${a.x + W / 2}" y1="${a.y + H + 5}" x2="${b.x + W / 2}" y2="${b.y - 9}" stroke="#5A646F" stroke-width="2" stroke-linecap="round" marker-end="url(#wf-pass)"/>`;
      })}
      ${backs.map((edge) => {
        const [a, b] = [at[edge.from], at[edge.to]];
        const [y1, y2] = [a.y + 52, b.y + 22];
        return html`<path d="M${a.x + W + 5} ${y1} H${edge.lane} V${y2} H${b.x + W + 12}" fill="none" stroke="#8E6B5E" stroke-width="2" stroke-dasharray="6 5" stroke-linejoin="round" marker-end="url(#wf-back)"><title>${LABELS[edge.from] ?? edge.from} sends back to ${LABELS[edge.to] ?? edge.to}</title></path>`;
      })}
    </svg>
    ${pass.map((edge) => (PASS[edge.from] ? html`<div class="wf-label" style="left: ${X + W / 2 + 12}px; top: ${at[edge.from].y + H + 24}px">${PASS[edge.from]}</div>` : ""))}
    ${backs.map((edge) => html`<div class="wf-label back" style="left: ${edge.lane + 8}px; top: ${(at[edge.from].y + 52 + at[edge.to].y + 22) / 2 - 8}px">${BACK[edge.from] ?? "send back"}</div>`)}
    ${graph.nodes.map((node, i) => {
      const fixed = node.id === "trigger" || node.id === "done";
      const [tile, stroke] = TONES[node.id] ?? TONES.trigger;
      const outBack = backs.some((edge) => edge.from === node.id);
      const inBack = backs.some((edge) => edge.to === node.id);
      const classes = ["wf-node", node.id === "trigger" ? "trigger" : "", node.id === "done" ? "done" : "", gate(node.id) ? "gate" : "", node.id === selected ? "selected" : "", off(node.id) ? "off" : ""].join(" ");
      return html`<div class="${classes}" style="left: ${node.x}px; top: ${node.y}px" ${fixed ? "" : html`data-node="${node.id}" tabindex="0" role="button" aria-pressed="${node.id === selected ? "true" : "false"}"`}>
        ${node.id !== "trigger" ? html`<span class="port p-top"></span>` : ""}${inBack ? html`<span class="port p-in"></span>` : ""}${outBack ? html`<span class="port p-out"></span>` : ""}${node.id !== "done" ? html`<span class="port p-bottom ${node.id === selected ? "lit" : ""}"></span>` : ""}
        <span class="wf-icon" style="background: ${tile}">${icon(STEP_ICONS[node.id] ?? "plan", { size: 15, stroke, width: 1.6 })}</span>
        <span class="wf-text"><b>${fixed ? LABELS[node.id] : `${i} · ${LABELS[node.id] ?? node.id}`}</b><span class="mono ${gate(node.id) ? "gate-sub" : ""}">${off(node.id) ? "off · skipped" : sub(node.id)}</span></span>
      </div>`;
    })}
    ${ghost && done ? html`<div class="wf-node ghost" style="left: ${X + W + 88}px; top: ${done.y}px" data-ghost="${ghost}" role="button" tabindex="0" title="Add ${LABELS[ghost]} to this workflow"><span class="port p-top"></span><span class="wf-icon">${icon(STEP_ICONS[ghost], { size: 15, stroke: "#5A646F", width: 1.6 })}</span><span class="wf-text"><b>${LABELS[ghost]}</b><span class="mono">off · not wired in</span></span></div>` : ""}
  </div>`;
}
