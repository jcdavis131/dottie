/**
 * Feedback tool — first-class shared RPC
 * Blueprint screenshots as system base, now with guardrails + feedback loops
 * Zero-deps, typed RPC only, no shell exec, single daemon ownership
 *
 * Invariant extension: thin UI shows last 20, approval mode auto aggregates
 */

export type FeedbackRating = 1 | 2 | 3 | 4 | 5;

export type FeedbackEntry = {
  id: string; // feedback_<timestamp>_<rand>
  ts: number; // Date.now()
  ts_iso: string; // ISO for human scan
  agentId: string;
  host: string;
  rating: FeedbackRating;
  note: string; // 1-500 chars, plain-ENG
  tags: string[]; // e.g. ['blocker','latency','ux','compaction','stuck']
  confidence?: number; // 0-1 optional from caller
  latency_ms?: number;
  lane?: string;
  resolved?: boolean;
  source: 'rpc' | 'compaction' | 'stuck-detector' | 'sporadic' | 'guardrail';
};

export type FeedbackSubmitPayload = {
  agentId: string;
  host: string;
  rating: FeedbackRating;
  note: string;
  tags?: string[];
  confidence?: number;
  latency_ms?: number;
  lane?: string;
};

export type FeedbackAggregate = {
  count: number;
  avgRating: number; // 1-5
  lowCount: number; // rating <=2
  highCount: number; // rating >=4
  topTags: { tag: string; count: number }[];
  topHosts: { host: string; count: number; avg: number }[];
  topAgents: { agentId: string; count: number; avg: number }[];
  blockers: number; // tags.includes blocker/bug/failed
  needsReview: number;
  lastTs: number;
};

// In-memory store — daemon owns single instance
const MAX_STORE = 2000;
let memoryStore: FeedbackEntry[] = [];
let feedbackPathCache: string | null = null;

function genId(): string {
  return `feedback_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

function sanitizeEntry(p: FeedbackSubmitPayload): Omit<FeedbackEntry,'id'|'ts'|'ts_iso'|'source'|'resolved'> {
  if (!p.agentId || typeof p.agentId !== 'string') throw new Error('feedback.submit: agentId required string');
  if (!p.host || typeof p.host !== 'string') throw new Error('feedback.submit: host required string');
  const r = Number(p.rating);
  if (!(r >= 1 && r <= 5 && Number.isInteger(r))) throw new Error('feedback.submit: rating must be int 1-5');
  if (!p.note || typeof p.note !== 'string' || p.note.trim().length === 0) throw new Error('feedback.submit: note required');
  if (p.note.length > 2000) throw new Error('feedback.submit: note max 2000 chars');
  const tags = (p.tags ?? []).slice(0, 8).map(t => String(t).trim().toLowerCase()).filter(Boolean).slice(0, 8);
  // guardrails: no shell exec tags
  for (const t of tags) {
    if (t.includes('bash') || t.includes('`') || t.includes('$(')) throw new Error(`feedback tag forbidden ${t}`);
  }
  return {
    agentId: p.agentId.slice(0, 64),
    host: p.host.slice(0, 64),
    rating: r as FeedbackRating,
    note: p.note.slice(0, 500),
    tags,
    confidence: p.confidence != null ? Math.max(0, Math.min(1, Number(p.confidence))) : undefined,
    latency_ms: p.latency_ms != null ? Math.max(0, Number(p.latency_ms)) : undefined,
    lane: p.lane?.slice(0, 64),
  };
}

