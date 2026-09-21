import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = process.env.ARXIVIQ_CONTRACT_ROOT
  ? path.resolve(process.env.ARXIVIQ_CONTRACT_ROOT)
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function readSource(relativePath) {
  return readFile(path.join(appRoot, relativePath), "utf8");
}

const SURFACES = [
  "app/page.tsx",
  "app/layout.tsx",
  "app/components/SystemOneHome.tsx",
  "lib/system-one-copy.ts",
  "index.html",
  "out/index.html",
  "public/starter/index.html",
  "out/starter/index.html",
  "public/manifest.json",
  "app/hive/page.tsx",
];

const REQUIRED = [
  /dottie-os/,
  /System One/,
  /Choice/,
  /Score/,
  /Noul/,
  /Laya/,
  /execute/,
  /escalate/,
  /halt/,
];

const FORBIDDEN = [
  /always-on AGI factory/i,
  /the always-on AGI factory you can watch train/i,
  /ava-agi-factory-v6-4/i,
  /Alienware 10M/i,
  /Hatch VM/i,
  /WSD warmup/i,
  /base1b 1\.17B/i,
  /\bNanoJev\b/,
  /\bOpenJev\b/,
  /\bNanoJev-Data\b/,
  /127\.0\.0\.1:8770/,
  /nugatron/i,
];

test("marketing surfaces carry System One hero language", async () => {
  const homepage = await Promise.all(
    ["lib/system-one-copy.ts", "out/index.html", "index.html"].map(readSource),
  );
  for (const [index, source] of homepage.entries()) {
    for (const pattern of REQUIRED) {
      assert.match(
        source,
        pattern,
        `${["system-one-copy", "out/index.html", "index.html"][index]} missing ${pattern}`,
      );
    }
  }
  const home = await readSource("app/components/SystemOneHome.tsx");
  assert.match(home, /from "\.\.\/\.\.\/lib\/system-one-copy"/);
  assert.match(home, /PRIMITIVES/);
  assert.match(home, /CHAMPION/);
});

test("marketing surfaces drop AGI-factory / private-host hero language", async () => {
  for (const relativePath of SURFACES) {
    const source = await readSource(relativePath);
    for (const pattern of FORBIDDEN) {
      assert.doesNotMatch(source, pattern, `${relativePath} still contains ${pattern}`);
    }
  }
});

test("champion stamp is static and does not publish a decide host", async () => {
  const stamp = JSON.parse(await readSource("public/champion-stamp.json"));
  const copy = await readSource("lib/system-one-copy.ts");
  assert.equal(stamp.helper, "Laya");
  assert.equal(stamp.mode, "CHAMPION");
  assert.equal(stamp.surface, "on your tailnet");
  assert.match(stamp.smoke, /does not curl a private host/);
  assert.equal(stamp.ckpt_id, "not published on this page");
  assert.equal(stamp.pack_rows, "not published as a live meter");
  assert.match(copy, /helper: "Laya"/);
  assert.match(copy, /surface: "on your tailnet"/);
});

test("tandem query still routes to conductor", async () => {
  const source = await readSource("app/page.tsx");
  assert.match(source, /searchParams\??:\s*Promise<\{[^}]*\}>/s);
  assert.match(source, /const\s+params\s*=\s*await\s+searchParams\s*;/);
  assert.match(source, /redirect\("\/conductor\?tandem=1"\)/);
});
