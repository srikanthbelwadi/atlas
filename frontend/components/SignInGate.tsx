"use client";

import { ReactNode } from "react";
import { useAuth } from "@/lib/auth-context";

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
      <div className="container" style={{ padding: "100px 0", textAlign: "center" }}>
        <h2 style={{ fontSize: "1.6rem", marginBottom: 12 }}>Ask public data a question</h2>
        <p style={{ color: "var(--ink-dim)", maxWidth: 440, margin: "0 auto 28px" }}>
          Sign in to ask Atlas anything answerable from public BigQuery datasets. New accounts need a quick admin
          approval before their first query.
        </p>
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
