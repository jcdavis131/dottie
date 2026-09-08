import { createHmac } from "node:crypto";
import { isIP } from "node:net";

type Bucket = { window: number; count: number };
type PairScope = "status" | "verify";
type RequestLike = {
  headers: { get(name: string): string | null };
  nextUrl: URL;
};
export type PairClient =
  | { ok: true; agentId: string }
  | { ok: false; error: "pair client identity unavailable" };

const rateGlobal = globalThis as typeof globalThis & {
  __dottiePairRateBuckets?: Map<string, Bucket>;
};
const buckets =
  rateGlobal.__dottiePairRateBuckets || new Map<string, Bucket>();
rateGlobal.__dottiePairRateBuckets = buckets;

function trustedHeaderName(raw: string | undefined): string | null {
  const name = String(raw || "").trim().toLowerCase();
  return /^[a-z0-9-]+$/.test(name) ? name : null;
}

function isExactLocalRequest(req: RequestLike, env: NodeJS.ProcessEnv): boolean {
  const configured = String(env.ARXIVIQ_PUBLIC_ORIGIN || "");
  try {
    const origin = new URL(configured);
    return (
      origin.origin === configured &&
      origin.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]", "::1"].includes(origin.hostname.toLowerCase()) &&
      (req.headers.get("origin") === configured ||
        req.headers.get("host") === origin.host)
    );
  } catch {
    return false;
  }
}

export function resolvePairClient(
  req: RequestLike,
  scope: PairScope,
  env: NodeJS.ProcessEnv = process.env
): PairClient {
  const secret = String(env.JARVIS_BEARER || "");
  if (!secret) return { ok: false, error: "pair client identity unavailable" };

  let identity: string | null = null;
  if (env.VERCEL === "1") {
    identity = req.headers.get("x-vercel-forwarded-for")?.trim() || null;
  } else {
    const configuredHeader = trustedHeaderName(env.ARXIVIQ_TRUSTED_CLIENT_IP_HEADER);
    if (configuredHeader) {
      identity = req.headers.get(configuredHeader)?.trim() || null;
    } else if (isExactLocalRequest(req, env)) {
      identity = "local-loopback";
    }
  }
  if (identity !== "local-loopback" && (!identity || isIP(identity) === 0)) {
    return { ok: false, error: "pair client identity unavailable" };
  }
  const pseudonym = createHmac("sha256", secret)
    .update(identity)
    .digest("hex")
    .slice(0, 32);
  return { ok: true, agentId: `arxiviq-pair-${scope}-${pseudonym}` };
}

export function allowPairRequest(
  client: Extract<PairClient, { ok: true }>,
  limit: number
): boolean {
  const window = Math.floor(Date.now() / 60_000);
  const key = client.agentId;
  const current = buckets.get(key);
  const count = current?.window === window ? current.count : 0;
  if (count >= limit) return false;
  buckets.delete(key);
  buckets.set(key, { window, count: count + 1 });
  while (buckets.size > 2048) {
    const oldest = buckets.keys().next().value;
    if (oldest === undefined) break;
    buckets.delete(oldest);
  }
  return true;
}
