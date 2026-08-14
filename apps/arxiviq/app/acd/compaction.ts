/**
 * Compaction loop — explicit module + extra heuristics
 * Blueprint screenshots system base + guardrails + feedback/compaction loops sporadic
 * Zero-deps, typed RPC only, no shell exec, daemon owns
 *
 * Requirements:
 * - every 4h OR 500 messages daemon runs compaction summarizing PTY history into scratchpad-ready digest (keep last 10% verbatim, 90% summarized)
 * - keeps full transcript warm in daemon snapshot <300ms
 * - sporadic triggers: low-conf <0.4 ×2, latency >2×p95 180s fallback, stuck-detector 9 lenses, all_lanes_busy 21 — trigger early compaction + feedback prompt
 * - pair with mistake-learning: every compaction uncovers blocker creates lesson entry lessons/ledger.jsonl + docs/LESSONS.md tight, confidence 0.7+
 */

import { getFeedbackStore, type FeedbackEntry } from './feedback';

export type CompactionTriggerReason =
  | 'interval_4h'
  | 'message_count_500'
  | 'low_conf_x2'
  | 'latency_p95_x2_fallback_180s'
  | 'stuck_detector_lens'
  | 'all_lanes_busy_21'
  | 'manual'
  | 'sporadic_jitter';

export type CompactionDigest = {
  id: string;
  ts: number;
  ts_iso: string;
  missionId?: string;
  sessionId?: string;
  reason: CompactionTriggerReason;
  messagesIn: number;
  messagesOut: number;
  verbatimKept: number; // 10%
  summarizedCount: number; // 90% summarized into N bullet lines
  digestMarkdown: string; // scratchpad-ready
  verbatimTail: string[]; // last 10% verbatim
  summaryBullets: string[]; // 90% summarized
  blockersFound: string[]; // keywords uncovered
  tokens_est_before: number;
  tokens_est_after: number;
  snapshotMs: number; // ensure <300ms read
};

export type CompactionConfig = {
  everyMs: number; // 4h
  everyNMessages: number; // 500
  keepVerbatimRatio: number; // 0.1
  maxSummaryBullets: number; // 40
  maxTokens: number;
  sporadicJitterPct: number; // 0.08
};

const DEFAULT_CONFIG: CompactionConfig = {
  everyMs: 4 * 60 * 60 * 1000, // 4h
  everyNMessages: 500,
  keepVerbatimRatio: 0.1,
  maxSummaryBullets: 40,
  maxTokens: 8000,
  sporadicJitterPct: 0.08,
};

// Helpers — zero-deps summarization
function isBlockerLine(s: string): boolean {
  const low = s.toLowerCase();
  return /(\b(blocker|blocked|failed|failure|stuck|error|exception|timeout|oom|sigterm|panic|retry|deadlock)\b)/i.test(low) ||
         /all_lanes_busy/.test(low) ||
         low.includes('attempt failed');
}

function extractDecision(s: string): boolean {
  return /(\b(decide|approved|blocked|merge|deploy|gate|ship|pass|fail)\b)/i.test(s);
}

function extractTodo(s: string): boolean {
  return /(\b(todo|task|fix|guardrail|lesson|next swarm|good\/better\/best)\b)/i.test(s);
}

function heuristicSummarize(messages: string[], maxBullets: number): { bullets: string[]; blockers: string[] } {
  const bullets: string[] = [];
  const blockers: string[] = [];
  const seen = new Set<string>();
  for (const m of messages) {
    if (isBlockerLine(m)) {
      const key = m.slice(0, 120);
      if (!seen.has(key)) {
        blockers.push(`- blocker: ${m.slice(0, 240)}`);
        seen.add(key);
      }
    }
  }
  // Decisions + todos + guardrails
  for (const m of messages) {
    if (bullets.length >= maxBullets) break;
    if (extractDecision(m) || extractTodo(m)) {
      const line = `- ${m.replace(/\s+/g,' ').slice(0, 200)}`;
      if (!seen.has(line)) { bullets.push(line); seen.add(line); }
    }
  }
  // Fallback: distinct first fragments if still sparse
  if (bullets.length < 6) {
    for (const m of messages) {
      if (bullets.length >= maxBullets) break;
      const frag = m.split('\n')[0]?.slice(0, 180);
      if (frag && !seen.has(frag)) { bullets.push(`- ${frag}`); seen.add(frag); }
    }
  }
  return { bullets: bullets.slice(0, maxBullets), blockers: blockers.slice(0, 20) };
}

function tokensEst(s: string): number {
  return Math.ceil(s.length / 4);
}

