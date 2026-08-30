"use client";

import { ReactNode } from "react";
import { useAuth } from "@/lib/auth-context";
import Logo from "@/components/Logo";

const DATASET_CATEGORIES = ["COVID-19", "Air quality", "Census & demographics", "Crime", "Campaign finance", "Climate"];

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
      <div className="container" style={{ padding: "90px 0 100px", textAlign: "center" }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }}>
          <Logo size={44} />
        </div>
        <h2 style={{ fontSize: "1.6rem", marginBottom: 12 }}>Ask public data a question</h2>
        <p style={{ color: "var(--ink-dim)", maxWidth: 440, margin: "0 auto 24px" }}>
          Sign in to ask Atlas anything answerable from public BigQuery datasets. New accounts need a quick admin
          approval before their first query.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, maxWidth: 460, margin: "0 auto 32px" }}>
          {DATASET_CATEGORIES.map((c) => (
            <span
              key={c}
              style={{
                fontSize: "0.76rem",
                padding: "5px 12px",
                borderRadius: 999,
                background: "var(--surface-2)",
                color: "var(--ink-dim)",
              }}
            >
              {c}
            </span>
          ))}
        </div>
        <button
          onClick={() => signIn()}
          style={{
            background: "var(--navy)",
            color: "white",
            border: "none",
            borderRadius: 8,
            padding: "12px 22px",
            fontSize: "0.95rem",
            cursor: "pointer",
          }}
        >
          Sign in with Google
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
