import fs from "fs";
import path from "path";
import { marked } from "marked";
import Header from "@/components/Header";

export const metadata = {
  title: "Atlas — Finance pack implementation",
  description: "What was built for the finance pack: architecture, catalog, executors, receipts, skills, operations and the private-data recommendation.",
};

// Same pattern as /finance/design: a mirrored markdown file rendered
// server-side, shareable without sign-in. The /finance layout's flag check
// still applies, so this only exists once the section is on.
export default function FinanceImplementationPage() {
  const filePath = path.join(process.cwd(), "public", "FINANCE-IMPLEMENTATION.md");
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
