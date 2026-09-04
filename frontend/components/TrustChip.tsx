import { TrustLevel } from "@/lib/types";

const LABEL: Record<TrustLevel, string> = {
  "human-reviewed": "human-reviewed",
  "machine-confirmed": "machine-confirmed",
  unverified: "unverified",
};

/** OKF trust tier as a small mono chip — same colours AnswerCanvas uses for its citation dots. */
export default function TrustChip({ trust }: { trust: TrustLevel }) {
  return <span className={`trust-chip ${trust}`}>{LABEL[trust] || trust}</span>;
}

/**
 * Visibility chip (finance pack, use case D). A private source shows a lock
 * and, when known, whether the current user holds the entitlement — the
 * "your controls still apply" signal on the catalog and the receipt.
 */
export function VisibilityChip({
  visibility,
  entitlement,
  accessible,
}: {
  visibility?: "public" | "private" | string | null;
  entitlement?: string | null;
  accessible?: boolean;
}) {
  if (visibility !== "private") return null;
  const label = accessible === false ? "private · no access" : accessible ? "private · unlocked" : "private";
  const title = entitlement ? `Restricted: needs the ${entitlement} entitlement` : "Restricted source";
  return (
    <span className={`trust-chip private${accessible === false ? " locked" : ""}`} title={title}>
      🔒 {label}
    </span>
  );
}
