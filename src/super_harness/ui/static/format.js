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