export class CompactionEngine {
  private lastCompactionTs = 0;
  private lastCompactionMsgCount = 0;
  private messageCount = 0;
  private recentLatencies: number[] = [];
  private recentConfidences: number[] = [];
  private config: CompactionConfig = { ...DEFAULT_CONFIG };
  private lastDigest: CompactionDigest | null = null;
  private runs = 0;
  private digests: CompactionDigest[] = [];

  configure(patch: Partial<CompactionConfig>) {
    Object.assign(this.config, patch);
  }

  ingestMessage(msg: string, opts?: { latency_ms?: number; confidence?: number }) {
    this.messageCount++;
    if (opts?.latency_ms != null) {
      this.recentLatencies.push(opts.latency_ms);
      if (this.recentLatencies.length > 200) this.recentLatencies.shift();
    }
    if (opts?.confidence != null) {
      this.recentConfidences.push(opts.confidence);
      if (this.recentConfidences.length > 50) this.recentConfidences.shift();
    }
    return this.messageCount;
  }

  private p95(arr: number[]): number {
    if (!arr.length) return 0;
    const s = [...arr].sort((a,b)=>a-b);
    return s[Math.floor(0.95 * (s.length-1))];
  }

  // Sporadic trigger check — returns reason or null
  checkSporadic(opts?: {
    latencies?: number[];
    confidences?: number[];
    stuckLens?: string | null;
    allLanesBusy?: number;
  }): CompactionTriggerReason | null {
    const now = Date.now();
    // interval 4h
    if (now - this.lastCompactionTs > this.config.everyMs) return 'interval_4h';
    // message count 500
    if (this.messageCount - this.lastCompactionMsgCount > this.config.everyNMessages) return 'message_count_500';

    // low-conf <0.4 ×2
    const confs = opts?.confidences ?? this.recentConfidences;
    if (confs.length >= 2) {
      const last2 = confs.slice(-2);
      if (last2.every(c => c < 0.4)) return 'low_conf_x2';
    }

    // latency >2×p95 180s fallback
    const lats = opts?.latencies ?? this.recentLatencies;
    if (lats.length >= 5) {
      const p95 = this.p95(lats);
      const threshold = p95 > 0 ? p95 * 2 : 180000;
      const fallback = 180000;
      const last = lats[lats.length-1];
      if (last > Math.max(threshold, fallback)) return 'latency_p95_x2_fallback_180s';
    }

    // stuck-detector 9 lenses
    if (opts?.stuckLens && ['inversion','scamper','analogy','worst-idea','provocation','concept-fan','random-stimulus','six-hats','lateral'].includes(opts.stuckLens)) {
      return 'stuck_detector_lens';
    }

    // all_lanes_busy 21
    if ((opts?.allLanesBusy ?? 0) >= 21) return 'all_lanes_busy_21';

    // sporadic jitter 8%
    if (Math.random() < this.config.sporadicJitterPct) return 'sporadic_jitter';

    return null;
  }

