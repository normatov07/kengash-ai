import { html } from "./html.js";
// Small display helpers shared by the screens.
export function tokens(count) {
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)}M`;
  if (count >= 1e3) return `${(count / 1e3).toFixed(1)}K`;
  return String(count);
}

export function elapsed(since, now = Date.now()) {
  const seconds = Math.max(0, Math.floor((now - Date.parse(since)) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}h ${pad(m)}m` : `${pad(m)}:${pad(s)}`;
}

export function clock(ts) {
  return new Date(ts).toTimeString().slice(0, 8);
}

export function stepLabel(status) {
  const sub = String(status).split("/")[1] || "";
  const names = {
    under_planning: "planning",
    under_plan_review: "reviewing plan",
    under_implementation: "implementing",
    under_review: "reviewing code",
    under_security_review: "security review",
    under_test: "testing",
    under_docs: "writing docs",
  };
  return names[sub] || sub.replaceAll("_", " ");
}

// Each workflow step's colour and short journal name (canvas step colours).
export const STEPS = {
  plan: { color: "var(--step-plan)", kind: "plan", label: "planning" },
  review_plan: { color: "var(--step-review)", kind: "review", label: "reviewing plan" },
  implement: { color: "var(--step-implement)", kind: "impl", label: "implementing" },
  review_code: { color: "var(--step-review)", kind: "review", label: "reviewing code" },
  security: { color: "var(--step-security)", kind: "security", label: "security review" },
  run_tests: { color: "var(--step-tests)", kind: "tests", label: "testing" },
  docs: { color: "var(--step-tests)", kind: "docs", label: "writing docs" },
  approve: { color: "var(--step-approve)", kind: "approve", label: "awaiting you" },
};

export function stepColor(step) {
  return STEPS[step]?.color ?? "var(--muted)";
}

export function shortTime(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return s >= 3600 ? `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m` : `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// The loops that cover `project` ("" for all projects): those over every project, and its own.
export function loopsIn(loops, project) {
  return project ? loops.filter((loop) => loop.project === null || loop.project === project) : loops;
}

// The Overview's loop line (SP11): which conductors hold a loop lease right now.
export function loopSummary(loops) {
  if (!loops.length) return "no loop running: run /kengash:loop in your agent";
  if (loops.length === 1) return `loop running (${loops[0].agent} · ${loops[0].scope})`;
  return `${loops.length} loops running (${[...new Set(loops.map((loop) => loop.agent))].join(", ")})`;
}

// One row of a worker's live activity (SP12): its local time, kind and text, escaped.
const KIND_LABELS = { step: "step", read: "read", edit: "edit", run: "run", reply: "reply", error: "error", status: "status" };
export function activityRow(item) {
  const time = item.ts ? new Date(item.ts).toTimeString().slice(0, 8) : "--:--:--";
  const label = KIND_LABELS[item.kind] ?? "run";
  return html`<div class="live-row kind-${label}"><span class="live-time mono">${time}</span><span class="live-kind">${label}</span><span class="live-text mono">${item.text}</span></div>`;
}

// Seconds as progress lines print them (SP12): 13s, 5m, 1h05m.
export function span(seconds) {
  const s = Math.max(0, Math.floor(seconds ?? 0));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}
