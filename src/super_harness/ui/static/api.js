// The UI's API client: the token cookie rides along; POSTs carry the X-Harness header.
async function read(response) {
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
      headers: { "Content-Type": "application/json", "X-Harness": "1" },
      body: JSON.stringify(body ?? {}),
    }),
  );
}

export function subscribe(onEvent, onState) {
  const source = new EventSource("/api/events");
  source.addEventListener("journal", (message) => onEvent(JSON.parse(message.data)));
  source.addEventListener("open", () => onState(true));
  source.addEventListener("error", () => onState(false));
  return source;
}