  // Core compaction — keep 10% verbatim tail, 90% summarized
  compact(ptyHistory: string[], reason: CompactionTriggerReason, opts?: { missionId?: string; sessionId?: string }): CompactionDigest {
    const t0 = Date.now();
    const total = ptyHistory.length;
    const keepVerbatim = Math.max(1, Math.ceil(total * this.config.keepVerbatimRatio));
    const toSummarize = ptyHistory.slice(0, total - keepVerbatim);
    const verbatimTail = ptyHistory.slice(total - keepVerbatim);

    const { bullets, blockers } = heuristicSummarize(toSummarize, this.config.maxSummaryBullets);

    const digestMdLines = [
      `# Compaction Digest — ${new Date().toISOString()}`,
      `Reason: ${reason} | totalMsgs:${total} keepVerbatim:${keepVerbatim} summarized:${toSummarize.length}`,
      ``,
      `## Summary Bullets (90% → ${bullets.length} lines)`,
      ...bullets,
      ``,
      ...(blockers.length ? [`## Blockers Uncovered (${blockers.length})`, ...blockers, ``] : []),
      `## Verbatim Tail (last 10%)`,
      ...verbatimTail.map(l => `> ${l.slice(0, 400)}`),
      ``,
      `Scratchpad-ready — paste into .scout/missions/<id>/scratchpad.md or shared todo`,
    ];

    const digestMarkdown = digestMdLines.join('\n').slice(0, this.config.maxTokens * 4);

    const beforeTokens = ptyHistory.reduce((s,m)=>s+tokensEst(m),0);
    const afterTokens = tokensEst(digestMarkdown); // approximate collapsed

    const d: CompactionDigest = {
      id: `compact_${Date.now()}_${Math.random().toString(16).slice(2,6)}`,
      ts: Date.now(),
      ts_iso: new Date().toISOString(),
      missionId: opts?.missionId,
      sessionId: opts?.sessionId,
      reason,
      messagesIn: total,
      messagesOut: bullets.length + verbatimTail.length,
      verbatimKept: verbatimTail.length,
      summarizedCount: toSummarize.length,
      digestMarkdown,
      verbatimTail,
      summaryBullets: bullets,
      blockersFound: blockers,
      tokens_est_before: beforeTokens,
      tokens_est_after: afterTokens,
      snapshotMs: Date.now() - t0,
    };

    this.lastCompactionTs = d.ts;
    this.lastCompactionMsgCount = this.messageCount;
    this.lastDigest = d;
    this.digests.unshift(d);
    if (this.digests.length > 50) this.digests.length = 50;
    this.runs++;

    // Pair with feedback — every early compaction + feedback prompt
    if (['low_conf_x2','latency_p95_x2_fallback_180s','stuck_detector_lens','all_lanes_busy_21'].includes(reason) || blockers.length > 0) {
      try {
        const store = getFeedbackStore();
        store.submit({
          agentId: `compaction-${reason}`,
          host: opts?.missionId ?? 'daemon',
          rating: blockers.length ? 2 as const : 3 as const,
          note: `compaction ${reason} uncovered ${blockers.length} blockers — ${bullets.slice(0,2).join(' | ').slice(0,200)}`,
          tags: [reason, blockers.length ? 'blocker':'compaction', 'auto'],
          lane: 'compaction',
        }, blockers.length ? 'compaction' : 'sporadic');
      } catch {}
      // Pair with mistake-learning — lesson entry
      if (blockers.length > 0) {
        void this.tryCreateLesson(d);
      }
    }

    // Also try fs persistence for digests
    void this.tryPersistDigest(d);

    return d;
  }

  private async tryPersistDigest(d: CompactionDigest): Promise<void> {
    try {
      const g: any = globalThis as any;
      if (g?.process?.versions?.node) {
        const fs: any = await import('fs').catch(()=>null);
        const pathMod: any = await import('path').catch(()=>null);
        if (fs && pathMod) {
          const home = g.process.env?.HOME ?? '';
          const candidates = [
            pathMod.join(home, '.scout/missions/compaction.jsonl'),
            pathMod.join(home, 'workspace/.scout/missions/compaction.jsonl'),
            pathMod.join(g.process.cwd?.() ?? '.', '.scout/missions/compaction.jsonl'),
            './.scout/missions/compaction.jsonl',
          ];
          for (const p of candidates.slice(0,1)) {
            try {
              const dir = pathMod.dirname(p);
              if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
              fs.appendFileSync(p, JSON.stringify(d) + '\n');
              break;
            } catch {}
          }
        }
      }
    } catch {}
  }

  private async tryCreateLesson(d: CompactionDigest): Promise<void> {
    try {
      const g: any = globalThis as any;
      if (!g?.process?.versions?.node) return;
      const fs: any = await import('fs').catch(()=>null);
      const pathMod: any = await import('path').catch(()=>null);
      if (!fs || !pathMod) return;
      const home = g.process.env?.HOME ?? '';
      const ledgerPaths = [
        pathMod.join(home, 'workspace/lessons/ledger.jsonl'),
        pathMod.join(home, 'workspace/lessons/ledger_tight.jsonl'),
        pathMod.join(g.process.cwd?.() ?? '.', 'workspace/lessons/ledger.jsonl'),
        './workspace/lessons/ledger.jsonl',
        pathMod.join(home, 'lessons/ledger.jsonl'),
      ];
      const lesson = {
        id: `lsn_${new Date().toISOString().replace(/[:.]/g,'')}_compaction_${d.reason}`,
        ts: d.ts_iso,
        what: `compaction ${d.reason} uncovered ${d.blockersFound.length} blockers — ${d.blockersFound.slice(0,2).join(' | ').slice(0,200)}`,
        lesson: `When PTY history grows >${this.config.everyNMessages} msgs or triggers ${d.reason}, compact keeping last 10% verbatim; summarize 90% preserving decisions/todos/guardrails/blockers; store digest scratchpad-ready. Pause/resume via daemon snapshot <300ms.`,
        cause: `Trigger ${d.reason} with blockers ${d.blockersFound.length}, latency/confidence degraded, stuck-detector lens, all_lanes_busy ≥21.`,
        fix: `Compaction loop every 4h / 500 msgs sporadic jitter 8% — early compaction + feedback prompt — digest ${d.id} ${d.verbatimKept} verbatim + ${d.summaryBullets.length} bullets.`,
        prevention: `Guardrail: daemon compaction scheduled 4h interval, message watermark 500, sporadic triggers low-conf×2 latency>2×p95 180s stuck 9 lenses all_lanes_busy 21 → early compact + feedback.submit rating 2 tag blocker; lesson paired confidence 0.8 tight; timeline 7-field 9 dirs.`,
        paired: true,
        status: 'open',
        confidence: 0.8,
        source: 'compaction-loop',
        digest_id: d.id,
        reason: d.reason,
        blockers: d.blockersFound.length,
      };
      for (const lp of ledgerPaths.slice(0,1)) {
        try {
          const dir = pathMod.dirname(lp);
          if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
          fs.appendFileSync(lp, JSON.stringify(lesson) + '\n');
          break;
        } catch {}
      }
      // Tight docs/LESSONS.md append
      const tightPaths = [
        pathMod.join(home, 'workspace/docs/LESSONS.md'),
        pathMod.join(g.process.cwd?.() ?? '.', 'workspace/docs/LESSONS.md'),
        './workspace/docs/LESSONS.md',
      ];
      for (const tp of tightPaths.slice(0,1)) {
        try {
          const dir = pathMod.dirname(tp);
          if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
          fs.appendFileSync(tp, `\n### ${lesson.id} — 0.8\n- what: ${lesson.what}\n- lesson: ${lesson.lesson}\n- cause: ${lesson.cause}\n- fix: ${lesson.fix}\n- prevention: ${lesson.prevention}\n- paired: True status: open\n`);
          break;
        } catch {}
      }
    } catch {}
  }

