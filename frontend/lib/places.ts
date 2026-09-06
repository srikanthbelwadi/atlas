// Places pack (Data Commons): feature flag + the example questions the
// /places page offers. Same mechanism as lib/finance.ts — the flag is read
// at build time (NEXT_PUBLIC_*), so flipping it in apphosting.yaml and
// redeploying turns the section on; off, the /places routes 404, the Header
// shows no link, and nothing else changes.

import type { ExampleGroup } from "@/components/AskBar";

export const PLACES_ENABLED = process.env.NEXT_PUBLIC_ATLAS_PLACES_ENABLED === "true";

// Keep in sync with tests/golden/places_a.yaml (minus the deliberate
// refusal, which doesn't belong on a chip).
export const PLACES_EXAMPLES: ExampleGroup[] = [
  {
    label: "One place — value, trend, comparison",
    questions: [
      "What is the population of India?",
      "How has median household income in Santa Clara County, CA changed over the last 10 years?",
      "Compare life expectancy in Japan and the United States.",
      "What was the GDP per capita of Germany in 2019?",
    ],
  },
  {
    label: "Rank every place inside another",
    questions: [
      "Which counties in California have the highest unemployment rate?",
      "Rank US states by median household income, top 10.",
      "Which ten countries in Africa have the lowest life expectancy?",
    ],
  },
];
