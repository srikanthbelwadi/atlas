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
