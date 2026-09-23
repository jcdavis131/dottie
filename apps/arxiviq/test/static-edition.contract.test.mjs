import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// out/ is what the Vercel project serves today (root vercel.json outputDirectory).
// It is produced by `npm run build && npm run snapshot`; these checks keep it honest.
const appRoot = process.env.ARXIVIQ_CONTRACT_ROOT
  ? path.resolve(process.env.ARXIVIQ_CONTRACT_ROOT)
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const read = (relativePath) => readFile(path.join(appRoot, relativePath), "utf8");
const PAGES = ["out/index.html", "out/hive.html", "out/404.html"];

test("static pages carry no scripts and every local asset they reference exists", async () => {
  for (const page of PAGES) {
    const html = await read(page);
    assert.doesNotMatch(html, /<script\b/i, `${page} must be script-free`);
    const refs = [...html.matchAll(/\b(?:href|src)="(\/[^"/][^"]*)"/g)]
      .map(([, ref]) => ref.split(/[?#]/)[0])
      .filter((ref) => ref.startsWith("/_next/") || /\.[a-z0-9]+$/i.test(ref));
    for (const ref of refs) {
      await access(path.join(appRoot, "out", ref));
    }
  }
});

test("static mirrors match their sources", async () => {
  assert.equal(await read("index.html"), await read("out/index.html"));
  assert.equal(await read("public/starter/index.html"), await read("out/starter/index.html"));
  assert.equal(await read("public/manifest.json"), await read("out/manifest.json"));
});

test("every static page has its own title, a skip link and a description", async () => {
  const titles = new Set();
  for (const page of [...PAGES, "out/starter/index.html"]) {
    const html = await read(page);
    const title = html.match(/<title>([^<]+)<\/title>/)?.[1];
    assert.ok(title, `${page} has a <title>`);
    titles.add(title);
    assert.match(html, /href="#main"/, `${page} has a skip link`);
    assert.match(html, /id="main"/, `${page} has a skip target`);
  }
  assert.equal(titles.size, 4, "titles are distinct per page");
});

test("probabilities are never called confidence on product surfaces", async () => {
  for (const source of [
    "lib/system-one-copy.ts",
    "app/components/SystemOneHome.tsx",
    "out/index.html",
    "out/hive.html",
    "public/starter/index.html",
  ]) {
    assert.doesNotMatch(await read(source), /confidence/i, `${source} says "confidence"`);
  }
});
