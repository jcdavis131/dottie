import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = process.env.ARXIVIQ_CONTRACT_ROOT
  ? path.resolve(process.env.ARXIVIQ_CONTRACT_ROOT)
  : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function readJson(relativePath) {
  return JSON.parse(await readFile(path.join(appRoot, relativePath), "utf8"));
}

async function readSource(relativePath) {
  return readFile(path.join(appRoot, relativePath), "utf8");
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) return sourceFiles(target);
      return /\.[cm]?[jt]sx?$/.test(entry.name) ? [target] : [];
    }),
  );
  return nested.flat();
}

test("pins the reviewed Next 16 and React 19 dependency versions", async () => {
  const packageJson = await readJson("package.json");
  const packageLock = await readJson("package-lock.json");
  const expected = {
    next: "16.3.4",
    react: "19.2.8",
    "react-dom": "19.2.8",
  };

  assert.deepEqual(
    Object.fromEntries(Object.keys(expected).map((name) => [name, packageJson.dependencies[name]])),
    expected,
  );
  assert.deepEqual(
    Object.fromEntries(Object.keys(expected).map((name) => [name, packageLock.packages[""].dependencies[name]])),
    expected,
  );
  for (const [name, version] of Object.entries(expected)) {
    assert.equal(packageLock.packages[`node_modules/${name}`].version, version);
  }
});

test("pins the reviewed ESLint 9 and Next lint config versions", async () => {
  const packageJson = await readJson("package.json");
  const packageLock = await readJson("package-lock.json");
  const expected = {
    eslint: "9.39.5",
    "eslint-config-next": "16.3.4",
  };

  assert.deepEqual(
    Object.fromEntries(Object.keys(expected).map((name) => [name, packageJson.devDependencies[name]])),
    expected,
  );
  assert.deepEqual(
    Object.fromEntries(Object.keys(expected).map((name) => [name, packageLock.packages[""].devDependencies[name]])),
    expected,
  );
  for (const [name, version] of Object.entries(expected)) {
    assert.equal(packageLock.packages[`node_modules/${name}`].version, version);
  }
});

test("requires the Node version supported by Next 16", async () => {
  const packageJson = await readJson("package.json");
  const packageLock = await readJson("package-lock.json");

  assert.equal(packageJson.engines?.node, ">=20.9");
  assert.equal(packageLock.packages[""].engines?.node, ">=20.9");
});

test("keeps removed webpack and eslint keys out of Next config", async () => {
  const configUrl = new URL(`file://${path.join(appRoot, "next.config.js").replaceAll("\\", "/")}?contract=${Date.now()}`);
  const { default: nextConfig } = await import(configUrl);

  assert.equal(Object.hasOwn(nextConfig, "webpack"), false);
  assert.equal(Object.hasOwn(nextConfig, "eslint"), false);
  assert.equal(
    Object.hasOwn(nextConfig.typescript ?? {}, "ignoreBuildErrors"),
    false,
  );
});

test("awaits async searchParams on both conductor entry points", async () => {
  for (const relativePath of ["app/page.tsx", "app/conductor/page.tsx"]) {
    const source = await readSource(relativePath);

    assert.match(source, /searchParams\??:\s*Promise<\{[^}]*\}>/s, `${relativePath} must type searchParams as a Promise`);
    assert.match(source, /const\s+params\s*=\s*await\s+searchParams\s*;/, `${relativePath} must await searchParams`);
  }
});

test("uses ESLint 9 flat config with Next core and TypeScript presets", async () => {
  const source = await readSource("eslint.config.mjs");

  assert.match(source, /from\s+["']eslint\/config["']/);
  assert.match(source, /from\s+["']eslint-config-next\/core-web-vitals["']/);
  assert.match(source, /from\s+["']eslint-config-next\/typescript["']/);
  assert.match(source, /ignores:\s*\["app\/acd\/\*\*"\]/);
  assert.match(source, /\.\.\.nextVitals,\s*\.\.\.nextTypeScript/s);
});

test("keeps dormant browser-local ACD simulation outside the product graph", async () => {
  const acdRoot = path.join(appRoot, "app", "acd");
  const files = (
    await Promise.all([sourceFiles(path.join(appRoot, "app")), sourceFiles(path.join(appRoot, "lib"))])
  )
    .flat()
    .filter((file) => file !== acdRoot && !file.startsWith(`${acdRoot}${path.sep}`));
  const violations = [];
  const staticImport = /\b(?:import|export)\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']/g;
  const dynamicImport = /\b(?:import|require)\(\s*["']([^"']+)["']\s*\)/g;

  for (const file of files) {
    const source = await readFile(file, "utf8");
    const imports = [...source.matchAll(staticImport), ...source.matchAll(dynamicImport)];
    for (const match of imports) {
      const specifier = match[1];
      const normalized = specifier.replaceAll("\\", "/");
      const resolved = specifier.startsWith(".")
        ? path.resolve(path.dirname(file), specifier)
        : null;
      const importsAcd =
        normalized === "app/acd" ||
        normalized.includes("/app/acd") ||
        (resolved !== null && (resolved === acdRoot || resolved.startsWith(`${acdRoot}${path.sep}`)));
      if (importsAcd || /\bAcdDaemon\b/.test(match[0])) {
        violations.push(`${path.relative(appRoot, file)} -> ${specifier}`);
      }
    }
  }

  assert.deepEqual(
    violations,
    [],
    `Product files must not import app/acd or AcdDaemon:\n${violations.join("\n")}`,
  );
});
