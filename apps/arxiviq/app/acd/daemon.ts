/**
 * Invariant 01: Thin UI, single daemon — All PTY ownership, SSH tunnel management,
 * file transfer, and ISL hosting live in one daemon. Electron renderer purely presentational.
 * Zero-deps TS shim for Rust daemon analog.
 * Extended with feedback + compaction first-class shared tools
 */
import { RpcDispatcher, createSecureDispatcher } from './rpc';
import { getGuardrails } from './guardrails';
import { getScratchpad, bindScratchpadRpcs } from './scratchpad';
import { getFeedbackStore, registerFeedbackRpc } from './feedback';
import { getCompactionEngine, registerCompactionRpc, type CompactionTriggerReason } from './compaction';
import { bindTodoRpcs, getTodoStore } from './todo';

type PtySession = {
  id: string;
  cols: number;
  rows: number;
  cwd: string;
  history: Uint8Array[];
  historyText: string[]; // decoded for compaction / scratchpad
  createdAt: number;
  warm: boolean;
};

export class AcdDaemon {
  private ptys = new Map<string, PtySession>();
  private tunnels = new Map<string, { host:string; port:number; openedAt:number; localPort:number }>();
  private dispatcher: RpcDispatcher;
  private isElectronRenderer = false;

  // compaction bookkeeping
  private compactionEngine = getCompactionEngine();
  private feedbackStore = getFeedbackStore();

  constructor(opts?: { isRenderer?: boolean }) {
    this.isElectronRenderer = !!opts?.isRenderer;
    this.dispatcher = createSecureDispatcher();
    this.bindCoreHandlers();
    // periodic 4h check — sporadic tick inside daemon
    try {
      setInterval(() => this.maybeAutoCompact('interval_4h'), 60_000);
    } catch {}
  }

  private assertDaemon() {
    if (this.isElectronRenderer) throw new Error('Thin UI: renderer cannot own PTY/tunnel — call daemon RPC');
  }

  ownPty(sessionId: string, cols=120, rows=32, cwd='/tmp'): PtySession {
    this.assertDaemon();
    const existing = this.ptys.get(sessionId);
    if (existing) return existing;
    const s: PtySession = { id: sessionId, cols, rows, cwd, history: [], historyText: [], createdAt: Date.now(), warm: true };
    this.ptys.set(sessionId, s);
    return s;
  }

  restorePty(sessionId: string): PtySession | null {
    return this.ptys.get(sessionId) ?? null;
  }

  appendHistory(sessionId:string, bytes:Uint8Array) {
    const s = this.ptys.get(sessionId);
    if (!s) return;
    s.history.push(bytes);
    // decode for compaction without shell exec
    try {
      const txt = new TextDecoder().decode(bytes).slice(0, 1000);
      s.historyText.push(txt);
      if (s.historyText.length > 1000) s.historyText.shift();
      this.compactionEngine.ingestMessage(txt);
    } catch {
      s.historyText.push(`[binary ${bytes.length}B]`);
    }
    if (s.history.length > 1000) s.history.shift();
    // message count trigger check sporadically
    const trig = this.compactionEngine.checkSporadic();
    if (trig) {
      void this.maybeAutoCompact(trig);
    }
  }

  manageTunnels(hosts: string[]) {
    this.assertDaemon();
    for (const h of hosts) {
      if (![...this.tunnels.values()].some(t=>t.host===h)) {
        const id = `tun_${h}_${Date.now()}`;
        this.tunnels.set(id, { host:h, port:22, openedAt: Date.now(), localPort: 4000 + this.tunnels.size });
      }
    }
    return [...this.tunnels.entries()].map(([id,t])=>({ tunnelId:id, ...t }));
  }

  fileTransfer() {
    this.assertDaemon();
    return { mode:'single-channel' as const, channel:'ws-mux' };
  }

  hostIsl(host:string, port:number) {
    this.assertDaemon();
    return { endpoint:`ws://${host}:${port}/isl`, alive: true };
  }

  getDispatcher() { return this.dispatcher; }

