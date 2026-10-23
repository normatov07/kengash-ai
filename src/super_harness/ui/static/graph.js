// The workflow graph (SP5 spec decision 10): automatic left-to-right layout from the trigger
// through each step to done; solid edges pass forward, dashed on_fail edges send a ticket back.
import { html } from "./html.js";

const W = 150;
const H = 64;
const GAP = 46;
const PAD = 24;
const DIP = 46; // how far below the row a send-back edge curves

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

export function layout(steps, onFail) {
  const ids = ["trigger", ...steps, "done"];
  const nodes = ids.map((id, col) => ({ id, col, x: PAD + col * (W + GAP), y: PAD }));
  const edges = [];
  for (let i = 0; i + 1 < ids.length; i++) edges.push({ from: ids[i], to: ids[i + 1], kind: "pass" });
  for (const [from, to] of Object.entries(onFail)) edges.push({ from, to, kind: "back" });
  const backs = edges.filter((edge) => edge.kind === "back").length;
  return { columns: ids.length, nodes, edges, width: PAD * 2 + ids.length * W + (ids.length - 1) * GAP, height: PAD * 2 + H + (backs ? DIP : 0) };
}

function backPath(from, to, index) {
  const x1 = from.x + W / 2 - 10;
  const x2 = to.x + W / 2 + 10;
  const y = from.y + H;
  const depth = DIP - 8 + index * 6;
  return `M${x1} ${y} C${x1} ${y + depth} ${x2} ${y + depth} ${x2} ${y + 6}`;
}

// sub(id): the node's second line, e.g. the step's CLI; off(id): the step is skipped.
export function svg(graph, { selected = "", sub = () => "", off = () => false } = {}) {
  const at = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
  const backs = graph.edges.filter((edge) => edge.kind === "back");
  return html`<svg class="graph" width="${graph.width}" height="${graph.height}" viewBox="0 0 ${graph.width} ${graph.height}" role="img" aria-label="Workflow graph">
    <defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#5A646F"/></marker>
    <marker id="arrow-back" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="#F0883E"/></marker></defs>
    ${graph.edges.filter((edge) => edge.kind === "pass").map((edge) => {
      const from = at[edge.from];
      const to = at[edge.to];
      return html`<line x1="${from.x + W}" y1="${from.y + H / 2}" x2="${to.x - 3}" y2="${to.y + H / 2}" stroke="#5A646F" stroke-width="1.4" marker-end="url(#arrow)"/>`;
    })}
    ${backs.map((edge, i) => html`<path d="${backPath(at[edge.from], at[edge.to], i)}" fill="none" stroke="#F0883E" stroke-width="1.3" stroke-dasharray="5 4" marker-end="url(#arrow-back)"><title>${LABELS[edge.from] ?? edge.from} sends back to ${LABELS[edge.to] ?? edge.to}</title></path>`)}
    ${graph.nodes.map((node, i) => {
      const fixed = node.id === "trigger" || node.id === "done";
      const classes = ["node", fixed ? "fixed" : "", node.id === selected ? "selected" : "", off(node.id) ? "off" : ""].join(" ");
      const title = fixed ? LABELS[node.id] : `${i} · ${LABELS[node.id] ?? node.id}`;
      return html`<g class="${classes}" data-node="${fixed ? "" : node.id}" tabindex="${fixed ? "-1" : "0"}" transform="translate(${node.x} ${node.y})">
        <rect width="${W}" height="${H}" rx="9"/>
        <text x="12" y="25" class="node-title">${title}</text>
        <text x="12" y="45" class="node-sub">${off(node.id) ? "off · skipped" : sub(node.id)}</text>
      </g>`;
    })}
  </svg>`;
}
