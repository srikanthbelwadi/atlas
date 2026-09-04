"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Header from "@/components/Header";
import SignInGate from "@/components/SignInGate";
import CatalogTable from "@/components/CatalogTable";
import { useAuth } from "@/lib/auth-context";
import { getPackCatalog, ApiError } from "@/lib/api";
import { PackCatalog } from "@/lib/types";

export default function FinanceCatalogPage() {
  const { user, getIdToken } = useAuth();
  const [catalog, setCatalog] = useState<PackCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getIdToken();
        if (!token) throw new ApiError(401, "Not signed in");
        const data = await getPackCatalog("finance", token);
        if (!cancelled) setCatalog(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Couldn't load the catalog.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, getIdToken]);

  return (
    <>
      <Header />
      <SignInGate>
        <main className="container" style={{ padding: "36px 0 80px", display: "flex", flexDirection: "column", gap: 18 }}>
          <div>
            <h2 style={{ fontSize: "1.4rem", marginBottom: 6 }}>Finance pack catalog</h2>
            <p style={{ margin: 0, color: "var(--ink-dim)", fontSize: "0.9rem", maxWidth: "70ch" }}>
              Everything the finance section can discover: reviewed templates (the SQL text below is exactly what runs — the model
              only binds parameter values), the public BigQuery tables that stand in for a bank&apos;s complaint system, entity
              master and fundamentals mart, and the private internal risk mart (🔒) that only entitled accounts can query.{" "}
              <Link href="/finance" className="nav-link">
                ← Back to asking
              </Link>
            </p>
          </div>
          {error && <div style={{ background: "var(--danger-soft)", color: "var(--danger)", borderRadius: 10, padding: "12px 16px" }}>{error}</div>}
          {!catalog && !error && <div style={{ color: "var(--ink-dim)" }}>Loading catalog…</div>}
          {catalog && (
            <>
              <div className="pack-banner">
                <span>{catalog.counts.attested} attested computations</span>
                <span>·</span>
                <span>{catalog.counts.tables} crawled tables</span>
                {catalog.counts.private ? (
                  <>
                    <span>·</span>
                    <span>🔒 {catalog.counts.private} private</span>
                  </>
                ) : null}
                <span style={{ marginLeft: "auto", color: "var(--ink-dim)" }}>
                  your entitlements: <span className="mono">{catalog.entitlements?.length ? catalog.entitlements.join(", ") : "none"}</span>
                </span>
              </div>
              <CatalogTable entries={catalog.entries} />
            </>
          )}
        </main>
      </SignInGate>
    </>
  );
}
