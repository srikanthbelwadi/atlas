"use client";

import { useState } from "react";
import Header from "@/components/Header";
import SignInGate from "@/components/SignInGate";
import AskBar from "@/components/AskBar";
import TracePanel from "@/components/TracePanel";
import AnswerCanvas from "@/components/AnswerCanvas";
import WalkthroughPanel from "@/components/Walkthrough";
import ErrorBoundary from "@/components/ErrorBoundary";
import { Answer, TraceEvent, Walkthrough } from "@/lib/types";

export default function Home() {
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Populated from either the "answer" event's data.walkthrough or the
  // "error" event's data.walkthrough (see pipeline.py — both terminal
  // events carry one), so a failed question still shows what Atlas tried:
  // sources considered, the actual queries run, and token cost so far.
  const [walkthrough, setWalkthrough] = useState<Walkthrough | null>(null);

  const handleStart = () => {
    setBusy(true);
    setEvents([]);
    setAnswer(null);
    setError(null);
    setWalkthrough(null);
  };

  const handleEvent = (event: TraceEvent) => {
    setEvents((prev) => [...prev, event]);
    if (event.event === "answer" || event.event === "error") setBusy(false);
  };

  const handleAnswer = (a: Answer) => {
    setAnswer(a);
    if (a.walkthrough) setWalkthrough(a.walkthrough);
  };

  const handleError = (message: string, errorData: Record<string, unknown> | null) => {
    setError(message);
    setBusy(false);
    const w = errorData?.walkthrough as Walkthrough | undefined;
    if (w) setWalkthrough(w);
  };

  return (
    <>
      <Header />
      <SignInGate>
        <main className="container" style={{ padding: "40px 0 80px", display: "flex", flexDirection: "column", gap: 24 }}>
          <AskBar busy={busy} onStart={handleStart} onEvent={handleEvent} onAnswer={handleAnswer} onError={handleError} />

          {error && (
            <div
              style={{
                background: "var(--danger-soft)",
                color: "var(--danger)",
                borderRadius: 10,
                padding: "14px 16px",
                fontSize: "0.9rem",
              }}
            >
              {error}
            </div>
          )}

          <TracePanel events={events} />

          {answer && (
            <ErrorBoundary label="answer">
              <AnswerCanvas answer={answer} />
            </ErrorBoundary>
          )}

          {walkthrough && (
            <ErrorBoundary label="walkthrough">
              <WalkthroughPanel walkthrough={walkthrough} />
            </ErrorBoundary>
          )}
        </main>
      </SignInGate>
    </>
  );
}
