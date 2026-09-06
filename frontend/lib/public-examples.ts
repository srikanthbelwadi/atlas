// Public catalog: the example questions the home ask bar offers, grouped by
// data domain the way /finance groups its chips. Same standard as the flat
// list in components/AskBar.tsx that these replace: every question here has
// been live-verified end to end — a chip must never point at a question
// Atlas can't answer well. Sources: tests/golden/public_regression.yaml,
// tests/golden/places_a.yaml (Data Commons) and, for the multi-company
// filings question, tests/golden/finance_b.yaml (the SEC EDGAR template is
// shared by both packs). Candidates for the next round live in
// tests/golden/public_b.yaml and are promoted here only after they pass.

import type { ExampleGroup } from "@/components/AskBar";

export const PUBLIC_EXAMPLES: ExampleGroup[] = [
  {
    label: "Places & demographics — Data Commons",
    questions: [
      "What is the population of India?",
      "Compare life expectancy in Japan and the United States.",
      "How has median household income in Santa Clara County, CA changed over the last 10 years?",
      "Which counties in California have the highest unemployment rate?",
      "Rank US states by median household income, top 10.",
      "Which ten countries in Africa have the lowest life expectancy?",
    ],
  },
  {
    label: "Public health",
    questions: [
      "How did COVID case rates change by year in Alameda County, CA?",
      "How did COVID-19 case rates change over time in Los Angeles County, CA?",
      "How many people in Texas have diabetes?",
    ],
  },
  {
    label: "Weather & air quality",
    questions: [
      "What was the average temperature in Chicago in 2023?",
      "Which US counties had the worst air quality last year?",
    ],
  },
  {
    label: "Cities & crime",
    questions: ["What are the most common types of crime reported in Chicago?"],
  },
  {
    label: "Companies & SEC filings",
    questions: [
      "What was Google's revenue in 2023?",
      "Revenue for Apple, Microsoft and Nvidia over the last five fiscal years.",
    ],
  },
  {
    label: "Elections & society",
    questions: [
      "Which candidates raised the most money in federal campaign contributions recently?",
      "What was the most popular baby name in the United States in 2020?",
    ],
  },
];
