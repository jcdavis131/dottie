/**
 * Scratchpad — first-class shared tool
 * Shared scratchpad per mission: .scout/missions/<id>/scratchpad.md
 * First-class over single WS multiplex file|isl|pty|rpc
 * Zero-deps, daemon owns file, thin UI purely presentational.
 * 
 * Invariants:
 * - 01 Thin UI single daemon wrapper: daemon.ts owns, snapshot <300ms
 * - 04 Tunnel survives restarts: sync via warm true reattach no re-auth
 * - 05 One channel many streams: Yubi once covers scratchpad RPCs
 * - 06 No shell exec: typed RPCs only, file.read via RPC not bash -c
 * - fbclone same OD sees same scratchpad (missionId scoped)
 */

export type ScratchpadEntry = {
  ts: number;            // ms epoch
  author: string;        // agentId | 'user' | 'pty:sessionId'
  text: string;          // one breadcrumb / block
};

export type ScratchpadFile = {
  missionId: string;
  path: string;          // canonical .scout/missions/<id>/scratchpad.md
  entries: ScratchpadEntry[];
  lastWriteTs: number;
  lastAuthor: string;
  rawSize: number;
};

// in-memory canonical stores — daemon owns
// missionId → file model. Persists via inMemory for TS shim;
// Rust daemon analog fs persistence mirrors same path.
const memStore = new Map<string, ScratchpadFile>();
const lwwMeta = new Map<string, { ts:number; author:string }>();

function canonicalPath(missionId: string): string {
  // zero-deps path safe — no .. traversal
  const safe = missionId.replace(/[^a-zA-Z0-9._-]/g, '_').slice(0, 128) || '_';
  return `.scout/missions/${safe}/scratchpad.md`;
}

function nowMs(): number { return Date.now(); }

function fmtEntry(e: ScratchpadEntry): string {
  const iso = new Date(e.ts).toISOString();
  const author = e.author || 'unknown';
  // markdown-ish line — human editable
  return `- [${iso}] ${author}: ${e.text}`;
}

function parseFile(entries: ScratchpadEntry[]): string {
  if (entries.length === 0) return '# Scratchpad\n\n_Agents can leave breadcrumbs here. User can edit inline. Auto-saves on pty exit._\n\n';
  const header = '# Scratchpad\n\n';
  return header + entries.map(fmtEntry).join('\n') + '\n';
}

export class ScratchpadStore {
  // Daemon-only assert shim — matches daemon.ts
  private isDaemon = true;

  constructor(opts?: { isDaemon?: boolean }) {
    if (opts?.isDaemon === false) this.isDaemon = false;
  }

  private assertDaemon() {
    if (!this.isDaemon) throw new Error('Thin UI: renderer cannot own scratchpad file — use RPC snapshot');
  }

  ensure(missionId: string): ScratchpadFile {
    const path = canonicalPath(missionId);
    let f = memStore.get(missionId);
    if (!f) {
      f = {
        missionId,
        path,
        entries: [],
        lastWriteTs: nowMs(),
        lastAuthor: 'init',
        rawSize: 0,
      };
      memStore.set(missionId, f);
      lwwMeta.set(missionId, { ts: f.lastWriteTs, author: 'init' });
    }
    return f;
  }

  // LWW with conflict preservation — "shows both"
  write(missionId: string, text: string, author = 'agent'): ScratchpadFile {
    this.assertDaemon();
    const f = this.ensure(missionId);
    const ts = nowMs();
    const last = lwwMeta.get(missionId);
    const incoming: ScratchpadEntry = { ts, author, text: text.slice(0, 8192) };

    // Conflict window 2000ms — keep both with marker, LWW still advances
    if (last && Math.abs(ts - last.ts) < 2000 && last.author !== author) {
      const conflictMarker = `<<<<CONFLICT ts=${ts} last=${last.ts} authors=${last.author}|${author}>>>>`;
      f.entries.push({ ts: ts-1, author: 'system/conflict', text: conflictMarker });
      f.entries.push(incoming);
      // keep tail — capability to truncate later via compact
    } else {
      f.entries.push(incoming);
    }

    f.lastWriteTs = ts;
    f.lastAuthor = author;
    f.rawSize = f.entries.reduce((n,e)=>n+e.text.length,0);
    lwwMeta.set(missionId, { ts, author });
    memStore.set(missionId, f);
    return f;
  }

  read(missionId: string, offset = 0, limit = 100): { entries: ScratchpadEntry[]; total: number; path: string } {
    const f = this.ensure(missionId);
    const total = f.entries.length;
    const slice = f.entries.slice(offset, offset+limit);
    return { entries: slice, total, path: f.path };
  }

  // full markdown rendering (for file.read RPC path — PTY can cat same file via file.read, no shell)
  readMarkdown(missionId: string): string {
    const f = this.ensure(missionId);
    return parseFile(f.entries);
  }

  compact(missionId: string, keep_last_n = 50): ScratchpadFile {
    this.assertDaemon();
    const f = this.ensure(missionId);
    if (f.entries.length <= keep_last_n) return f;
    const kept = f.entries.slice(-keep_last_n);
    // breadcrumb about compaction
    kept.unshift({ ts: nowMs(), author: 'system/compact', text: `[compacted ${f.entries.length - keep_last_n} older entries → kept last ${keep_last_n}]` });
    f.entries = kept;
    f.lastWriteTs = nowMs();
    memStore.set(missionId, f);
    return f;
  }

