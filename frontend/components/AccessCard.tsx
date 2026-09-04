"use client";

import { AccessInfo } from "@/lib/types";

/**
 * Finance pack, use case D. Shown under an answer whenever a private source
 * was involved: either the sources discovery matched but withheld (the user
 * lacks the entitlement — the answer is then a refusal) or, for an entitled
 * user, the entitlement that unlocked a private answer. Withheld sources are
 * named by id and title only; their contents never reach the client.
 */
export default function AccessCard({ access, refused }: { access: AccessInfo; refused?: boolean }) {
  const withheld = access.withheld || [];
  const needs = Array.from(new Set(withheld.map((w) => w.entitlement).filter(Boolean))) as string[];
  if (!withheld.length && !access.entitlements?.length) return null;

  if (withheld.length) {
    return (
      <section className={`access-card${refused ? "" : " unlocked"}`} aria-label="Restricted sources">
        <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 4 }}>
          Restricted sources {refused ? "— answer withheld" : "— not used"}
        </div>
        <div>
          {withheld.length} matching source{withheld.length === 1 ? "" : "s"} {withheld.length === 1 ? "is" : "are"} private and need
          {withheld.length === 1 ? "s" : ""} the <span className="mono">{needs.join(", ") || "required"}</span> entitlement, which this
          account doesn&apos;t hold. Atlas names them but never answers from a public stand-in in their place. An admin can grant the
          entitlement on <span className="mono">/admin</span>.
        </div>
        <ul>
          {withheld.map((w) => (
            <li key={w.source_id}>
              <span className="mono" style={{ fontSize: "0.8rem" }}>{w.source_id}</span> — {w.title}
              {w.score != null ? <span style={{ color: "var(--ink-dim)" }}> (match {w.score.toFixed(2)})</span> : null}
            </li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section className="access-card unlocked" aria-label="Access">
      <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 4 }}>
        Private data — unlocked
      </div>
      <div>
        This answer reads the bank&apos;s own data. Your account holds <span className="mono">{access.entitlements.join(", ")}</span>; the
        receipt records it. The dataset itself has no public IAM binding — only the orchestrator&apos;s service account can read it.
      </div>
    </section>
  );
}
