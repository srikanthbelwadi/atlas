import { notFound } from "next/navigation";
import { FINANCE_ENABLED } from "@/lib/finance";

// The flag check lives here, not only in the nav: Firebase App Hosting
// deploys `main` automatically, so a merge with the flag off must leave
// every /finance/* route returning 404 — the section can't be reached by
// URL before the backend has the finance pack enabled and crawled.
export default function FinanceLayout({ children }: { children: React.ReactNode }) {
  if (!FINANCE_ENABLED) notFound();
  return <>{children}</>;
}
