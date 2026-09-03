"use client";

import { FormEvent, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { factCheckStream, ApiError } from "@/lib/api";
import { Answer, TraceEvent } from "@/lib/types";
import { FACT_CHECK_EXAMPLE } from "@/lib/finance";

interface Props {
  busy: boolean;
  onStart: () => void;
  onEvent: (event: TraceEvent) => void;
  onAnswer: (answer: Answer) => void;
  onError: (message: string, errorData: Record<string, unknown> | null) => void;
}

/**
 * Finance pack, use case B4: paste a paragraph, get a verdict per claim.
 * Same streaming contract as AskBar (start → events → answer | error), but
 * against /skills/filing-fact-check, which never drafts SQL — every claim is
 * checked through an attested computation or marked "not verifiable".
 */
export default function FactCheckBar({ busy, onStart, onEvent, onAnswer, onError }: Props) {
  const [text, setText] = useState(FACT_CHECK_EXAMPLE);
  const { getIdToken } = useAuth();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim() || busy) return;
    onStart();
    let sawTerminal = false;
    try {
      const token = await getIdToken();
      if (!token) throw new ApiError(401, "Not signed in");
      for await (const event of factCheckStream(text.trim(), token)) {
        onEvent(event);
        if (event.event === "answer") {
          sawTerminal = true;
          onAnswer(event.data as unknown as Answer);
        }
        if (event.event === "error") {
          sawTerminal = true;
          onError((event.data.message as string) || "Something went wrong.", event.data);
        }
      }
      if (!sawTerminal) onError("The connection ended before Atlas finished checking. Try again.", null);
    } catch (err) {
      if (err instanceof ApiError) onError(err.message, null);
      else onError("Couldn't reach Atlas. Try again in a moment.", null);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <textarea
        className="fact-check-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={busy}
        maxLength={4000}
        placeholder="Paste a paragraph with figures about a public company's reported financials…"
      />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.8rem", color: "var(--ink-dim)" }}>
          Each claim is checked only through attested computations (SEC EDGAR + the SEC bulk data set). Claims with no attested
          path are marked not verifiable — never guessed.
        </span>
        <button type="submit" disabled={busy || !text.trim()} className="cta-button" style={{ padding: "10px 20px" }}>
          {busy ? "Checking…" : "Check claims"}
        </button>
      </div>
    </form>
  );
}
