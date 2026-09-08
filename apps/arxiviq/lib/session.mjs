import {
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

export const SESSION_COOKIE = "__Host-arxiviq_session";
const SESSION_CAPS = [
  "claims:read",
  "goals:read",
  "conductor:read",
  "conductor:write",
];
const LOOPBACK_ORIGIN_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

export function validatePublicOrigin(origin) {
  if (typeof origin !== "string" || !origin) return null;
  try {
    const parsed = new URL(origin);
    const exact =
      parsed.origin === origin &&
      parsed.pathname === "/" &&
      parsed.search === "" &&
      parsed.hash === "" &&
      parsed.username === "" &&
      parsed.password === "";
    if (!exact) return null;
    if (parsed.protocol === "https:") return origin;
    if (
      parsed.protocol === "http:" &&
      LOOPBACK_ORIGIN_HOSTS.has(parsed.hostname.toLowerCase())
    ) {
      return origin;
    }
    return null;
  } catch {
    return null;
  }
}

function config(env) {
  const encoded = String(env.ARXIVIQ_SESSION_SECRET || "").trim();
  const bearer = String(env.JARVIS_BEARER || "").trim();
  const repo = String(env.ARXIVIQ_JARVIS_REPO || "").trim();
  if (!/^[A-Za-z0-9_-]+$/.test(encoded)) {
    throw new Error("ARXIVIQ_SESSION_SECRET must be base64url");
  }
  const secret = Buffer.from(encoded, "base64url");
  if (secret.length < 32) {
    throw new Error("ARXIVIQ_SESSION_SECRET must decode to at least 32 bytes");
  }
  if (encoded === bearer || secret.toString("utf8") === bearer) {
    throw new Error("ARXIVIQ_SESSION_SECRET must differ from JARVIS_BEARER");
  }
  if (!repo) throw new Error("ARXIVIQ_JARVIS_REPO is required");
  return { encoded, secret, repo };
}

export function validateSessionConfig(env = process.env) {
  config(env);
}

function encode(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function sign(unsigned, secret) {
  return createHmac("sha256", secret).update(unsigned).digest("base64url");
}

export function createSession({ agent, pairExp, now = Math.floor(Date.now() / 1000) }, env = process.env) {
  const { secret, repo } = config(env);
  const exp = Math.min(Number(pairExp), now + 600);
  if (!Number.isInteger(exp) || exp <= now) throw new Error("pairing is expired");
  const sid = randomBytes(18).toString("base64url");
  const sub = createHash("sha256")
    .update(`${sid}:${String(agent || "")}`)
    .digest("base64url")
    .slice(0, 32);
  const claims = {
    iss: "arxiviq",
    aud: "jarvisd",
    caps: SESSION_CAPS,
    iat: now,
    exp,
    sid,
    sub,
    repo,
  };
  const unsigned = `${encode({ alg: "HS256", typ: "JWT" })}.${encode(claims)}`;
  return { token: `${unsigned}.${sign(unsigned, secret)}`, claims, maxAge: exp - now };
}

export function readSession(token, env = process.env) {
  try {
    const { secret, repo } = config(env);
    const parts = String(token || "").split(".");
    if (parts.length !== 3) return null;
    const unsigned = `${parts[0]}.${parts[1]}`;
    const expected = Buffer.from(sign(unsigned, secret));
    const actual = Buffer.from(parts[2]);
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return null;
    const header = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8"));
    const claims = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
    const now = Number(env.now ?? Math.floor(Date.now() / 1000));
    if (
      header?.alg !== "HS256" ||
      header?.typ !== "JWT" ||
      claims?.iss !== "arxiviq" ||
      claims?.aud !== "jarvisd" ||
      claims?.repo !== repo ||
      !Array.isArray(claims?.caps) ||
      claims.caps.length !== SESSION_CAPS.length ||
      claims.caps.some((cap, index) => cap !== SESSION_CAPS[index]) ||
      !Number.isInteger(claims?.iat) ||
      !Number.isInteger(claims?.exp) ||
      claims.iat > now ||
      claims.exp <= now ||
      claims.exp - claims.iat > 600 ||
      typeof claims.sid !== "string" ||
      !/^[A-Za-z0-9_-]{24}$/.test(claims.sid) ||
      typeof claims.sub !== "string" ||
      !/^[A-Za-z0-9_-]{32}$/.test(claims.sub)
    ) {
      return null;
    }
    return claims;
  } catch {
    return null;
  }
}
