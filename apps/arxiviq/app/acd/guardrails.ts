/**
 * Invariant 07: Guardrails — first-class safety nets on top of 6 load-bearing invariants.
 * Zero-deps TS, single daemon enforces, thin UI only shows status.
 *
 * Screenshots blueprint:
 * - Session dies → reliable sessions warm, <300ms reconnect, full history
 * - Yubikey x3 → one touch covers PTY|file|ISL, exponential backoff
 * - 1 agent 1 window → parallel fbclone multi-agent
 *
 * Guardrails added (next swarm focus):
 * - Approval modes auto/manual — destructive always needs manual even in auto
 * - Quotas (PTYs, memory, reconnect)
 * - Session expiry 48h → snapshot + pause, resume days later with receipts
 * - Auth re-check on hash change / 24h
 * - INV-01 snapshot <300ms
 * - Rate limit 60/min per agent, 1k/min per host
 *
 * Everyday language: "We keep sessions safe, not bossy."
 * Zero-deps true, stdlib only.
 */

// --- Legacy simple policy (kept for compat) ---
export type GuardrailPolicy = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  severity: 'low'|'medium'|'high'|'block';
  pattern?: string;
  maxAttempts?: number;
};

export type GuardrailViolation = {
  policyId: string;
  agentId?: string;
  input: string;
  ts: number;
  blocked: boolean;
  reason: string;
};

// --- 7-field timeline ---
export type TimelineEntry = {
  nodeId: string;
  agentId: string;
  attempt: number;
  latency_ms: number;
  tokens_est: number;
  status: 'ok' | 'error' | 'blocked' | 'needs_approval';
  errorClass: string;
  ts?: string;
  extra?: Record<string, unknown>;
};

function tripleWriteLog(entry: TimelineEntry, paths: string[]) {
  const line = JSON.stringify({ ...entry, ts: entry.ts ?? new Date().toISOString() }) + '\n';
  try {
    // @ts-ignore — zero-deps lazy require, works in node
    const fs = (globalThis as any).require?.('fs');
    const path = (globalThis as any).require?.('path');
    if (fs && path) {
      for (const p of paths) {
        try {
          const cwd = (globalThis as any).process?.cwd?.() ?? (globalThis as any).process?.cwd ?? '/tmp';
          const full = typeof cwd === 'function' ? path.resolve((globalThis as any).process.cwd(), p) : path.resolve(cwd, p);
          const dir = path.dirname(full);
          fs.mkdirSync(dir, { recursive: true });
          fs.appendFileSync(full, line, 'utf8');
        } catch {}
      }
    }
  } catch {}
  try { console.log(`[guardrails] ${entry.nodeId} ${entry.agentId} ${entry.status} ${entry.errorClass}`); } catch {}
}

// --- Approval Guard ---
export type ApprovalMode = 'auto' | 'manual';
export type DestructiveKind = 'rm_rf'|'git_force_push'|'db_drop'|'db_truncate'|'fs_format'|'unknown_destructive'|'no_shell';
export type GuardDecision =
  | { allowed: true; reason?: string }
  | { allowed: false; needsApproval: true; kind: DestructiveKind; preview: string; reason: string }
  | { allowed: false; needsApproval: false; reason: string };

