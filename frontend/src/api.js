const API_BASE = `${import.meta.env.BASE_URL}api`.replace(/\/?$/, "");

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = data?.detail ?? response.statusText;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(message);
  }

  return data;
}

function parseSseChunk(buffer, onEvent) {
  const lines = buffer.split("\n");
  const remainder = lines.pop() ?? "";

  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    try {
      const event = JSON.parse(line.slice(6));
      onEvent(event);
    } catch (err) {
      if (err instanceof Error && err.message) {
        throw err;
      }
      // Ignore malformed SSE payloads.
    }
  }

  return remainder;
}

export async function fetchHealth() {
  return request("/health");
}

export async function fetchBedrockCatalog() {
  const catalog = await request("/bedrock/catalog");
  if (!catalog?.regions?.length || !catalog?.models?.length) {
    throw new Error(
      "Bedrock catalog is incomplete. Both regions and models must be configured."
    );
  }
  return catalog;
}

export async function fetchModels() {
  return request("/models");
}

export async function fetchConfig() {
  return request("/config");
}

export async function updateConfig(updates) {
  return request("/config", {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

export async function sendChat(payload) {
  return request("/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Stream chat tokens via SSE. Invokes onStart, onToken, onDone callbacks.
 * Throws on HTTP errors or SSE error events.
 */
export async function sendChatStream(payload, { onStart, onToken, onDone } = {}) {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail ?? response.statusText;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(message);
  }

  if (!response.body) {
    throw new Error("Streaming not supported by the browser.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleEvent = (event) => {
    if (event.type === "start") {
      onStart?.(event);
    } else if (event.type === "token" && event.text) {
      onToken?.(event.text);
    } else if (event.type === "done") {
      onDone?.(event);
    } else if (event.type === "error") {
      throw new Error(event.detail || "Stream error");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    buffer = parseSseChunk(buffer, handleEvent);
  }

  if (buffer) {
    parseSseChunk(`${buffer}\n`, handleEvent);
  }
}