  // Snapshot for thin UI — <300ms read-only
  snapshot(missionId: string): { missionId:string; path:string; count:number; lastWriteTs:number; lastAuthor:string; preview: ScratchpadEntry[] } {
    const f = this.ensure(missionId);
    const t0 = nowMs();
    // thin UI purely presentational — no mutation, must be fast
    const snap = {
      missionId: f.missionId,
      path: f.path,
      count: f.entries.length,
      lastWriteTs: f.lastWriteTs,
      lastAuthor: f.lastAuthor,
      preview: f.entries.slice(-5),
    };
    const elapsed = nowMs() - t0;
    // soft assert <300ms — in shim always true (<1ms)
    if (elapsed > 300) {
      // log but don't throw in prod — thin UI degrade
      // console.warn(`scratchpad snapshot ${elapsed}ms exceeds 300ms`);
    }
    return snap;
  }

  // Sync via tunnel warm true reattach no re-auth — called on TunnelStore.reattach()
  syncFromRemote(missionId: string, remote: ScratchpadFile): ScratchpadFile {
    this.assertDaemon();
    const local = this.ensure(missionId);
    // last-write-wins with ts, but merge preserving both on close timestamps
    if (!remote.lastWriteTs) return local;
    if (remote.lastWriteTs > local.lastWriteTs + 2000) {
      // remote strictly newer — win
      memStore.set(missionId, remote);
      lwwMeta.set(missionId, { ts: remote.lastWriteTs, author: remote.lastAuthor });
      return remote;
    }
    if (Math.abs(remote.lastWriteTs - local.lastWriteTs) <= 2000 && remote.lastAuthor !== local.lastAuthor) {
      // concurrent edit — keep both logs, mark conflict
      const merged: ScratchpadFile = {
        missionId,
        path: local.path,
        entries: [...local.entries, { ts: nowMs(), author: 'system/conflict-merge', text: `<<<<MERGE remote=${remote.lastAuthor}@${remote.lastWriteTs} local=${local.lastAuthor}@${local.lastWriteTs}>>>>` }, ...remote.entries.slice(-10)],
        lastWriteTs: Math.max(local.lastWriteTs, remote.lastWriteTs),
        lastAuthor: remote.lastWriteTs >= local.lastWriteTs ? remote.lastAuthor : local.lastAuthor,
        rawSize: 0,
      };
      merged.rawSize = merged.entries.reduce((n,e)=>n+e.text.length,0);
      memStore.set(missionId, merged);
      lwwMeta.set(missionId, { ts: merged.lastWriteTs, author: merged.lastAuthor });
      return merged;
    }
    // local wins
    return local;
  }

  // Auto-save on pty exit — breadcrumb hook
  onPtyExit(missionId: string, sessionId: string, exitCode?: number) {
    this.assertDaemon();
    return this.write(missionId, `pty ${sessionId} exited${exitCode !== undefined ? ` code=${exitCode}` : ''} — auto-saved`, `pty:${sessionId}`);
  }

  // fbclone same OD sees same scratchpad — OD is mission-scoped
  // no extra handling: same missionId map entry ensures fbclone reads identical backing
}

// singleton — daemon owns single wrapper, matching daemon.ts pattern
let _scratchpad: ScratchpadStore | null = null;
export function getScratchpad(): ScratchpadStore {
  if (!_scratchpad) _scratchpad = new ScratchpadStore({ isDaemon: true });
  return _scratchpad;
}
export function getThinUiScratchpadFacade() {
  // read-only preview only — mirrors thin UI facade pattern
  const s = getScratchpad();
  return {
    snapshot: (missionId:string) => s.snapshot(missionId),
    readMarkdown: (missionId:string) => s.readMarkdown(missionId),
  };
}

// RPC method types — zero-deps TS, extend RpcMethod union elsewhere via augmentation.
// For now expose const list for rpc.ts patching.
export const SCRATCHPAD_METHODS = ['scratchpad.read','scratchpad.write','scratchpad.compact'] as const;
export type ScratchpadMethod = typeof SCRATCHPAD_METHODS[number];

export type ScratchpadRpcPayloads = {
  'scratchpad.read': { missionId:string; offset?:number; limit?:number };
  'scratchpad.write': { missionId:string; append:boolean; text:string; author?:string };
  'scratchpad.compact': { missionId:string; keep_last_n?:number };
};

export type ScratchpadRpcResponses = {
  'scratchpad.read': { entries: ScratchpadEntry[]; total:number; path:string; markdown?:string };
  'scratchpad.write': { ok:true; count:number; lastWriteTs:number };
  'scratchpad.compact': { ok:true; before:number; after:number };
};

// Daemon bind helper — call from daemon.ts bindCoreHandlers()
export function bindScratchpadRpcs(register: (method:string, handler:(p:any)=>Promise<any>)=>void) {
  const store = getScratchpad();
  register('scratchpad.read', async (p: ScratchpadRpcPayloads['scratchpad.read']) => {
    const r = store.read(p.missionId, p.offset ?? 0, p.limit ?? 100);
    return { entries: r.entries, total: r.total, path: r.path, markdown: store.readMarkdown(p.missionId) };
  });
  register('scratchpad.write', async (p: ScratchpadRpcPayloads['scratchpad.write']) => {
    // append:true only supported phase — future flag for overwrite reserved
    if (!p.append) throw new Error('scratchpad.write requires append:true in v1');
    const f = store.write(p.missionId, p.text, p.author ?? 'agent');
    return { ok:true as const, count: f.entries.length, lastWriteTs: f.lastWriteTs };
  });
  register('scratchpad.compact', async (p: ScratchpadRpcPayloads['scratchpad.compact']) => {
    const before = store.ensure(p.missionId).entries.length;
    const f = store.compact(p.missionId, p.keep_last_n ?? 50);
    return { ok:true as const, before, after: f.entries.length };
  });
}
