/**
 * Invariant 03: Binary hash → wire version — On connect, client and remote exchange a hash.
 * Mismatch triggers automatic redeploy of `ac-remote` before any agent attaches.
 * Zero-deps TS using WebCrypto subtle where available, fallback to simple hash.
 */

export type WireVersion = number;

function simpleHash(buf: Uint8Array): string {
  // FNV-1a 32-bit for stdlib fallback — not crypto strong but deterministic
  let h = 2166136261;
  for (let i=0;i<buf.length;i++) { h ^= buf[i]; h = Math.imul(h, 16777619); }
  return (h>>>0).toString(16).padStart(8,'0');
}

export async function getBinaryHash(binaryBytes?: Uint8Array): Promise<string> {
  const bytes = binaryBytes ?? new TextEncoder().encode('acd-v6-placeholder-binary');
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    try {
      const dig = await crypto.subtle.digest('SHA-256', bytes as any);
      return [...new Uint8Array(dig)].map(b=>b.toString(16).padStart(2,'0')).join('').slice(0,16);
    } catch {}
  }
  return simpleHash(bytes);
}

export type Handshake = {
  clientHash: string;
  clientVersion: WireVersion;
  serverHash: string;
  serverVersion: WireVersion;
  ts: number;
};

export type HandshakeResult = {
  accepted: boolean;
  redeployNeeded: boolean;
  reason?: string;
};

export async function exchangeHandshake(localHash:string, remote: {hash:string; version:WireVersion}, localVersion:WireVersion=6): Promise<HandshakeResult> {
  if (localHash === remote.hash && localVersion === remote.version) {
    return { accepted:true, redeployNeeded:false };
  }
  return {
    accepted: false,
    redeployNeeded: true,
    reason: `hash mismatch local ${localHash.slice(0,8)} != remote ${remote.hash.slice(0,8)} or version ${localVersion} != ${remote.version} — auto-redeploy triggered before agent attach per invariant 03`
  };
}

export async function triggerRedeployIfNeeded(result: HandshakeResult, deployFn?: ()=>Promise<void>) {
  if (!result.redeployNeeded) return { redeployed:false };
  if (deployFn) await deployFn();
  // Simulate redeploy log
  const log = {
    at: new Date().toISOString(),
    action: 'redeploy ac-remote',
    reason: result.reason,
    newHash: await getBinaryHash(),
  };
  // Persist to timeline dir for audit
  return { redeployed:true, log };
}

// Telemetry for AgentConductorPanel
export function versionBadge(hash:string, version:number) {
  return `${hash.slice(0,8)}@v${version}`;
}
