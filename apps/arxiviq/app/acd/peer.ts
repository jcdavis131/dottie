/**
 * Invariant 02: Local & remote are peers — same `acd` binary ships on laptop
 * and on every remote host. No `is_local` branch anywhere.
 * Zero-deps peer abstraction.
 */

export interface AcOps {
  spawnAgent(cloneId:string, task:string, env?:Record<string,string>): Promise<{agentId:string}>;
  attachPty(sessionId:string): Promise<{sessionId:string; history:Uint8Array[]}>;
  readFile(path:string): Promise<Uint8Array>;
  writeFile(path:string, content:Uint8Array): Promise<number>;
  hostIsl(host:string, port:number): Promise<string>;
  ping(ts:number): Promise<number>;
}

export type PeerLocation = 'laptop' | 'devserver' | 'unknown';

export class AcPeer implements AcOps {
  public readonly location: PeerLocation;
  public readonly binaryHash: string;
  public readonly wireVersion: number = 6; // bump when RPC shape changes

  constructor(opts: { location: PeerLocation; binaryHash?: string }) {
    this.location = opts.location;
    // Same binary ships everywhere — hash should match peer's hash (Invariant 03)
    this.binaryHash = opts.binaryHash ?? 'acd-v6-placeholder-hash';
  }

  // No is_local branch — identical codepaths for both sides
  async spawnAgent(cloneId:string, task:string, env?:Record<string,string>) {
    // In real impl, delegates to daemon.ts ownPty via RPC
    return { agentId: `agt_${cloneId}_${Date.now()}` };
  }

  async attachPty(sessionId:string) {
    return { sessionId, history: [] as Uint8Array[] };
  }

  async readFile(path:string) {
    // Typed RPC only — no shell
    return new TextEncoder().encode(`// stub content of ${path}`);
  }

  async writeFile(path:string, content:Uint8Array) {
    return content.length;
  }

  async hostIsl(host:string, port:number) {
    return `ws://${host}:${port}/isl`;
  }

  async ping(ts:number) {
    return Date.now() - ts;
  }

  // Peer negotiation — no branch on locality, just hash equality
  async handshake(peer: AcPeer): Promise<{ compatible:boolean; needsRedeploy:boolean }> {
    const sameHash = this.binaryHash === peer.binaryHash;
    const sameWire = this.wireVersion === peer.wireVersion;
    return { compatible: sameHash && sameWire, needsRedeploy: !sameHash };
  }
}

// Factory — caller never asks is_local? we just pick same class
export function createPeer(location: PeerLocation = 'unknown', binaryHash?: string): AcPeer {
  return new AcPeer({ location, binaryHash });
}

// Example: ensures binary ships to remote via same path
export const ACD_BINARY_PATHS = {
  laptop: '~/.acd/bin/acd',
  remote: '~/.acd/bin/acd', // same relative — no divergence
} as const;
