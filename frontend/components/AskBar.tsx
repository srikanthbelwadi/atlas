"use client";

import { FormEvent, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { askStream, ApiError } from "@/lib/api";
import { Answer, TraceEvent } from "@/lib/types";

const EXAMPLES = [
  "How did COVID case rates change by year in Alameda County, CA?",
  "Which US counties had the worst air quality last year?",
  "What's the population trend in San Francisco over the last decade?",
  // Added after a 10-question live evaluation of backend routing + frontend
  // rendering (see /home/claude/test_results.md) — these three passed end
  // to end with no crashes and a correct, well-cited answer, and between
  // them exercise the three viz shapes the original examples didn't: a
  // single-stat KPI, a multi-stat KPI grid, and a many-category bar chart.
  "What was the average temperature in Chicago in 2023?",
  "What are the most common types of crime reported in Chicago?",
  "Which candidates raised the most money in federal campaign contributions recently?",
];

interface Props {
  busy: boolean;
  onStart: () => void;
  onEvent: (event: TraceEvent) => void;
  onAnswer: (answer: Answer) => void;
  // `errorData` carries the raw "error" event payload (which includes
  // `walkthrough` — see pipeline.py) when there was one, so the caller can
  // still show a full walkthrough on a failed question, not just the
  // message. It's null for client-side failures (auth, network) that never
  // reached the backend and so have no walkthrough to show.
  onError: (message: string, errorData: Record<string, unknown> | null) => void;
}

export default function AskBar({ busy, onStart, onEvent, onAnswer, onError }: Props) {
  const [question, setQuestion] = useState("");
  const { getIdToken } = useAuth();

  const submit = async (q: string) => {
    if (!q.trim() || busy) return;
    onStart();
    // Tracks whether the stream ever sent a recognized terminal event, so we
    // can tell a clean finish apart from the stream just ending. Without
    // this, a response that closes early — a proxy timeout, a server crash
    // mid-stream, sse-starlette's connection dropping — falls straight
    // through the for-await loop with no exception thrown, `submit()`
    // returns normally, and `busy` is never reset by anything: the "Ask"
    // button is stuck reading "Asking…" forever. Found while debugging the
    // reported "stuck at Asking..." bug — the backend pipeline had its own
    // real bug (see pipeline.py/llm.py), but this gap meant even an
    // unrelated stream hiccup would produce the exact same symptom, so it's
    // fixed here too as defense in depth.
    let sawTerminalEvent = false;
    try {
      const token = await getIdToken();
      if (!token) throw new ApiError(401, "Not signed in");
      for await (const event of askStream(q.trim(), token)) {
        onEvent(event);
        if (event.event === "answer") {
          sawTerminalEvent = true;
          onAnswer(event.data as unknown as Answer);
        }
        if (event.event === "error") {
          sawTerminalEvent = true;
          onError((event.data.message as string) || "Something went wrong.", event.data);
        }
      }
      if (!sawTerminalEvent) {
        onError("The connection ended before Atlas finished answering. Try again.", null);
      }
    } catch (err) {
      if (err instanceof ApiError) onError(err.message, null);
      else onError("Couldn't reach Atlas. Try again in a moment.", null);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(question);
  };

  return (
    <div>
      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 10 }}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question a public dataset can answer…"
          disabled={busy}
          style={{
            flex: 1,
            padding: "14px 16px",
            fontSize: "1rem",
            borderRadius: 10,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--ink)",
          }}
        />
        <button
          type="submit"
          disabled={busy || !question.trim()}
          style={{
            padding: "0 22px",
            borderRadius: 10,
            border: "none",
            background: busy ? "var(--border)" : "var(--accent)",
            color: busy ? "var(--ink-dim)" : "white",
            fontSize: "0.95rem",
            cursor: busy ? "default" : "pointer",
          }}
        >
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>
      {!busy && (
        <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => submit(ex)}
              style={{
                fontSize: "0.8rem",
                padding: "6px 12px",
                borderRadius: 999,
                border: "1px solid var(--border)",
                background: "var(--surface)",
                color: "var(--ink-dim)",
                cursor: "pointer",
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
