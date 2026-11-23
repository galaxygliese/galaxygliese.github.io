// Render every equation in public/ with KaTeX (throwOnError) and fail on any error.
// Usage: node tools/check-math.mjs [public-dir]
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import katex from "katex";

const root = process.argv[2] || "public";
const unescape = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const files = [];
(function walk(dir) {
  for (const f of readdirSync(dir)) {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) walk(p); else if (p.endsWith(".html")) files.push(p);
  }
})(root);

let errors = 0, count = 0;
for (const file of files) {
  const html = readFileSync(file, "utf8");
  for (const m of html.matchAll(/<span\s+class="math (inline|display)">([\s\S]*?)<\/span>/g)) {
    count++;
    const tex = unescape(m[2]);
    try {
      katex.renderToString(tex, { displayMode: m[1] === "display", throwOnError: true, strict: "ignore" });
    } catch (e) {
      errors++;
      console.error(`\n✗ ${file}\n  ${tex.trim().slice(0, 200)}\n  ${e.message}`);
    }
  }
}
console.log(`KaTeX: ${count} equations checked in ${files.length} files, ${errors} error(s).`);
process.exit(errors ? 1 : 0);
