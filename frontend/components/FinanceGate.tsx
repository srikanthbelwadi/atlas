"use client";

import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { getPackCatalog, ApiError } from "@/lib/api";
import { FINANCE_EXAMPLES } from "@/lib/finance";
import Logo from "@/components/Logo";
import AdminContact from "@/components/AdminContact";

/**
 * The finance section's own front door and approval gate.
 *
 * Signed out → a landing page that says what the section is and what an
 * account gets after signing in (the public demo's SignInGate describes the
 * public pack; this one describes the finance pack).
 *
 * Signed in → the same approval queue the public demo uses, made visible:
 * the backend refuses every finance endpoint for a `pending` account with a
 * 403, so this probes `GET /packs/finance/catalog` once (cheap, cached
 * server-side) and shows an "awaiting approval" state instead of letting
 * the user type a question that will only fail. Approved accounts get the
 * children, plus their entitlements through `useFinanceAccess()` so the
 * page can say up front whether private sources are open to them.
 */

type AccessState =
  | { status: "checking" }
  | { status: "pending"; detail: string }
  | { status: "approved"; entitlements: string[] }
  | { status: "error"; detail: string };

const FinanceAccessContext = createContext<{ entitlements: string[] }>({ entitlements: [] });
export const useFinanceAccess = () => useContext(FinanceAccessContext);

const AFTER_SIGN_IN = [
  {
    title: "Ask, and get a receipt",
    body:
      "Plain-English questions over complaints, conduct, SEC filings and peer banks. Attested answers carry a receipt: the reviewed template, its version and reviewer, every query step, bytes and cost.",
  },
  {
    title: "Fact-check a paragraph",
    body: "Paste prose with figures in it. Every numeric claim is verified against SEC filings through reviewed templates only, and comes back verified, differs, or not verifiable.",
  },
  {
    title: "Browse the catalog",
    body: "Every source the pack can discover, with its trust tier, reviewer and freshness — and for reviewed templates, the exact SQL that runs. The model only binds parameter values.",
  },
  {
    title: "Private internal data, if entitled",
    body:
      "A private risk mart — a loan book and a payments ledger — sits behind the same catalog. Only accounts holding the finance.internal entitlement are offered it; everyone else sees a clear refusal that names what was withheld.",
  },
];

const ACCESS_STEPS = [
  { title: "Sign in with Google", body: "The same account works for the public demo and the finance section." },
  {
    title: "An admin approves your account",
    body: "New accounts start as pending. You'll see a waiting state here until an admin approves you; the admin is notified automatically.",
  },
  { title: "Ask", body: "Public finance sources are open to every approved account, within a $100 monthly query budget." },
  {
    title: "Private sources need an entitlement",
    body: "If a question is best answered from private data your account can't see, Atlas refuses and tells you what it withheld. If you believe you should have access, contact the administrator.",
  },
];

