// Finance pack: feature flag + the example questions the /finance page
// offers. The flag is read at build time (NEXT_PUBLIC_*), so flipping it in
// apphosting.yaml and redeploying is what turns the section on; with it off
// the /finance routes 404 and the Header shows no link, and the public demo
// is byte-for-byte what it was.

import type { ExampleGroup } from "@/components/AskBar";

export const FINANCE_ENABLED = process.env.NEXT_PUBLIC_ATLAS_FINANCE_ENABLED === "true";

// The golden questions from atlas-finance-demo-plan.md §2.4 and §3.4, minus
// the deliberate-refusal ones (A6/B6), which don't belong on a chip a
// visitor would click expecting an answer. Keep in sync with
// tests/golden/finance_a.yaml and finance_b.yaml.
export const FINANCE_EXAMPLES: ExampleGroup[] = [
  {
    label: "Complaints & conduct",
    questions: [
      "Which five products had the largest year-over-year increase in complaints in 2025, and what share of each was disputed?",
      "What is Wells Fargo's timely-response rate on mortgage complaints by quarter since 2023, versus the top-10 banks by deposits?",
      "Complaints per $1B of deposits for the ten largest banks in 2025.",
      "What are the main themes in narratives about credit-reporting disputes filed in Q1 2026, with three representative quotes each?",
      "Did older-American-tagged complaints about debt collection get resolved with relief less often than untagged ones in 2025?",
    ],
  },
  {
    label: "Filings & peers",
    questions: [
      "What was JPMorgan's net income for fiscal 2025 according to its 10-K, and does the SEC bulk data set agree with the EDGAR API?",
      "Compare return on assets for the five largest US banks by deposits in 2025, using FDIC figures.",
      "Revenue for Apple, Microsoft and Nvidia over the last five fiscal years.",
      "Which state commercial bank filers (SIC 6022) reported a net loss in any quarter of 2025?",
    ],
  },
];

export const FACT_CHECK_EXAMPLE =
  "Bank of America grew deposits 6% in 2025 while its net income reached $27.1 billion and its efficiency ratio fell below 60%.";
