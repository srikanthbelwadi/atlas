"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import Logo from "@/components/Logo";

const DATASET_CATEGORIES = ["SEC filings (API)", "Data Commons — any place, 250k statistics (API)", "Labor & economics", "Census & demographics", "Air quality & climate", "Public health", "City operations", "Campaign finance"];

const HOW_IT_WORKS = [
  {
    title: "Discover",
    body:
      "Every data source — a warehouse table, an operational store, an API — is described once in the Open Knowledge Format (OKF) and indexed for Agentic Resource Discovery (ARD), then searched by meaning at question time instead of wired up one integration at a time.",
  },
  {
    title: "Plan",
    body:
      "Gemini reads the matched dataset's real, crawled schema and drafts a query against it — it can't invent a column that isn't there, because it never sees the dataset without seeing its schema first. For a reviewed template it only binds parameters; for an API source like Data Commons it passes the question's own words, and the source's own resolver turns them into identifiers.",
  },
  {
    title: "Fetch & verify",
    body:
      "The query runs under a per-request byte cap and a per-user monthly budget ceiling, checked before it runs. A failed attempt is redrafted against the schema it actually hit — not the one it guessed.",
  },
  {
    title: "Answer, cited",
    body:
      "The result becomes a plain-language answer, cited back to its exact source and trust tier: unverified, machine-confirmed, or human-reviewed.",
  },
];

const FEATURES = [
  {
    title: "Described once, not wired by hand",
    body: "Adding a source — private or public, table or API — means writing an OKF description, not a new integration. The discovery step searches those descriptions by meaning, so the catalog grows without per-source glue code.",
  },
  {
    title: "Every figure, never invented",
    body: "The model never answers from what it already knows. Every number comes from a real, guarded query — BigQuery today, any OKF-described store or API by the same path — and is cited back to its exact source and trust tier: unverified, machine-confirmed, or human-reviewed.",
  },
  {
    title: "Refuses rather than guesses",
    body: "When no source can answer a question well enough to cite, Atlas says so plainly instead of approximating — a clear \"I couldn't find a good source for this\" beats a confident-sounding guess.",
  },
  {
    title: "Reasoning you can watch",
    body: "A live trace shows every candidate source considered and why one was ranked above the rest — not just a spinner — including what changed when a first attempt had to backtrack.",
  },
];

export default function SignInGate({ children }: { children: ReactNode }) {
  const { user, loading, signIn } = useAuth();

  if (loading) {
    return (
      <div className="container" style={{ padding: "80px 0", color: "var(--ink-dim)" }}>
        Loading…
      </div>
    );
  }

  if (!user) {
    return (
      <div>
        {/* Hero */}
        <section className="container" style={{ padding: "72px 0 56px", textAlign: "center" }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 22 }}>
            <Logo size={48} />
          </div>
          <div className="eyebrow" style={{ marginBottom: 14 }}>
            Built on ARD + OKF, answered by Gemini
          </div>
          <h2 style={{ fontSize: "2rem", marginBottom: 16, maxWidth: 620, marginLeft: "auto", marginRight: "auto" }}>
            Ask large-scale data a question.
          </h2>
          <p style={{ color: "var(--ink-dim)", maxWidth: 520, margin: "0 auto 30px", fontSize: "1.02rem" }}>
            Atlas turns a plain-English question into a cited, budgeted answer from any data source described in OKF —
            a warehouse, an operational store, or an API — discovered, planned, and verified in real time. The demo runs
            on BigQuery Public Datasets, the SEC EDGAR API and Google Data Commons.
          </p>
          <button onClick={() => signIn()} className="cta-button">
            Sign in with Google
          </button>
          <p style={{ color: "var(--ink-dim)", fontSize: "0.8rem", marginTop: 14 }}>
            New accounts need a quick admin approval before their first query.
          </p>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="container" style={{ padding: "48px 0" }}>
          <h3 className="section-heading">How it works</h3>
          <ol className="step-list">
            {HOW_IT_WORKS.map((step, i) => (
              <li key={step.title} className="step-item">
                <div className="step-number">{i + 1}</div>
                <div>
                  <div className="step-title">{step.title}</div>
                  <p className="step-body">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* USP feature grid */}
        <section className="container" style={{ padding: "40px 0 48px" }}>
          <h3 className="section-heading">Why it's not just a chatbot on top of a database</h3>
          <div className="feature-grid">
            {FEATURES.map((f) => (
              <div key={f.title} className="feature-card">
                <div className="feature-title">{f.title}</div>
                <p className="feature-body">{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Dataset categories */}
        <section className="container" style={{ padding: "0 0 56px", textAlign: "center" }}>
          <div style={{ color: "var(--ink-dim)", fontSize: "0.82rem", marginBottom: 14 }}>In the demo catalog today — hundreds of millions of rows across BigQuery datasets, plus the SEC EDGAR and Data Commons APIs</div>
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, maxWidth: 520, margin: "0 auto" }}>
            {DATASET_CATEGORIES.map((c) => (
              <span key={c} className="pill">
                {c}
              </span>
            ))}
          </div>
        </section>

        {/* References + closing CTA */}
        <section className="container" style={{ padding: "0 0 72px", textAlign: "center" }}>
          <button onClick={() => signIn()} className="cta-button">
            Sign in with Google
          </button>
          <p style={{ marginTop: 28, fontSize: "0.78rem", color: "var(--ink-dim)" }}>
            <Link href="/implementation" className="nav-link">
              Read the full engineering writeup
            </Link>
            {" · "}
            <a href="https://agenticresourcediscovery.org/spec/" target="_blank" rel="noopener noreferrer" className="nav-link">
              ARD spec
            </a>
            {" · "}
            <a href="https://okf.md/spec/" target="_blank" rel="noopener noreferrer" className="nav-link">
              OKF spec
            </a>
            {" · "}
            <a href="https://github.com/rvguha/Neuralkg" target="_blank" rel="noopener noreferrer" className="nav-link">
              NeuralKG
            </a>
            {" (forked & extended)"}
          </p>
        </section>
      </div>
    );
  }

  return <>{children}</>;
}
