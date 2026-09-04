// Finance pack: feature flag + the example questions the /finance page
// offers. The flag is read at build time (NEXT_PUBLIC_*), so flipping it in
// apphosting.yaml and redeploying is what turns the section on; with it off
// the /finance routes 404 and the Header shows no link, and the public demo
// is byte-for-byte what it was.

import type { ExampleGroup } from "@/components/AskBar";

export const FINANCE_ENABLED = process.env.NEXT_PUBLIC_ATLAS_FINANCE_ENABLED === "true";

// The golden questions from atlas-finance-demo-plan.md §2.4 and §3.4 plus
// the private internal mart (IMPLEMENTATION.md §8.3, §9.1), minus the deliberate-refusal
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

// Fact-check example paragraphs. Every claim is checked through
// ac.sec_fact_reconcile (levels: both the EDGAR API and the SEC bulk mirror)
// or ac.sec_ratio_by_year (ratios), so examples stay inside what those can
// reach: filers in the entity crosswalk, fiscal years the bulk mirror covers
// (its last complete 10-K year is fiscal 2019), the 21 curated metrics and
// the five curated ratios. Each level claim costs a ~21 GB bulk scan
// (~$0.13), so a chip carries at most three. Some figures are deliberately wrong so the demo
// shows a "differs" verdict; growth / percentage-change claims about level
// metrics are included because they come back "not verifiable" by design.
export const FACT_CHECK_EXAMPLES: ExampleGroup[] = [
  {
    label: "Banks, fiscal 2019 (both sources)",
    questions: [
      "JPMorgan grew deposits 6% in 2019 while its net income reached $36.4 billion, total assets stood at $2.69 trillion and its return on assets was 1.33%.",
      "Bank of America earned $27.4 billion in 2019 on total assets of $2.43 trillion, with deposits of $1.43 trillion at year end.",
      "Wells Fargo reported net income of $25 billion for 2019 and closed the year with $1.93 trillion in total assets.",
      "Citigroup's 2019 net income was $19.4 billion, its total assets were $1.95 trillion and its return on equity was about 10%.",
      "Goldman Sachs finished 2019 with net income of $8.5 billion, total assets of $993 billion and diluted earnings per share of $21.03.",
    ],
  },
  {
    label: "Large filers, fiscal 2019",
    questions: [
      "Apple's fiscal 2019 revenue was $260.2 billion, net income was $55.3 billion and its net margin was roughly 21%.",
      "Microsoft reported $125.8 billion of revenue and $39.2 billion of net income for fiscal 2019, with operating income of $43 billion.",
      "Amazon's 2019 revenue was $280.5 billion with net income of $11.6 billion and operating cash flow of $38.5 billion.",
      "Exxon Mobil's 2019 net income was $14.3 billion, its capital expenditures were $24.4 billion and its long-term debt stood at $26.3 billion.",
      "Walmart's fiscal 2019 revenue was $500 billion and its net income was $6.7 billion.",
    ],
  },
  {
    label: "Claims Atlas won't verify",
    questions: [
      "Nvidia's revenue rose 41% in fiscal 2019 and its net income grew faster than at any point in the prior decade.",
      "Capital One's 2019 net income of $5.5 billion made it the most profitable card issuer in the country, and its total assets grew 5% to $390 billion.",
      "Tesla's 2019 revenue was $24.6 billion, its net loss was $862 million, and its share price doubled over the year.",
    ],
  },
];

export const FACT_CHECK_EXAMPLE = FACT_CHECK_EXAMPLES[0].questions[0];
