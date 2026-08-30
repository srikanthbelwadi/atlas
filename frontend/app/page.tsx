"use client";

import { useState } from "react";
import Header from "@/components/Header";
import SignInGate from "@/components/SignInGate";
import AskBar from "@/components/AskBar";
import TracePanel from "@/components/TracePanel";
import AnswerCanvas from "@/components/AnswerCanvas";
import { Answer, TraceEvent } from "@/lib/types";

export default function Home() {
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleStart = () => {
    setBusy(true);
    setEvents([]);
    setAnswer(null);
    setError(null);
  };

  const handleEvent = (event: TraceEvent) => {
    setEvents((prev) => [...prev, event]);
    if (event.event === "answer" || event.event === "error") setBusy(false);
  };

  const handleAnswer = (a: Answer) => setAnswer(a);

  const handleError = (message: string) => {
    setError(message);
    setBusy(false);
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

          {answer && <AnswerCanvas answer={answer} />}
        </main>
      </SignInGate>
    </>
  );
}
