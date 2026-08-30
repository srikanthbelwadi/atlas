"use client";

import { FormEvent, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { askStream, ApiError } from "@/lib/api";
import { Answer, TraceEvent } from "@/lib/types";

const EXAMPLES = [
  "How did COVID case rates change by year in Alameda County, CA?",
  "Which US counties had the worst air quality last year?",
  "What's the population trend in San Francisco over the last decade?",
];

interface Props {
  busy: boolean;
  onStart: () => void;
  onEvent: (event: TraceEvent) => void;
  onAnswer: (answer: Answer) => void;
  onError: (message: string) => void;
}

export default function AskBar({ busy, onStart, onEvent, onAnswer, onError }: Props) {
  const [question, setQuestion] = useState("");
  const { getIdToken } = useAuth();

  const submit = async (q: string) => {
    if (!q.trim() || busy) return;
    onStart();
    try {
      const token = await getIdToken();
      if (!token) throw new ApiError(401, "Not signed in");
      for await (const event of askStream(q.trim(), token)) {
        onEvent(event);
        if (event.event === "answer") onAnswer(event.data as unknown as Answer);
        if (event.event === "error") onError((event.data.message as string) || "Something went wrong.");
      }
    } catch (err) {
      if (err instanceof ApiError) onError(err.message);
      else onError("Couldn't reach Atlas. Try again in a moment.");
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