// Detect file persistence capability — Node fs if available, else no-op
async function tryAppendJsonl(entry: FeedbackEntry): Promise<void> {
  try {
    const g: any = globalThis as any;
    if (g?.process?.versions?.node) {
      const fs: any = await import('fs').catch(() => null);
      const pathMod: any = await import('path').catch(() => null);
      if (fs && pathMod) {
        const home = g.process.env?.HOME || g.process.env?.USERPROFILE || '';
        const candidates = [
          pathMod.join(home, '.scout/missions/feedback.jsonl'),
          pathMod.join(home, 'workspace/.scout/missions/feedback.jsonl'),
          pathMod.join(g.process.cwd?.() ?? '.', '.scout/missions/feedback.jsonl'),
          pathMod.join(g.process.cwd?.() ?? '.', 'workspace/.scout/missions/feedback.jsonl'),
          './.scout/missions/feedback.jsonl',
          './workspace/.scout/missions/feedback.jsonl',
        ];
        let target = feedbackPathCache;
        if (!target) {
          for (const cand of candidates) {
            try {
              const dir = pathMod.dirname(cand);
              if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
              target = cand;
              feedbackPathCache = cand;
              break;
            } catch {}
          }
        }
        if (target) {
          const dir = pathMod.dirname(target);
          try { if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true }); } catch {}
          fs.appendFileSync(target, JSON.stringify(entry) + '\n', { encoding: 'utf-8' });
          // also try workspace absolute
          try {
            const ws = pathMod.join(home, 'workspace/.scout/missions/feedback.jsonl');
            if (ws !== target) {
              const d2 = pathMod.dirname(ws);
              if (!fs.existsSync(d2)) fs.mkdirSync(d2, { recursive: true });
              fs.appendFileSync(ws, JSON.stringify(entry) + '\n');
            }
          } catch {}
        }
      }
    }
  } catch {
    // swallow — in-memory still valid, daemon warm
  }
}

export class FeedbackStore {
  private entries: FeedbackEntry[] = memoryStore;

  submit(payload: FeedbackSubmitPayload, source: FeedbackEntry['source'] = 'rpc'): FeedbackEntry {
    const clean = sanitizeEntry(payload);
    const now = Date.now();
    const e: FeedbackEntry = {
      id: genId(),
      ts: now,
      ts_iso: new Date(now).toISOString(),
      ...clean,
      source,
      resolved: false,
    };
    this.entries.unshift(e); // newest first — thin UI reads 0..19
    if (this.entries.length > MAX_STORE) this.entries.length = MAX_STORE;
    memoryStore = this.entries;
    // async persist — don't block snapshot <300ms
    void tryAppendJsonl(e);
    return e;
  }

  last20(): FeedbackEntry[] {
    return this.entries.slice(0, 20);
  }

  aggregate(lastN = 100): FeedbackAggregate {
    const slice = this.entries.slice(0, Math.min(lastN, this.entries.length));
    const count = slice.length;
    if (count === 0) return { count: 0, avgRating: 0, lowCount: 0, highCount: 0, topTags: [], topHosts: [], topAgents: [], blockers: 0, needsReview: 0, lastTs: 0 };
    const sum = slice.reduce((s, e) => s + e.rating, 0);
    const low = slice.filter(e => e.rating <= 2).length;
    const high = slice.filter(e => e.rating >= 4).length;
    const blockers = slice.filter(e => e.tags.some(t => ['blocker','bug','failed','stuck','error'].includes(t)) || e.rating <= 2).length;
    const tagMap = new Map<string, number>();
    const hostMap = new Map<string, { sum:number; count:number }>();
    const agentMap = new Map<string, { sum:number; count:number }>();
    for (const e of slice) {
      for (const t of e.tags) tagMap.set(t, (tagMap.get(t) ?? 0) + 1);
      const hm = hostMap.get(e.host) ?? { sum:0, count:0 }; hm.sum+=e.rating; hm.count++; hostMap.set(e.host, hm);
      const am = agentMap.get(e.agentId) ?? { sum:0, count:0 }; am.sum+=e.rating; am.count++; agentMap.set(e.agentId, am);
    }
    const topTags = [...tagMap.entries()].sort((a,b)=>b[1]-a[1]).slice(0, 6).map(([tag,c])=>({tag,count:c}));
    const topHosts = [...hostMap.entries()].sort((a,b)=>b[1].count-a[1].count).slice(0, 5).map(([host,v])=>({host,count:v.count,avg:+(v.sum/v.count).toFixed(2)}));
    const topAgents = [...agentMap.entries()].sort((a,b)=>b[1].count-a[1].count).slice(0, 5).map(([agentId,v])=>({agentId,count:v.count,avg:+(v.sum/v.count).toFixed(2)}));
    return {
      count,
      avgRating: +(sum / count).toFixed(2),
      lowCount: low,
      highCount: high,
      topTags,
      topHosts,
      topAgents,
      blockers,
      needsReview: blockers,
      lastTs: slice[0]?.ts ?? 0,
    };
  }