const DESTRUCTIVE_PATTERNS: Array<{ kind: DestructiveKind; re: RegExp; desc: string }> = [
  { kind: 'rm_rf', re: /\brm\s+.*-r[f]?\b|\brm\s+-rf\b|\brm\s+-r\b/i, desc: 'rm -rf recursive delete' },
  { kind: 'rm_rf', re: /rmdir\s+\//, desc: 'rmdir root' },
  { kind: 'git_force_push', re: /git\s+push\s+.*(--force|-f)\b/, desc: 'git push --force' },
  { kind: 'db_drop', re: /\bDROP\s+(DATABASE|SCHEMA|TABLE)\b/i, desc: 'db DROP' },
  { kind: 'db_truncate', re: /\bTRUNCATE\s+TABLE\b/i, desc: 'TRUNCATE TABLE' },
  { kind: 'fs_format', re: /\b(mkfs|fdisk|diskutil\s+eraseDisk)\b/i, desc: 'format disk' },
  { kind: 'no_shell', re: /(bash\s+-c|sh\s+-c|\bchild_process\.exec|\$\(|`)/i, desc: 'shell injection — use typed RPC' },
];

export class ApprovalGuard {
  private mode: ApprovalMode = 'auto';
  private pending = new Map<string, { kind: DestructiveKind; preview: string; at: number; requester: string }>();
  setMode(m: ApprovalMode) { this.mode = m; }
  getMode() { return this.mode; }

  check(op: { command?: string; sql?: string; task?: string; requester?: string }): GuardDecision {
    const text = `${op.command ?? ''} ${op.sql ?? ''} ${op.task ?? ''}`.trim();
    if (!text) return { allowed: true };
    for (const p of DESTRUCTIVE_PATTERNS) {
      if (p.re.test(text)) {
        return {
          allowed: false,
          needsApproval: true,
          kind: p.kind,
          preview: text.slice(0, 160),
          reason: `Destructive '${p.desc}' always needs manual approval, even in ${this.mode}`,
        };
      }
    }
    if (this.mode === 'manual') {
      const mutateRe = /(git\s+push|npm\s+publish|kubectl\s+delete|docker\s+system\s+prune)/i;
      if (mutateRe.test(text)) {
        return {
          allowed: false,
          needsApproval: true,
          kind: 'unknown_destructive',
          preview: text.slice(0, 160),
          reason: `Manual mode: '${text.slice(0,40)}…' needs explicit OK`,
        };
      }
    }
    return { allowed: true };
  }

  queue(id: string, kind: DestructiveKind, preview: string, requester='unknown') {
    this.pending.set(id, { kind, preview, at: Date.now(), requester });
    return id;
  }
  approve(id: string){ return this.pending.delete(id); }
  deny(id: string){ return this.pending.delete(id); }
  pendingList(){ return [...this.pending.entries()].map(([id,v])=>({ id, ...v })); }
}

// --- Quota Guard ---
export type QuotaConfig = {
  maxPtysPerHost: number;
  maxMemoryPerSessionMB: number;
  maxTunnelReconnectAttempts: number;
  reconnectBackoffMs: number[];
};
const DEFAULT_QUOTAS: QuotaConfig = {
  maxPtysPerHost: 8,
  maxMemoryPerSessionMB: 512,
  maxTunnelReconnectAttempts: 5,
  reconnectBackoffMs: [1000,2000,4000,8000,16000],
};
export class QuotaGuard {
  private cfg: QuotaConfig;
  private ptyCounts = new Map<string, number>();
  private memUsed = new Map<string, number>();
  private reconnectAttempts = new Map<string, number>();
  constructor(cfg: Partial<QuotaConfig> = {}){ this.cfg = { ...DEFAULT_QUOTAS, ...cfg }; }
  canCreatePty(host: string): GuardDecision {
    const c = this.ptyCounts.get(host) ?? 0;
    if (c >= this.cfg.maxPtysPerHost) return { allowed:false, needsApproval:false, reason:`PTY quota: ${host} has ${c}/${this.cfg.maxPtysPerHost} — close one first` };
    return { allowed:true };
  }
  recordPtyCreate(host:string, sessionId:string, memMb=32){ this.ptyCounts.set(host,(this.ptyCounts.get(host)??0)+1); this.memUsed.set(sessionId, memMb); }
  recordPtyClose(host:string, sessionId:string){ this.ptyCounts.set(host, Math.max(0,(this.ptyCounts.get(host)??1)-1)); this.memUsed.delete(sessionId); }
  checkMemory(sessionId:string, proposedMb:number): GuardDecision {
    if (proposedMb > this.cfg.maxMemoryPerSessionMB) return { allowed:false, needsApproval:false, reason:`Memory guard: ${proposedMb}MB > ${this.cfg.maxMemoryPerSessionMB}MB cap` };
    return { allowed:true };
  }
  canReconnect(tunnelId:string){ const a=this.reconnectAttempts.get(tunnelId)??0; if (a>=this.cfg.maxTunnelReconnectAttempts) return { allowed:false, backoffMs:30000, attempt:a }; const b=this.cfg.reconnectBackoffMs[a]??16000; const j=Math.floor(Math.random()*200); return { allowed:true, backoffMs:Math.min(b+j,30000), attempt:a+1 }; }
  recordReconnectAttempt(tunnelId:string){ this.reconnectAttempts.set(tunnelId,(this.reconnectAttempts.get(tunnelId)??0)+1); }
  resetReconnect(tunnelId:string){ this.reconnectAttempts.delete(tunnelId); }
  getConfig(){ return this.cfg; }
  status(){ return { ptysByHost:Object.fromEntries(this.ptyCounts), totalPtys:[...this.ptyCounts.values()].reduce((a,b)=>a+b,0), reconnecting:Object.fromEntries(this.reconnectAttempts), cfg:this.cfg }; }
}

// --- Session Expiry Guard ---
export type WarmSession = { id:string; host:string; createdAt:number; lastActiveAt:number; warm:boolean; pausedAt?:number; receipt?:{ snapshotPath:string; historyLen:number; reason:string } };
export class SessionExpiryGuard {
  static readonly WARM_MAX_MS = 48*3600*1000;
  private sessions = new Map<string, WarmSession>();
  track(id:string, host:string){ const now=Date.now(); if(!this.sessions.has(id)) this.sessions.set(id,{id,host,createdAt:now,lastActiveAt:now,warm:true}); }
  touch(id:string){ const s=this.sessions.get(id); if(s) s.lastActiveAt=Date.now(); }
  sweep(now=Date.now()): WarmSession[]{ const out:WarmSession[]=[]; for(const s of this.sessions.values()){ if(!s.warm) continue; const age=now-s.createdAt; const idle=now-s.lastActiveAt; if(age>SessionExpiryGuard.WARM_MAX_MS||idle>SessionExpiryGuard.WARM_MAX_MS){ s.warm=false; s.pausedAt=now; s.receipt={ snapshotPath:`/tmp/acd-snap-${s.id}.json`, historyLen:0, reason:`warm >48h (age ${Math.floor(age/3600000)}h idle ${Math.floor(idle/3600000)}h) — snapshot+pause, resume with receipts` }; out.push(s); } } return out; }
  resume(id:string){ const s=this.sessions.get(id); if(!s) return null; if(!s.pausedAt) return s; s.warm=true; s.lastActiveAt=Date.now(); s.pausedAt=undefined; return s; }
  list(){ return [...this.sessions.values()]; }
  paused(){ return [...this.sessions.values()].filter(s=>!s.warm); }
}

// --- Auth Guard ---
export class AuthGuard {
  static readonly REAUTH_MS = 24*3600*1000;
  private lastTouchAt=0; private lastBinaryHash=''; private tag='';
  touch(tag:string,binaryHash:string){ this.lastTouchAt=Date.now(); this.tag=tag; this.lastBinaryHash=binaryHash; }
  isValid(currentBinaryHash:string, now=Date.now()):{ valid:boolean; reason?:string }{
    if(!this.lastTouchAt) return { valid:false, reason:'never touched — Yubi needed' };
    if(currentBinaryHash && this.lastBinaryHash && currentBinaryHash!==this.lastBinaryHash) return { valid:false, reason:`binary changed ${this.lastBinaryHash.slice(0,8)}→${currentBinaryHash.slice(0,8)} — re-touch required` };
    if(now-this.lastTouchAt>AuthGuard.REAUTH_MS) return { valid:false, reason:`Yubi expired ${Math.floor((now-this.lastTouchAt)/3600000)}h ago (>24h)` };
    return { valid:true };
  }
  covers(){ return ['pty','file','isl','rpc'] as const; }
  getTag(){ return this.tag; }
  hoursSinceTouch(now=Date.now()){ return this.lastTouchAt ? (now-this.lastTouchAt)/3600000 : Infinity; }
  get lastHash(){ return this.lastBinaryHash; }
}

// --- Rate Limiter ---
type Bucket = { stamps:number[] };
export class RateLimiter {
  private agentBuckets=new Map<string,Bucket>(); private hostBuckets=new Map<string,Bucket>();
  private readonly perAgentMax=60; private readonly perHostMax=1000; private readonly windowMs=60_000;
  private prune(b:Bucket,now:number){ b.stamps=b.stamps.filter(t=>now-t<this.windowMs); }
  check(agentId:string,hostId:string,now=Date.now()): GuardDecision {
    const ab=this.agentBuckets.get(agentId)??{stamps:[]}; const hb=this.hostBuckets.get(hostId)??{stamps:[]};
    this.prune(ab,now); this.prune(hb,now);
    if(ab.stamps.length>=this.perAgentMax) return { allowed:false, needsApproval:false, reason:`Rate limit agent ${agentId} ${ab.stamps.length}/${this.perAgentMax}/min` };
    if(hb.stamps.length>=this.perHostMax) return { allowed:false, needsApproval:false, reason:`Rate limit host ${hostId} ${hb.stamps.length}/${this.perHostMax}/min` };
    return { allowed:true };
  }
  record(agentId:string,hostId:string,now=Date.now()){ const ab=this.agentBuckets.get(agentId)??{stamps:[]}; const hb=this.hostBuckets.get(hostId)??{stamps:[]}; ab.stamps.push(now); hb.stamps.push(now); this.agentBuckets.set(agentId,ab); this.hostBuckets.set(hostId,hb); }
  status(agentId?:string,hostId?:string){ if(agentId){const b=this.agentBuckets.get(agentId); return {agent:agentId,count:b?.stamps.length??0,limit:this.perAgentMax};} if(hostId){const b=this.hostBuckets.get(hostId); return {host:hostId,count:b?.stamps.length??0,limit:this.perHostMax};} return {agents:this.agentBuckets.size,hosts:this.hostBuckets.size}; }
}

// --- IPC Guard ---
export class IpcGuard {
  static readonly SNAPSHOT_MAX_MS=300;
  private last=0; private violations=0;
  measure(fn:()=>unknown){ const s=Date.now(); fn(); const e=Date.now()-s; this.last=e; if(e>IpcGuard.SNAPSHOT_MAX_MS) this.violations++; return { ok:e<=IpcGuard.SNAPSHOT_MAX_MS, elapsedMs:e }; }
  async measureAsync(fn:()=>Promise<unknown>){ const s=Date.now(); await fn(); const e=Date.now()-s; this.last=e; if(e>IpcGuard.SNAPSHOT_MAX_MS) this.violations++; return { ok:e<=IpcGuard.SNAPSHOT_MAX_MS, elapsedMs:e }; }
  getStatus(){ return { lastSnapshotMs:this.last, violations:this.violations, maxMs:IpcGuard.SNAPSHOT_MAX_MS }; }
}

// --- GuardrailRegistry compat + full Guardrails orchestrator ---
export class GuardrailRegistry {
  // legacy simple policy layer
  private policies: Map<string, GuardrailPolicy> = new Map();
  private violations: GuardrailViolation[] = [];
  private attempts: Map<string, number> = new Map();

  // new first-class guardrails
  public readonly approval: ApprovalGuard;
  public readonly quota: QuotaGuard;
  public readonly expiry: SessionExpiryGuard;
  public readonly auth: AuthGuard;
  public readonly rate: RateLimiter;
  public readonly ipc: IpcGuard;

  private nodeId: string;
  private timelinePaths: string[];

  constructor(opts?: { nodeId?: string; quotas?: Partial<QuotaConfig>; timelinePaths?: string[] }) {
    this.approval = new ApprovalGuard();
    this.quota = new QuotaGuard(opts?.quotas);
    this.expiry = new SessionExpiryGuard();
    this.auth = new AuthGuard();
    this.rate = new RateLimiter();
    this.ipc = new IpcGuard();
    this.nodeId = opts?.nodeId ?? 'guardrails-lane';
    this.timelinePaths = opts?.timelinePaths ?? [
      'bundles/ultra/runs/guardrails-lane/timeline.jsonl',
      '.scout/missions/guardrails-lane/timeline.jsonl',
      'dottie/bundles/ultra/runs/guardrails-lane/timeline.jsonl',
    ];

    // default policies — screenshot blueprint first-class
    this.register({ id:'no-shell-injection', name:'No Shell Injection', description:'Blocks bash -c, sh -c, $(), backticks, child_process.exec — invariant 06', enabled:true, severity:'block', pattern:'(bash\\s+-c|sh\\s+-c|\\$\\(|child_process\\.exec|\\bexec\\s*\\()' });
    this.register({ id:'pty-rate-limit', name:'PTY Create Rate Limit', description:'Max 20 PTY creates / min / agent — prevents fork bomb', enabled:true, severity:'high', maxAttempts:20 });
    this.register({ id:'file-write-boundary', name:'File Write Boundary', description:'Deny writes to /etc, /usr, *.pem, .env outside project', enabled:true, severity:'block', pattern:'(^/etc/|^/usr/|\\.pem$|\\.env$)' });
    this.register({ id:'secret-egress', name:'Secret Egress Guard', description:'Blocks raw dm_dev_ keys in logs / network plaintext', enabled:true, severity:'block', pattern:'(dm_dev_[A-Za-z0-9]{20,})' });
    this.register({ id:'destructive-ops', name:'Destructive Ops Manual Approval', description:'rm -rf, git push --force, DROP DATABASE always need manual even in auto mode', enabled:true, severity:'block', pattern:'(rm\\s+.*-rf|git\\s+push\\s+.*--force|DROP\\s+DATABASE)' });
  }

  // legacy API
  register(p: GuardrailPolicy){ this.policies.set(p.id,p); }
  list(): GuardrailPolicy[]{ return [...this.policies.values()]; }
  toggle(id:string,enabled:boolean){ const p=this.policies.get(id); if(p) p.enabled=enabled; return p; }
  check(input:string,agentId?:string):{ ok:boolean; violations:GuardrailViolation[] }{
    const out: GuardrailViolation[]=[];
    for(const pol of this.policies.values()){
      if(!pol.enabled) continue;
      let hit=false;
      if(pol.pattern){ try{ hit=new RegExp(pol.pattern,'i').test(input); }catch{ hit=input.includes(pol.pattern); } }
      if(pol.maxAttempts && agentId){ const key=`${agentId}:${pol.id}`; const cnt=(this.attempts.get(key)??0)+1; this.attempts.set(key,cnt); if(cnt>pol.maxAttempts) hit=true; }
      if(hit){ const blocked=pol.severity==='block'||pol.severity==='high'; const v:GuardrailViolation={ policyId:pol.id, agentId, input:input.slice(0,200), ts:Date.now(), blocked, reason:pol.description }; this.violations.push(v); if(this.violations.length>200) this.violations.shift(); out.push(v); if(blocked) break; }
    }
    return { ok: out.length===0 || !out.some(v=>v.blocked), violations:out };
  }
  recent(n=20){ return this.violations.slice(-n).reverse(); }

  // --- unified enforcement ---
  log(entry: TimelineEntry){ tripleWriteLog(entry, this.timelinePaths); }

  enforceRpc(opts:{ agentId:string; hostId:string; method:string; payload:any; binaryHash:string; yubiTag?:string }): GuardDecision {
    const start=Date.now();
    // rate
    const rl=this.rate.check(opts.agentId, opts.hostId);
    if(!rl.allowed){
      this.log({ nodeId:this.nodeId, agentId:opts.agentId, attempt:1, latency_ms:Date.now()-start, tokens_est:12, status:'blocked', errorClass:'RATE_LIMIT', extra:{ method:opts.method, reason:(rl as any).reason } });
      return rl;
    }
    // auth except handshake/ping
    if(!['version.handshake','heartbeat.ping'].includes(opts.method)){
      const ac=this.auth.isValid(opts.binaryHash);
      if(!ac.valid){
        this.log({ nodeId:this.nodeId, agentId:opts.agentId, attempt:1, latency_ms:Date.now()-start, tokens_est:16, status:'blocked', errorClass:'AUTH_REQUIRED', extra:{ reason:ac.reason } });
        return { allowed:false, needsApproval:false, reason:ac.reason! };
      }
    }
    // destructive via approval guard
    const cmdLike = opts.payload?.command ?? opts.payload?.task ?? JSON.stringify(opts.payload ?? '').slice(0,300);
    const ap=this.approval.check({ command:cmdLike, requester:opts.agentId });
    if(!ap.allowed) {
      const isApproval = (ap as any).needsApproval;
      this.log({
        nodeId:this.nodeId,
        agentId:opts.agentId,
        attempt:1,
        latency_ms:Date.now()-start,
        tokens_est:20,
        status: isApproval ? 'needs_approval' : 'blocked',
        errorClass: (ap as any).kind ?? 'DESTRUCTIVE',
        extra:{ preview:(ap as any).preview, mode:this.approval.getMode() },
      });
      return ap;
    }
    // quota — PTY create
    if(opts.method==='pty.create'){
      const q=this.quota.canCreatePty(opts.hostId);
      if(!q.allowed){ this.log({ nodeId:this.nodeId, agentId:opts.agentId, attempt:1, latency_ms:Date.now()-start, tokens_est:10, status:'blocked', errorClass:'QUOTA', extra:{ host:opts.hostId } }); return q; }
    }

    this.rate.record(opts.agentId, opts.hostId);
    this.log({ nodeId:this.nodeId, agentId:opts.agentId, attempt:1, latency_ms:Date.now()-start, tokens_est:18, status:'ok', errorClass:'none', extra:{ method:opts.method, hostId:opts.hostId } });
    return { allowed:true };
  }

  // Snapshot for thin UI — single daemon is source of truth
  snapshot(){
    return {
      mode:this.approval.getMode(),
      pendingApprovals:this.approval.pendingList().length,
      policies:this.policies.size,
      enabled:[...this.policies.values()].filter(p=>p.enabled).length,
      violations:this.violations.length,
      quotas:this.quota.status(),
      sessions:{ total:this.expiry.list().length, paused:this.expiry.paused().length, receipts:this.expiry.paused().slice(0,3).map(s=>s.receipt) },
      auth:{ valid:this.auth.isValid(this.auth.lastHash).valid, hoursSinceTouch:this.auth.hoursSinceTouch().toFixed(1), covers:this.auth.covers(), tagShort:this.auth.getTag().slice(0,8) },
      rate:this.rate.status(),
      ipc:this.ipc.getStatus(),
      inv:{
        thinUI:'single daemon owns PTY',
        peers:'same binary local&remote',
        hashWire:'auto-redeploy',
        tunnelWarm:'daemon outlives Electron',
        mux:'one WS covers all',
        noShell:'typed RPC only',
        guardrails:'first-class approval/quota/expiry/auth/rate/ipc',
        snapshotMs:`<${IpcGuard.SNAPSHOT_MAX_MS}ms`,
      },
      pillars:{
        lightweight:'thin UI + single daemon wrapper',
        reliable:'daemon keeps sessions warm snapshot+pause 48h resume days later receipts',
        parallel:'fbclone + multi-agent summarized',
      },
    };
  }

  // Yubi touch entry
  yubiTouch(tag:string,binaryHash:string){
    this.auth.touch(tag,binaryHash);
    this.log({ nodeId:this.nodeId, agentId:'guardrails-yubi', attempt:1, latency_ms:4, tokens_est:10, status:'ok', errorClass:'none', extra:{ action:'yubi_touch', tagShort:tag.slice(0,8), binaryHash:binaryHash.slice(0,12) } });
  }

  // For dashboard widget daily run
  sweepExpiry(now=Date.now()){
    const paused=this.expiry.sweep(now);
    for(const s of paused){
      this.log({ nodeId:this.nodeId, agentId:'guardrails-expiry', attempt:1, latency_ms:2, tokens_est:8, status:'ok', errorClass:'SESSION_EXPIRED', extra:{ sessionId:s.id, pausedAt:s.pausedAt, receipt:s.receipt } });
    }
    return paused;
  }
}

let _g: GuardrailRegistry | null = null;
export function getGuardrails(): GuardrailRegistry {
  if (!_g) _g = new GuardrailRegistry();
  return _g;
}

// Back-compat alias expected by prompt: Guardrails class name
export const Guardrails = GuardrailRegistry;

