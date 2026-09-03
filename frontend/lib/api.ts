import { AdminUser, Pack, PackCatalog, TraceEvent, TraceEventName } from "./types";

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
export async function* askStream(
  question: string,
  token: string,
  opts: { pack?: Pack; signal?: AbortSignal } = {},
): AsyncGenerator<TraceEvent> {
  // `pack` is only sent when it's not the public default, so the request
  // body the public demo sends today is byte-for-byte unchanged.
  const body: Record<string, unknown> = { question };
  if (opts.pack && opts.pack !== "public") body.pack = opts.pack;
  yield* sseStream("/ask", body, token, opts.signal);
}

/** Finance pack: POST /skills/filing-fact-check — same SSE shape as /ask plus claim.* events. */
export async function* factCheckStream(text: string, token: string, signal?: AbortSignal): AsyncGenerator<TraceEvent> {
  yield* sseStream("/skills/filing-fact-check", { text, pack: "finance" }, token, signal);
}

async function* sseStream(path: string, body: Record<string, unknown>, token: string, signal?: AbortSignal): AsyncGenerator<TraceEvent> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
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

  // sse-starlette (the library backing /ask) encodes every field with "\r\n",
  // so a frame boundary is "\r\n\r\n" — never a bare "\n\n". This parser used
  // to search only for "\n\n", which never matched: every event, including
  // the terminal "answer"/"error", sat unparsed in `buffer` for the whole
  // request and was silently dropped when the stream closed. That's the real
  // root cause behind "stuck at Asking..." — no event ever reached onEvent,
  // regardless of what the backend actually did. Matching either separator
  // (and splitting frame lines on either "\r\n" or "\n") makes this robust to
  // both sse-starlette's own wire format and a bare-"\n" SSE producer.
  const FRAME_SEP = /\r\n\r\n|\n\n/;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let match: RegExpMatchArray | null;
    while ((match = buffer.match(FRAME_SEP))) {
      const sepIndex = match.index as number;
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + match[0].length);
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
  for (const line of frame.split(/\r\n|\n/)) {
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

// --- packs ---------------------------------------------------------------

export async function getPackCatalog(pack: Pack, token: string): Promise<PackCatalog> {
  const res = await authedFetch(`/packs/${pack}/catalog`, token);
  return res.json();
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
