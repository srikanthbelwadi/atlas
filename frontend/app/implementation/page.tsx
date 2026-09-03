import fs from "fs";
import path from "path";
import { marked } from "marked";
import Header from "@/components/Header";

export const metadata = {
  title: "Atlas — Implementation",
  description:
    "Engineering design: architecture, tech stack, cost guardrails, grounding, tracing, and what was kept vs. replaced from NeuralKG.",
};

// Deliberately NOT wrapped in SignInGate — this is reference material meant
// to be shareable with testers before (or without) signing in, same as the
// GitHub repo itself would be. frontend/public/IMPLEMENTATION.md is a
// mirrored copy of the repo-root IMPLEMENTATION.md, kept inside frontend/
// specifically so this route doesn't depend on Firebase App Hosting's
// monorepo "root directory" setting resolving a path above it.
export default function ImplementationPage() {
  const filePath = path.join(process.cwd(), "public", "IMPLEMENTATION.md");
  const markdown = fs.readFileSync(filePath, "utf8");
  const html = marked.parse(markdown, { async: false }) as string;

  return (
    <>
      <Header />
      <main className="container" style={{ padding: "48px 0 96px" }}>
        <div className="prose" dangerouslySetInnerHTML={{ __html: html }} />
      </main>
    </>
  );
}
