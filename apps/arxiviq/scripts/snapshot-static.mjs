#!/usr/bin/env node
// Writes the static edition of arxiviq.com into out/.
//
// The Vercel project currently serves apps/arxiviq/out as prebuilt static files
// (root vercel.json; see HANDOFF.md 2026-09-05). Rather than hand-maintaining a
// second copy of the homepage, this renders the pages that need no server
// (home, the hive, 404) from a production `next build`, strips every script so
// the result is plain HTML + CSS, and copies the assets those pages reference.
// Conductor and Pair need the server and are not part of the static edition.
//
// Usage: npm run build && npm run snapshot
import { spawn } from "node:child_process";
import { copyFile, mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = path.join(root, "out");
const port = Number(process.env.SNAPSHOT_PORT || 3931);
const origin = `http://127.0.0.1:${port}`;

const PAGES = [
  { route: "/", file: "index.html", status: 200 },
  { route: "/hive", file: "hive.html", status: 200 },
  { route: "/__static-edition-404__", file: "404.html", status: 404 },
];
const COPIES = [
  ["public/starter/index.html", "starter/index.html"],
  ["public/manifest.json", "manifest.json"],
  ["public/icon.svg", "icon.svg"],
  ["public/icon-192.png", "icon-192.png"],
  ["public/icon-512.png", "icon-512.png"],
];

function stripScripts(html) {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<link\b[^>]*\bas="script"[^>]*>/gi, "")
    .replace(/<link\b[^>]*\brel="modulepreload"[^>]*>/gi, "");
}

function assetPaths(html) {
  const found = new Set();
  const attr = /\b(?:href|src|content)="([^"]+)"/g;
  for (const [, raw] of html.matchAll(attr)) {
    let value = raw.replaceAll("&amp;", "&");
    if (value.startsWith("https://arxiviq.com/")) value = value.slice("https://arxiviq.com".length);
    if (!value.startsWith("/") || value.startsWith("//")) continue;
    const pathname = value.split(/[?#]/)[0];
    const isAsset = pathname.startsWith("/_next/") || /\.[a-z0-9]+$/i.test(pathname);
    if (isAsset && !pathname.endsWith(".html")) found.add(value);
  }
  return [...found];
}

async function waitForServer() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const res = await fetch(`${origin}/hive`);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`next start did not answer on ${origin}`);
}

const server = spawn(
  process.execPath,
  [path.join(root, "node_modules/next/dist/bin/next"), "start", "-p", String(port), "-H", "127.0.0.1"],
  { cwd: root, stdio: ["ignore", "ignore", "inherit"] },
);

try {
  await waitForServer();
  await rm(path.join(outDir, "_next"), { recursive: true, force: true });
  const assets = new Set();

  for (const page of PAGES) {
    const res = await fetch(origin + page.route);
    if (res.status !== page.status) {
      throw new Error(`${page.route} returned ${res.status}, expected ${page.status}`);
    }
    const html = stripScripts(await res.text());
    if (/<script\b/i.test(html)) throw new Error(`${page.route}: script survived stripping`);
    for (const asset of assetPaths(html)) assets.add(asset);
    await mkdir(path.dirname(path.join(outDir, page.file)), { recursive: true });
    await writeFile(path.join(outDir, page.file), html);
    console.log(`page   ${page.route} -> out/${page.file}`);
  }

  for (const asset of assets) {
    const pathname = asset.split(/[?#]/)[0];
    const res = await fetch(origin + asset);
    if (!res.ok) throw new Error(`${asset} returned ${res.status}`);
    const target = path.join(outDir, pathname);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, Buffer.from(await res.arrayBuffer()));
    console.log(`asset  ${pathname}`);
  }

  for (const [from, to] of COPIES) {
    await mkdir(path.dirname(path.join(outDir, to)), { recursive: true });
    await copyFile(path.join(root, from), path.join(outDir, to));
    console.log(`copy   ${from} -> out/${to}`);
  }

  // index.html at the app root has always mirrored out/index.html.
  await copyFile(path.join(outDir, "index.html"), path.join(root, "index.html"));
  console.log("mirror out/index.html -> index.html");
} finally {
  server.kill();
}