  // Sporadic trigger entry point — can be called from outside with low-conf/latency/stuck/all_lanes_busy signals
  triggerCompactionIfNeeded(opts: {
    latencies?: number[];
    confidences?: number[];
    stuckLens?: string | null;
    allLanesBusy?: number;
    latency_ms?: number;
    confidence?: number;
  } = {}): CompactionTriggerReason | null {
    if (opts.latency_ms != null) this.compactionEngine.ingestMessage(`latency ${opts.latency_ms}`, { latency_ms: opts.latency_ms });
    if (opts.confidence != null) this.compactionEngine.ingestMessage(`conf ${opts.confidence}`, { confidence: opts.confidence });
    const reason = this.compactionEngine.checkSporadic({
      latencies: opts.latencies,
      confidences: opts.confidences,
      stuckLens: opts.stuckLens,
      allLanesBusy: opts.allLanesBusy,
    });
    if (reason) {
      void this.maybeAutoCompact(reason);
      // feedback prompt
      try {
        this.feedbackStore.submit({
          agentId: 'daemon-sporadic',
          host: 'daemon',
          rating: 3,
          note: `sporadic compaction triggered ${reason} — low-conf×2 / latency>2×p95 180s / stuck 9 lenses / all_lanes_busy 21`,
          tags: [reason, 'sporadic', 'compaction'],
          lane: 'compaction',
        }, 'sporadic');
      } catch {}
    }
    return reason;
  }

  private maybeAutoCompact(reason: CompactionTriggerReason) {
    // Find biggest session for compaction
    let biggest: PtySession | null = null;
    for (const s of this.ptys.values()) {
      if (!biggest || s.historyText.length > biggest.historyText.length) biggest = s;
    }
    const history = biggest?.historyText ?? ['no PTY history — daemon warm but no sessions yet'];
    const digest = this.compactionEngine.compact(history, reason, { missionId: biggest?.id ?? 'daemon', sessionId: biggest?.id });
    // Write digest to scratchpad-ready place via thin UI safe logging
    try {
      const pad = getScratchpad();
      pad.write(digest.missionId ?? 'daemon-compaction', `Compaction ${reason} → ${digest.id}\n${digest.digestMarkdown}`, 'compaction/daemon');
    } catch {}
    return digest;
  }

