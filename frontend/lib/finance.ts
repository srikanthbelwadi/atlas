// Finance pack: feature flag + the example questions the /finance page
// offers. The flag is read at build time (NEXT_PUBLIC_*), so flipping it in
// apphosting.yaml and redeploying is what turns the section on; with it off
// the /finance routes 404 and the Header shows no link, and the public demo
// is byte-for-byte what it was.

import type { ExampleGroup } from "@/components/AskBar";

export const FINANCE_ENABLED = process.env.NEXT_PUBLIC_ATLAS_FINANCE_ENABLED === "true";

// The golden questions from atlas-finance-demo-plan.md §2.4 and §3.4 plus
// use case D (FINANCE-IMPLEMENTATION.md §12), minus the deliberate-refusal
// ones (A6/B6/D5), which don't belong on a chip a visitor would click
// expecting an answer. The private group answers only for accounts holding
// the finance.internal entitlement; everyone else gets the withheld card.
// Keep in sync with tests/golden/finance_{a,b,d}.yaml.
export const FINANCE_EXAMPLES: ExampleGroup[] = [
  {
    label: "Complaints & conduct",
    questions: [
      "Which five products had the largest year-over-year increase in complaints in 2022, and what share of each was answered on time?",
      "What is Wells Fargo's timely-response rate on mortgage complaints by quarter since 2021, versus the top-10 banks by deposits?",
      "Complaints per $1B of deposits for the ten largest banks in 2022.",
      "What are the main themes in narratives about credit-reporting disputes filed in Q1 2022, with three representative quotes each?",
      "Did older-American-tagged complaints about debt collection get resolved with relief less often than untagged ones in 2022?",
    ],
  },
  {
    label: "Internal risk mart (private)",
    questions: [
      "What is our default rate by income band, and which band is furthest above the book rate?",
      "Do applicants with more than three bureau inquiries in the last year default more often than the rest of our book?",
      "How did late payment on instalments trend over the twelve months before application, for clients who later defaulted versus those who didn't?",
      "Which accounts in our ledger made three or more transfers just under 10,000 within 72 hours, and did the legacy flag catch any?",
    ],
  },
  {
    label: "Filings & peers",
    questions: [
      "What was JPMorgan's net income for fiscal 2019 according to its 10-K, and does the SEC bulk data set agree with the EDGAR API?",
      "Compare return on assets for the five largest US banks by deposits, using the latest FDIC figures.",
      "Revenue for Apple, Microsoft and Nvidia over the last five fiscal years.",
      "According to their SEC 10-Q filings, which state commercial banks (SIC code 6022) reported a quarterly net loss in 2019?",
    ],
  },
];

export const FACT_CHECK_EXAMPLE =
  "JPMorgan grew deposits 6% in 2019 while its net income reached $36.4 billion, total assets stood at $2.69 trillion and its return on assets was 1.33%.";
