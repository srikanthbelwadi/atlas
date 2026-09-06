"use client";

import { useState } from "react";
import Header from "@/components/Header";
import SignInGate from "@/components/SignInGate";
import AskBar from "@/components/AskBar";
import TracePanel from "@/components/TracePanel";
import AnswerCanvas from "@/components/AnswerCanvas";
import ReceiptCard from "@/components/ReceiptCard";
import WalkthroughPanel from "@/components/Walkthrough";
import ErrorBoundary from "@/components/ErrorBoundary";
import { Answer, TraceEvent, Walkthrough } from "@/lib/types";
import { PLACES_EXAMPLES } from "@/lib/places";

/**
 * The places section: the public demo's ask experience pointed at the
 * `places` pack (Google Data Commons behind two reviewed templates — see
 * okf-catalog/packs/places/), with the receipt under every answer showing
 * which place and variable Data Commons resolved and which source facet
 * the figures came from. Same sign-in gate and approval queue as `/`.
 */
export default function PlacesHome() {
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
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
        <main className="container" style={{ padding: "36px 0 80px", display: "flex", flexDirection: "column", gap: 22 }}>
          <div className="pack-banner">
            <strong>Places pack</strong>
            <span>
              Reported statistics for any place — countries, states, counties, cities — from Google Data Commons&apos;
              harmonised graph of 200+ public sources. Places and variables are resolved by Data Commons, never guessed;
              one source is used per answer and named on every row.
            </span>
          </div>

          <AskBar
            busy={busy}
            pack="places"
            placeholder="Ask about population, income, unemployment, GDP, health, emissions… for any place"
            groupedExamples={PLACES_EXAMPLES}
            onStart={handleStart}
            onEvent={handleEvent}
            onAnswer={handleAnswer}
            onError={handleError}
          />

          {error && (
            <div style={{ background: "var(--danger-soft)", color: "var(--danger)", borderRadius: 10, padding: "14px 16px", fontSize: "0.9rem" }}>
              {error}
            </div>
          )}

          <TracePanel events={events} />

          {answer && (
            <ErrorBoundary label="answer">
              <AnswerCanvas answer={answer} />
            </ErrorBoundary>
          )}

          {answer?.receipt && (
            <ErrorBoundary label="receipt">
              <ReceiptCard receipt={answer.receipt} />
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
