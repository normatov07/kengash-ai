// The UI's API client: the token cookie rides along; POSTs carry the X-Kengash header.
async function read(response) {
  if (response.status === 401) throw new Error("This page is signed out: open the link that kengash ui open printed");
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
  return data;
}

export async function get(path) {
  return read(await fetch(path, { credentials: "same-origin" }));
}

export async function post(path, body) {
  return read(
    await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Kengash": "1" },
      body: JSON.stringify(body ?? {}),
    }),
  );
}

// The journal stream. It closes when the page is hidden (navigation, back-forward cache) so
// stale tabs never hold one of the browser's few connections to the server, and reopens when
// the page shows again.
export function subscribe(onEvent, onState) {
  let source = null;
  const open = () => {
    source?.close();
    source = new EventSource("/api/events");
    source.addEventListener("journal", (message) => onEvent(JSON.parse(message.data)));
    source.addEventListener("open", () => onState(true));
    source.addEventListener("error", () => onState(false));
  };
  window.addEventListener("pagehide", () => {
    source?.close();
    source = null;
    onState(false);
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted || !source) open();
  });
  open();
}
