"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import Logo from "@/components/Logo";

const DATASET_CATEGORIES = ["COVID-19", "Air quality", "Census & demographics", "Crime", "Campaign finance", "Climate"];

const HOW_IT_WORKS = [
  {
    title: "Discover",
    body:
      "Every public dataset is described once, in the Agentic Resource Discovery (ARD) and Open Knowledge Format (OKF) — searched by meaning at question time, not wired up one integration at a time.",
  },
  {
    title: "Plan",
    body:
      "Gemini reads the matched dataset's real, crawled schema and drafts a query against it — it can't invent a column that isn't there, because it never sees the dataset without seeing its schema first.",
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
    body: "Adding a dataset means writing an ARD/OKF description, not a new integration. The discovery step searches those descriptions by meaning, so the catalog grows without new glue code per source.",
  },
  {
    title: "Trust you can see",
    body: "Every citation carries the OKF trust tier behind it, so you know whether a figure is a direct schema read or a human-reviewed computation — not just a number with a link.",
  },
  {
    title: "Budget-guarded by design",
    body: "A hard per-user monthly ceiling and a per-query byte cap are enforced before a query runs, not discovered afterward on a bill.",
  },
  {
    title: "Reasoning you can watch",
    body: "A live trace shows which sources were considered and why one was chosen over another, including what happened on a retry — not just a spinner.",
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
            Ask public data a question.
          </h2>
          <p style={{ color: "var(--ink-dim)", maxWidth: 520, margin: "0 auto 30px", fontSize: "1.02rem" }}>
            Atlas turns a plain-English question into a cited answer — discovered, planned, and verified against
            public BigQuery datasets in real time, not a canned dashboard behind it.
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
          <h3 className="section-heading">Why it's not just a chatbot on top of BigQuery</h3>
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
          <div style={{ color: "var(--ink-dim)", fontSize: "0.82rem", marginBottom: 14 }}>Some of what's covered today</div>
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
            <a href="https://github.com/TechSoup/resource-raiser" target="_blank" rel="noopener noreferrer" className="nav-link">
              Resource Raiser
            </a>
            {" (forked & extended)"}
          </p>
        </section>
      </div>
    );
  }

  return <>{children}</>;
}
