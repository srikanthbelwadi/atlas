// Public catalog: the example questions the home ask bar offers, grouped by
// data domain the way /finance groups its chips. Same standard as the flat
// list in components/AskBar.tsx that these replace: every question here has
// been live-verified end to end — a chip must never point at a question
// Atlas can't answer well. Sources: tests/golden/public_regression.yaml,
// tests/golden/places_a.yaml and public_b.yaml (Data Commons and round-B
// BigQuery questions) and, for the multi-company filings question,
// tests/golden/finance_b.yaml (the SEC EDGAR template is shared by both
// packs). Candidates for the next round live in tests/golden/public_b.yaml
// and are promoted here only after they pass.

import type { ExampleGroup } from "@/components/AskBar";

export const PUBLIC_EXAMPLES: ExampleGroup[] = [
  {
    label: "Places & demographics — Data Commons",
    questions: [
      "What is the population of India?",
      "Compare life expectancy in Japan and the United States.",
      "How has median household income in Santa Clara County, CA changed over the last 10 years?",
      "How has Brazil's GDP per capita changed since 2000?",
      "Compare the fertility rate of Nigeria and Germany over the last 20 years.",
      "What is the median age in Miami, Florida?",
    ],
  },
  {
    label: "Rankings across places — Data Commons",
    questions: [
      "Which counties in California have the highest unemployment rate?",
      "Rank US states by median household income, top 10.",
      "Which ten countries in Africa have the lowest life expectancy?",
      "Rank the countries in Asia by CO2 emissions per capita.",
      "Which US states have the highest obesity rate?",
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
      "How has annual average PM2.5 in Los Angeles County changed over the last five years?",
    ],
  },
  {
    label: "Cities & crime",
    questions: [
      "What are the most common types of crime reported in Chicago?",
      "What are the most common 311 complaint types in New York City?",
      "How have motor-vehicle collisions in New York City trended by year?",
    ],
  },
  {
    label: "Companies & SEC filings",
    questions: [
      "What was Google's revenue in 2023?",
      "Revenue for Apple, Microsoft and Nvidia over the last five fiscal years.",
    ],
  },
  {
    label: "Elections, search & society",
    questions: [
      "Which candidates raised the most money in federal campaign contributions recently?",
      "Which committees received the largest individual contributions in the 2020 cycle?",
      "What were the top rising search terms in the United States most recently?",
      "What was the most popular baby name in the United States in 2020?",
    ],
  },
];