function Landing({ onSignIn }: { onSignIn: () => void }) {
  const examples = FINANCE_EXAMPLES.flatMap((g) => g.questions.slice(0, 2).map((q) => ({ q, group: g.label })));
  return (
    <div>
      <section className="container" style={{ padding: "64px 0 48px", textAlign: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 22 }}>
          <Logo size={48} />
        </div>
        <div className="eyebrow" style={{ marginBottom: 14 }}>
          Atlas · Finance pack
        </div>
        <h2 style={{ fontSize: "2rem", marginBottom: 16, maxWidth: 680, marginLeft: "auto", marginRight: "auto" }}>
          Complaints, filings and peer banks — answered with receipts.
        </h2>
        <p style={{ color: "var(--ink-dim)", maxWidth: 560, margin: "0 auto 30px", fontSize: "1.02rem" }}>
          The same Atlas platform pointed at a finance catalog: public datasets standing in for a bank&apos;s complaint
          system, entity master and fundamentals warehouse, plus a private internal risk mart that only entitled accounts
          can query. Every attested answer names the reviewed definition it came from.
        </p>
        <button onClick={onSignIn} className="cta-button">
          Sign in with Google
        </button>
        <p style={{ color: "var(--ink-dim)", fontSize: "0.8rem", marginTop: 14 }}>
          New accounts need a quick admin approval before their first question.
        </p>
      </section>

      <section className="container" style={{ padding: "32px 0 40px" }}>
        <h3 className="section-heading">What you get after signing in</h3>
        <div className="feature-grid">
          {AFTER_SIGN_IN.map((f) => (
            <div key={f.title} className="feature-card">
              <div className="feature-title">{f.title}</div>
              <p className="feature-body">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="how-access-works" className="container" style={{ padding: "24px 0 40px" }}>
        <h3 className="section-heading">How access works</h3>
        <ol className="step-list">
          {ACCESS_STEPS.map((step, i) => (
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

      <section className="container" style={{ padding: "0 0 40px", textAlign: "center" }}>
        <div style={{ color: "var(--ink-dim)", fontSize: "0.82rem", marginBottom: 14 }}>
          Questions the finance pack answers today — each one routes to a reviewed template
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, maxWidth: 760, margin: "0 auto" }}>
          {examples.map(({ q, group }) => (
            <span key={q} className="pill" title={group} style={{ maxWidth: 360, textAlign: "left" }}>
              {group.includes("private") ? "🔒 " : ""}
              {q}
            </span>
          ))}
        </div>
        <p style={{ color: "var(--ink-dim)", fontSize: "0.78rem", marginTop: 16, maxWidth: 560, marginLeft: "auto", marginRight: "auto" }}>
          The public mirrors are dated — CFPB complaints to March 2023, SEC bulk filings to fiscal 2019, FDIC to late 2022; the
          EDGAR API is current — so example questions ask about 2022 and fiscal 2019, and every answer names the vintage it used.
        </p>
      </section>

      <section className="container" style={{ padding: "0 0 72px", textAlign: "center" }}>
        <button onClick={onSignIn} className="cta-button">
          Sign in with Google
        </button>
        <p style={{ marginTop: 28, fontSize: "0.78rem", color: "var(--ink-dim)" }}>
          <Link href="/implementation#the-finance-pack-atlas-for-one-vertical" className="nav-link">
            How the finance pack is built
          </Link>
          {" · "}
          <Link href="/implementation" className="nav-link">
            Full implementation document
          </Link>
          {" · "}
          <Link href="/" className="nav-link">
            Public demo
          </Link>
        </p>
      </section>
    </div>
  );
}

function PendingApproval({ email, detail }: { email: string; detail: string }) {
  return (
    <main className="container" style={{ padding: "64px 0 96px", maxWidth: 640 }}>
      <div className="eyebrow" style={{ marginBottom: 12 }}>
        Finance pack · account pending
      </div>
      <h2 style={{ fontSize: "1.6rem", marginBottom: 12 }}>You&apos;re signed in — your account is waiting for approval.</h2>
      <p style={{ color: "var(--ink-dim)", marginBottom: 20 }}>
        Signed in as <span className="mono">{email}</span>. {detail}
      </p>
      <div className="feature-card" style={{ marginBottom: 20 }}>
        <div className="feature-title">What happens next</div>
        <ol style={{ margin: "8px 0 0", paddingLeft: 20, lineHeight: 1.6, fontSize: "0.9rem" }}>
          <li>An Atlas administrator has been notified and will review your account.</li>
          <li>Once approved, reload this page — you can ask, fact-check a paragraph and browse the catalog.</li>
          <li>
            Private internal sources additionally need an entitlement. If your work requires them, mention it when you contact
            the administrator.
          </li>
        </ol>
      </div>
      <p style={{ fontSize: "0.88rem" }}>
        Waiting longer than expected? Contact{" "}
        <AdminContact subject="Atlas finance access request" body={`Please approve my Atlas account (${email}) for the finance section.`} />
        .
      </p>
    </main>
  );
}

export default function FinanceGate({ children }: { children: ReactNode }) {
  const { user, loading, signIn, getIdToken } = useAuth();
  const [access, setAccess] = useState<AccessState>({ status: "checking" });

  useEffect(() => {
    if (!user) {
      setAccess({ status: "checking" });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const token = await getIdToken();
        if (!token) throw new ApiError(401, "Not signed in");
        const catalog = await getPackCatalog("finance", token);
        if (!cancelled) setAccess({ status: "approved", entitlements: catalog.entitlements || [] });
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) setAccess({ status: "pending", detail: err.message });
        else setAccess({ status: "error", detail: err instanceof ApiError ? err.message : "Couldn't reach Atlas. Try again in a moment." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, getIdToken]);

  if (loading) {
    return (
      <div className="container" style={{ padding: "80px 0", color: "var(--ink-dim)" }}>
        Loading…
      </div>
    );
  }
  if (!user) return <Landing onSignIn={() => signIn()} />;

  if (access.status === "checking") {
    return (
      <div className="container" style={{ padding: "80px 0", color: "var(--ink-dim)" }}>
        Checking your access…
      </div>
    );
  }
  if (access.status === "pending") return <PendingApproval email={user.email || ""} detail={access.detail} />;
  if (access.status === "error") {
    return (
      <main className="container" style={{ padding: "64px 0 96px", maxWidth: 640 }}>
        <div style={{ background: "var(--danger-soft)", color: "var(--danger)", borderRadius: 10, padding: "14px 16px", fontSize: "0.9rem" }}>
          {access.detail}
        </div>
      </main>
    );
  }

  return <FinanceAccessContext.Provider value={{ entitlements: access.entitlements }}>{children}</FinanceAccessContext.Provider>;
}