  snapshot() {
    const agg = this.aggregate(100);
    return {
      last20Count: Math.min(20, this.entries.length),
      totalCount: this.entries.length,
      avgRating: agg.avgRating,
      blockers: agg.blockers,
      needsReview: agg.needsReview,
      isThinUiReadable: true,
    };
  }

  extractBlockersFromNotes(): FeedbackEntry[] {
    return this.entries.filter(e => e.tags.some(t => ['blocker','bug','failed','stuck'].includes(t)) || e.rating <= 2).slice(0, 20);
  }
}

let _store: FeedbackStore | null = null;
export function getFeedbackStore(): FeedbackStore {
  if (!_store) _store = new FeedbackStore();
  return _store;
}

export function registerFeedbackRpc(dispatcher: any) {
  dispatcher.register('feedback.submit', async (p: FeedbackSubmitPayload & { source?: FeedbackEntry['source'] }) => {
    const store = getFeedbackStore();
    const e = store.submit(p, (p as any).source ?? 'rpc');
    return { ok: true, id: e.id, ts: e.ts };
  });
  dispatcher.register('feedback.list', async (p: { limit?: number }) => {
    const store = getFeedbackStore();
    const lim = Math.max(1, Math.min(50, Number(p?.limit ?? 20)));
    return { entries: store.last20().slice(0, lim), aggregate: store.aggregate(100) };
  });
  dispatcher.register('feedback.snapshot', async () => {
    const store = getFeedbackStore();
    return store.snapshot();
  });
}

export type FeedbackRpcMap = {
  'feedback.submit': FeedbackSubmitPayload;
  'feedback.list': { limit?: number };
  'feedback.snapshot': {};
};

export type FeedbackResponseMap = {
  'feedback.submit': { ok: true; id: string; ts: number };
  'feedback.list': { entries: FeedbackEntry[]; aggregate: FeedbackAggregate };
  'feedback.snapshot': ReturnType<FeedbackStore['snapshot']>;
};

// Backward compat shim for prior FeedbackHub shape
export type FeedbackSignal = {
  id: string;
  agentId?: string;
  taskId?: string;
  kind: 'thumbs_up'|'thumbs_down'|'correction'|'note'|'guardrail_hit';
  message: string;
  ts: number;
  strength: number;
  compacted?: boolean;
};
export class FeedbackHub {
  private store = getFeedbackStore();
  push(s: Omit<FeedbackSignal,'id'|'ts'> & Partial<Pick<FeedbackSignal,'id'|'ts'>>): FeedbackSignal {
    const rating = s.kind === 'thumbs_up' ? 5 : s.kind === 'thumbs_down' ? 1 : 3;
    const full: any = { id: s.id ?? `fb_${Date.now()}`, ts: s.ts ?? Date.now(), ...s, strength: s.strength ?? 0 };
    this.store.submit({ agentId: s.agentId ?? 'unknown', host: 'local', rating: rating as any, note: s.message, tags: [s.kind] }, 'rpc');
    return full as FeedbackSignal;
  }
  list(n=50){ return this.store.last20().slice(0,n).map(e=>({ id:e.id, agentId:e.agentId, kind: e.rating>=4?'thumbs_up': e.rating<=2?'thumbs_down':'note', message:e.note, ts:e.ts, strength: e.rating-3 } as FeedbackSignal)); }
  shouldCompact(messageCount:number){ return messageCount % 25 === 0 || Math.random() < 0.08; }
  compact(recent:string[]){ const tail=recent.slice(-3).join('\n'); return `COMPACT ${new Date().toISOString()} tail:${tail.slice(0,400)} fb:${this.store.snapshot().totalCount}`; }
  recentCompaction(){ return null; }
  triggerConfig(){ return { everyNMessages:25, maxTokens:8000, sporadicJitterMs:12000 }; }
  setTrigger(t:any){ Object.assign(this.triggerConfig(), t); }
  snapshot(){ const s=this.store.snapshot(); return { total:s.totalCount, negative:s.blockers, compactedEntries:0, trigger:this.triggerConfig() }; }
}
export function getFeedbackHub(){ const s=getFeedbackStore(); const hub=new FeedbackHub(); (hub as any).store=s; return hub; }