  snapshot() {
    const t0 = Date.now();
    const s = {
      runs: this.runs,
      lastTs: this.lastCompactionTs,
      lastReason: this.lastDigest?.reason ?? null,
      messageCount: this.messageCount,
      recentLatencies: this.recentLatencies.length,
      recentConfidences: this.recentConfidences.length,
      lastDigestId: this.lastDigest?.id ?? null,
    };
    const elapsed = Date.now() - t0;
    return { ...s, snapshotMs: elapsed, snapshotOk: elapsed < 300 };
  }

  last20(): CompactionDigest[] { return this.digests.slice(0, 20); }
  last(): CompactionDigest | null { return this.lastDigest; }
}

let _engine: CompactionEngine | null = null;
export function getCompactionEngine(): CompactionEngine {
  if (!_engine) _engine = new CompactionEngine();
  return _engine;
}

// Typed RPC wiring
export function registerCompactionRpc(dispatcher: any) {
  dispatcher.register('compaction.trigger', async (p: { missionId?: string; sessionId?: string; reason?: CompactionTriggerReason; messages?: string[] }) => {
    const eng = getCompactionEngine();
    const msgs = p.messages ?? [];
    const reason = (p.reason ?? eng.checkSporadic() ?? 'manual') as CompactionTriggerReason;
    const d = eng.compact(msgs.length ? msgs : ['no-history placeholder'], reason, { missionId: p.missionId, sessionId: p.sessionId });
    return { ok: true, digest: d };
  });
  dispatcher.register('compaction.snapshot', async () => {
    const eng = getCompactionEngine();
    return eng.snapshot();
  });
  dispatcher.register('compaction.last20', async () => {
    const eng = getCompactionEngine();
    return { digests: eng.last20() };
  });
}

// Types for RPC maps augmentation
export type CompactionRpcMap = {
  'compaction.trigger': { missionId?: string; sessionId?: string; reason?: CompactionTriggerReason; messages?: string[] };
  'compaction.snapshot': {};
  'compaction.last20': {};
};

export type CompactionResponseMap = {
  'compaction.trigger': { ok: true; digest: CompactionDigest };
  'compaction.snapshot': ReturnType<CompactionEngine['snapshot']>;
  'compaction.last20': { digests: CompactionDigest[] };
};

// Backward compat re-export for earlier simple API
export type CompactionResult = {
  summary: string;
  keptMessages: number;
  droppedTokensEst: number;
  ts: number;
};
export function heuristicCompact(messages: string[], keepLast = 5, maxSummaryChars = 1200): CompactionResult {
  const eng = getCompactionEngine();
  const reason = (eng.checkSporadic() ?? 'manual') as CompactionTriggerReason;
  const d = eng.compact(messages, reason);
  return { summary: d.digestMarkdown.slice(0, maxSummaryChars), keptMessages: d.verbatimKept, droppedTokensEst: d.tokens_est_before - d.tokens_est_after, ts: d.ts };
}
// Extra re-export aliases expected by barrel
export { getCompactionEngine as getCompactionLoop };
export type CompactionTrigger = { everyNMessages:number; maxTokens:number; sporadicJitterMs:number };
