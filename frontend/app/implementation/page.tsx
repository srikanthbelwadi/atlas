import fs from "fs";
import path from "path";
import { Marked, Renderer, Tokens } from "marked";
import Header from "@/components/Header";

export const metadata = {
  title: "Atlas — Implementation",
  description:
    "How Atlas is built: architecture, the OKF/ARD catalog, packs, trust tiers and private catalogs, executors and guardrails, receipts, the data sources, the finance pack, and the HTTP API and agent skills.",
};

// Deliberately NOT wrapped in SignInGate and NOT under /finance's feature
// flag — this is reference material meant for developers and decision
// makers before (or without) signing in, same as the GitHub repo itself.
// frontend/public/IMPLEMENTATION.md is a mirrored copy of the repo-root
// IMPLEMENTATION.md, kept inside frontend/ so this route doesn't depend on
// Firebase App Hosting's monorepo "root directory" setting resolving a path
// above it. It is the single implementation document: the finance pack is
// one section of it (§9), not a separate page.

type TocEntry = { id: string; text: string; depth: number };

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/&[a-z]+;/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

function render(markdown: string): { html: string; toc: TocEntry[] } {
  const toc: TocEntry[] = [];
  const seen = new Set<string>();
  // marked ≥13 copies these methods onto its own renderer instance, so
  // `this` inside them is marked's renderer (with `.parser` attached) — not
  // this object. Fall back to the prototype for the parts we don't change.
  const renderer: Partial<Renderer> = {};

  renderer.heading = function (this: Renderer, { tokens, depth }: Tokens.Heading) {
    const inner = this.parser.parseInline(tokens);
    const plain = tokens.map((t) => ("text" in t ? (t as { text: string }).text : "")).join("");
    // "5.2 Packs — isolation at every layer" → "packs-isolation-at-every-layer":
    // drop the section number so anchors survive renumbering.
    let id = slugify(plain.replace(/^\d+(\.\d+)*\.?\s+/, "")) || `section-${toc.length}`;
    while (seen.has(id)) id = `${id}-`;
    seen.add(id);
    if (depth === 2 || depth === 3) toc.push({ id, text: plain, depth });
    return `<h${depth} id="${id}"><a class="anchor" href="#${id}" aria-hidden="true">#</a>${inner}</h${depth}>\n`;
  };

  // Wide inventory tables scroll inside their own box; the page never
  // scrolls horizontally.
  renderer.table = function (this: Renderer, token: Tokens.Table) {
    return `<div class="table-scroll">${Renderer.prototype.table.call(this, token)}</div>`;
  };

  const marked = new Marked();
  marked.use({ renderer });
  let html = marked.parse(markdown, { async: false }) as string;
  // Private catalog entries are marked 🔒 in the markdown; render the mark
  // as the same chip the catalog page uses so the two surfaces agree.
  html = html.replace(/🔒/g, '<span class="trust-chip private" title="Private — needs an entitlement">🔒 private</span>');
  return { html, toc };
}

export default function ImplementationPage() {
  const filePath = path.join(process.cwd(), "public", "IMPLEMENTATION.md");
  const markdown = fs.readFileSync(filePath, "utf8");
  const { html, toc } = render(markdown);

  const tocList = (
    <ol className="toc-list">
      {toc.map((e) => (
        <li key={e.id} className={e.depth === 3 ? "toc-sub" : undefined}>
          <a href={`#${e.id}`}>{e.text}</a>
        </li>
      ))}
    </ol>
  );

  return (
    <>
      <Header />
      <main className="container doc-layout" style={{ paddingTop: 48, paddingBottom: 96 }}>
        <aside className="doc-toc" aria-label="On this page">
          <div className="doc-toc-title">On this page</div>
          {tocList}
        </aside>
        <div className="prose doc-body">
          <details className="doc-toc-inline">
            <summary>On this page</summary>
            {tocList}
          </details>
          <div dangerouslySetInnerHTML={{ __html: html }} />
        </div>
      </main>
    </>
  );
}