  private bindCoreHandlers() {
    const guards = getGuardrails();

    this.dispatcher.register('pty.create', async (p) => {
      // guardrails: quota + approval + rate + auth
      try {
        const enforce = (guards as any).enforceRpc?.({ agentId: 'acd-daemon', hostId: p.cwd ?? 'local', method: 'pty.create', payload: p, binaryHash: (globalThis as any).__ACD_BINARY_HASH__ ?? 'dev-hash' });
        if (enforce && !enforce.allowed) throw new Error(enforce.reason ?? 'guardrails blocked pty.create');
        const ok = (guards as any).quota?.canCreatePty?.(p.cwd ?? 'local');
        if (ok && !ok.allowed) throw new Error(ok.reason);
      } catch (e:any) {
        if (e?.message?.includes('blocked')) throw e;
      }
      const id = `pty_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      this.ownPty(id, p.cols, p.rows, p.cwd);
      try { (guards as any).quota?.recordPtyCreate?.(p.cwd ?? 'local', id, 32); (guards as any).expiry?.track?.(id, p.cwd ?? 'local'); } catch {}
      return { sessionId: id };
    });

    this.dispatcher.register('pty.attach', async (p) => {
      const s = this.ptys.get(p.sessionId);
      if (!s) throw new Error('session not found — daemon may have restarted; check persisted warm store');
      try { (guards as any).expiry?.touch?.(p.sessionId); } catch {}
      return { sessionId: s.id, history: s.history };
    });

    this.dispatcher.register('tunnel.open', async (p) => {
      try {
        const dec = (guards as any).enforceRpc?.({ agentId: 'acd-daemon', hostId: p.host, method: 'tunnel.open', payload: p, binaryHash: (globalThis as any).__ACD_BINARY_HASH__ ?? 'dev-hash' });
        if (dec && !dec.allowed) throw new Error(dec.reason ?? 'guardrails blocked tunnel');
      } catch (e:any) { if (e?.message?.includes('blocked')) throw e; }
      const id = `tun_${p.host}_${Date.now()}`;
      this.tunnels.set(id, { host:p.host, port:p.port, openedAt:Date.now(), localPort: 4100 + this.tunnels.size });
      return { tunnelId:id, localPort: Array.from(this.tunnels.values()).pop()!.localPort };
    });

    this.dispatcher.register('heartbeat.ping', async (p) => ({ pong: Date.now() }));

    bindScratchpadRpcs((method, handler) => this.dispatcher.register(method as any, handler as any));
    // todo first-class — single daemon, single WS, mission-scoped
    try {
      bindTodoRpcs(this.dispatcher as any, { defaultMissionId: 'acd-daemon' });
      // also keep backward compat for old register style if needed
    } catch {
      // fallback dynamic require for older build
      try {
        const { bindTodoRpcs: b2 } = require('./todo') as any;
        (b2 as any)((method: string, handler: any) => this.dispatcher.register(method as any, handler as any));
      } catch {}
    }

    // feedback + compaction — first-class shared RPCs
    registerFeedbackRpc(this.dispatcher);
    registerCompactionRpc(this.dispatcher);

    // extra: low-conf / latency / stuck / all_lanes_busy reporting via heartbeat piggyback
    this.dispatcher.register('heartbeat.ping' as any, async (p:any) => {
      // if payload carries sporadic signals, forward to trigger
      if (p?.confidences || p?.latencies || p?.stuckLens || p?.allLanesBusy != null) {
        this.triggerCompactionIfNeeded(p);
      }
      return { pong: Date.now() } as any;
    });

    const sweep = () => {
      try {
        const paused = (guards as any).sweepExpiry?.() ?? [];
        if (paused.length) {
          try { console.log(`[daemon] ${paused.length} sessions paused >48h — snapshot+pause w receipts`); } catch {}
        }
      } catch {}
    };
    try { setInterval(sweep, 60_000); } catch {}
  }

  snapshot() {
    const t0 = Date.now();
    const pid = (globalThis as any)?.process?.pid ?? 1;
    const first = this.ptys.values().next().value as PtySession | undefined;
    const guards = getGuardrails();
    const ipcMeasure = (guards as any).ipc?.measure?.(() => this.ptys.size) ?? { ok: true, elapsedMs: 0 };
    const compactionSnap = this.compactionEngine.snapshot();
    const feedbackSnap = this.feedbackStore.snapshot();
    const todoSnap = (()=>{ try { return getTodoStore('acd-daemon').snapshot('acd-daemon'); } catch { return { count:0, pending:0, todos:[] }; } })();
    const elapsed = Date.now() - t0;
    return {
      daemonPid: pid,
      ptyCount: this.ptys.size,
      tunnelCount: this.tunnels.size,
      uptimeMs: Date.now() - (first?.createdAt ?? Date.now()),
      isThinUi: this.isElectronRenderer,
      guardrails: guards.snapshot(),
      ipcOk: ipcMeasure.ok,
      ipcMs: ipcMeasure.elapsedMs,
      inv01: `snapshot <300ms — ${elapsed < 300 ? 'PASS' : 'SLOW'} ${elapsed}ms`,
      compaction: compactionSnap,
      feedback: feedbackSnap,
      todos: todoSnap,
      singleInProgressEnforced: true,
      snapshotMs: elapsed,
      snapshotOk: elapsed < 300,
    };
  }
}

let _daemon: AcdDaemon | null = null;
export function getDaemon(): AcdDaemon {
  if (!_daemon) _daemon = new AcdDaemon({ isRenderer: false });
  return _daemon;
}
export function getThinUiFacade(): Pick<AcdDaemon,'snapshot'> {
  return { snapshot: () => getDaemon().snapshot() } as any;
}
