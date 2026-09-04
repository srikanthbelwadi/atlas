"use client";

import { useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import SignInGate from "@/components/SignInGate";
import AskBar from "@/components/AskBar";
import FactCheckBar from "@/components/FactCheckBar";
import TracePanel from "@/components/TracePanel";
import AnswerCanvas from "@/components/AnswerCanvas";
import ReceiptCard from "@/components/ReceiptCard";
import AccessCard from "@/components/AccessCard";
import WalkthroughPanel from "@/components/Walkthrough";
import ErrorBoundary from "@/components/ErrorBoundary";
import { Answer, TraceEvent, Walkthrough } from "@/lib/types";
import { FINANCE_EXAMPLES } from "@/lib/finance";

type Mode = "ask" | "fact-check";

/**
 * The finance section: the public demo's ask experience pointed at the
 * `finance` pack, plus a fact-check mode and a receipt under every attested
 * answer. Same components, same trace, same walkthrough — the pack is the
 * only thing that changes what the backend can see.
 */
export default function FinanceHome() {
  const [mode, setMode] = useState<Mode>("ask");
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

  const switchMode = (m: Mode) => {
    if (busy || m === mode) return;
    setMode(m);
    setEvents([]);
    setAnswer(null);
    setError(null);
    setWalkthrough(null);
  };

  return (
    <>
      <Header />
      <SignInGate>
        <main className="container" style={{ padding: "36px 0 80px", display: "flex", flexDirection: "column", gap: 22 }}>
          <div className="pack-banner">
            <strong>Finance pack</strong>
            <span>
              Public datasets standing in for a bank&apos;s complaint system, entity master and fundamentals mart, plus a
              private internal risk mart behind the same catalog — every attested answer carries a receipt.
            </span>
            <span style={{ marginLeft: "auto", display: "flex", gap: 14 }}>
              <Link href="/finance/catalog" className="nav-link">
                Sources & templates →
              </Link>
              <Link href="/finance/implementation" className="nav-link">
                How it&apos;s built →
              </Link>
            </span>
          </div>

          <div className="segmented" role="group" aria-label="Mode">
            <button type="button" aria-pressed={mode === "ask"} onClick={() => switchMode("ask")}>
              Ask
            </button>
            <button type="button" aria-pressed={mode === "fact-check"} onClick={() => switchMode("fact-check")}>
              Fact-check a paragraph
            </button>
          </div>

          {mode === "ask" ? (
            <AskBar
              busy={busy}
              pack="finance"
              placeholder="Ask about complaints, conduct, filings or peer banks…"
              groupedExamples={FINANCE_EXAMPLES}
              onStart={handleStart}
              onEvent={handleEvent}
              onAnswer={handleAnswer}
              onError={handleError}
            />
          ) : (
            <FactCheckBar busy={busy} onStart={handleStart} onEvent={handleEvent} onAnswer={handleAnswer} onError={handleError} />
          )}

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

          {answer?.access && (
            <ErrorBoundary label="access">
              <AccessCard access={answer.access} refused={answer.refused === "not_entitled"} />
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
