"use client";

import { AccessInfo } from "@/lib/types";
import AdminContact from "@/components/AdminContact";

/**
 * Shown under an answer whenever a private source was involved: either the
 * sources discovery matched but withheld (the user lacks the entitlement —
 * the answer is then a refusal) or, for an entitled user, the entitlement
 * that unlocked a private answer. Withheld sources are named by id and
 * title only; their contents never reach the client. The refusal says
 * plainly what to do next: contact the administrator if you believe you
 * should have access.
 */
export default function AccessCard({ access, refused }: { access: AccessInfo; refused?: boolean }) {
  const withheld = access.withheld || [];
  const needs = Array.from(new Set(withheld.map((w) => w.entitlement).filter(Boolean))) as string[];
  if (!withheld.length && !access.entitlements?.length) return null;

  if (withheld.length) {
    const n = withheld.length;
    const needList = needs.join(", ") || "required";
    const requestBody = `I'd like the ${needList} entitlement on my Atlas account so I can query: ${withheld
      .map((w) => w.source_id)
      .join(", ")}.`;
    return (
      <section className={`access-card${refused ? "" : " unlocked"}`} aria-label="Restricted sources">
        <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 4 }}>
          {refused ? "Answer withheld — private data you can't access" : "Private sources not used"}
        </div>
        <div>
          {refused ? (
            <>
              This question is best answered from private data, and your account doesn&apos;t hold the{" "}
              <span className="mono">{needList}</span> entitlement that {n === 1 ? "it needs" : "those sources need"}. Atlas names the{" "}
              {n === 1 ? "source" : `${n} sources`} it withheld but never answers from a public stand-in in their place.
            </>
          ) : (
            <>
              {n} matching private source{n === 1 ? "" : "s"} {n === 1 ? "was" : "were"} withheld because your account doesn&apos;t hold
              the <span className="mono">{needList}</span> entitlement; the answer above comes from public sources only.
            </>
          )}
        </div>
        <ul>
          {withheld.map((w) => (
            <li key={w.source_id}>
              🔒 <span className="mono" style={{ fontSize: "0.8rem" }}>{w.source_id}</span> — {w.title}
              {w.score != null ? <span style={{ color: "var(--ink-dim)" }}> (match {w.score.toFixed(2)})</span> : null}
            </li>
          ))}
        </ul>
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
          <strong>Believe you should have access?</strong> Contact{" "}
          <AdminContact subject={`Atlas entitlement request: ${needList}`} body={requestBody} /> and mention the{" "}
          <span className="mono">{needList}</span> entitlement. Once granted, it applies to your very next question — no new sign-in
          needed.
        </div>
      </section>
    );
  }

  return (
    <section className="access-card unlocked" aria-label="Access">
      <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 4 }}>
        Private data — unlocked
      </div>
      <div>
        This answer reads private internal data. Your account holds <span className="mono">{access.entitlements.join(", ")}</span>;
        the receipt records it. The dataset itself has no public IAM binding — only the orchestrator&apos;s service account can read it.
      </div>
    </section>
  );
}
