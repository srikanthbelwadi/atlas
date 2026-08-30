import { AdminUser, TraceEvent, TraceEventName } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_ATLAS_API_BASE_URL || "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function authedFetch(path: string, token: string, init: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res;
}

/**
 * Streams the live query trace + final answer from POST /ask.
 *
 * Native `EventSource` can't send an Authorization header, and the backend
 * requires a Firebase ID token on every request — so this parses the SSE
 * wire format (`event: ...\ndata: ...\n\n`) by hand off a `fetch` response
 * body reader instead of using EventSource.
 */
export async function* askStream(question: string, token: string, signal?: AbortSignal): AsyncGenerator<TraceEvent> {
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || res.statusText || "Stream failed to start");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let seq = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      const parsed = parseSseFrame(rawEvent);
      if (parsed) {
        yield { ...parsed, id: `${seq++}` };
        if (parsed.event === "answer" || parsed.event === "error") return;
      }
    }
  }
}

function parseSseFrame(frame: string): { event: TraceEventName; data: Record<string, unknown> } | null {
  let eventName: string | null = null;
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!eventName) return null;
  try {
    return { event: eventName as TraceEventName, data: JSON.parse(dataLines.join("\n") || "{}") };
  } catch {
    return { event: eventName as TraceEventName, data: {} };
  }
}

// --- admin console -------------------------------------------------------

export async function adminListUsers(token: string): Promise<AdminUser[]> {
  const res = await authedFetch("/admin/users", token);
  const body = await res.json();
  return body.users;
}

export async function adminSetUserStatus(token: string, uid: string, action: "approve" | "reject"): Promise<void> {
  await authedFetch(`/admin/users/${uid}/${action}`, token, { method: "POST" });
}

export async function adminGetUsage(token: string, uid: string): Promise<{ estimated_cost_usd: number; query_count: number }> {
  const res = await authedFetch(`/admin/usage/${uid}`, token);
  return res.json();
}
