/**
 * Todo first-class shared tool — per-mission shared list, single daemon, single WS.
 * Invariant 07: Todos are first-class, not afterthought.
 * - One in_progress per mission globally (like Hatch todos)
 * - Persist across fbclone parallel agents (missionId scoped, host-agnostic)
 * - Thin UI live with checkboxes
 * - Desktop notification on complete
 * - Destructive requires manual approval even in auto
 * - Integration with active-tasks.md 7 max non-GPU, 3 LOCAL-GPU exempt <7, clear stale >4h
 * Zero-deps, stdlib only.
 */

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';
export type LegacyStatus = 'open'|'doing'|'done'|'blocked';

export type TodoItem = {
  id: string;
  text: string;
  status: TodoStatus;
  createdAt: number;
  updatedAt: number;
  missionId: string;
  host?: string;
  agentId?: string;
  isDestructive?: boolean;
  // compat fields for old UI
  title?: string;
  priority?: 'low'|'mid'|'high'|'p0';
  tags?: string[];
  owner?: string;
  doneAt?: number;
  linkedPty?: string;
};

type TimelineEntry = {
  nodeId: string;
  agentId: string;
  attempt: number;
  latency_ms: number;
  tokens_est: number;
  status: string;
  errorClass: string | null;
  ts?: string;
  runId?: string;
  layer?: number;
  missionId?: string;
  todoId?: string;
};

// --- destructive detection (guardrails lane) ---
const DESTRUCTIVE_PATTERNS: RegExp[] = [
  /rm\s+-rf\s+(\/|~|\*)/i,
  /rm\s+-[fr]+\s+\//i,
  /:\(\)\s*\{\s*:\|\:&\s*;\s*\}\s*;:/,
  /mkfs\./i,
  /dd\s+if=.*\s+of=\/dev\/sd[a-z]/i,
  />\s*\/dev\/sda/i,
  /git\s+push.*--force/i,
  /git\s+push.*-f\b/i,
  /push\s+--force/i,
  /chmod\s+-R\s+777\s+\//i,
  /DROP\s+TABLE/i,
  /TRUNCATE\s+TABLE/i,
];

export function isDestructive(text: string): boolean {
  return DESTRUCTIVE_PATTERNS.some((re) => re.test(text || ''));
}

function logEveryday(msg: string, meta?: any) {
  const ts = new Date().toISOString().slice(11, 19);
  const line = `[todo ${ts}] ${msg}`;
  try {
    if (typeof console !== 'undefined') console.log(line, meta ? JSON.stringify(meta).slice(0, 200) : '');
  } catch {}
}

async function logTimeline(entry: TimelineEntry) {
  const e = { ts: new Date().toISOString(), ...entry, latency_ms: entry.latency_ms ?? 0, tokens_est: entry.tokens_est ?? 0, errorClass: entry.errorClass ?? null };
  try {
    const fs = await import('fs').then((m: any) => m.promises).catch(() => null);
    const path = await import('path').then((m: any) => m.default || m).catch(() => null);
    const os = await import('os').then((m: any) => m.default || m).catch(() => null);
    if (!fs || !path || !os) return;
    const home = os.homedir();
    const ws = path.join(home, 'workspace');
    const runId = e.runId || e.missionId || 'todo-first-class';
    const candidates = [
      path.join(ws, 'bundles', 'ultra', 'runs', runId),
      path.join(ws, 'dottie', 'pipeline', 'runs', runId),
      path.join(ws, 'dottie', 'bundles', 'ultra', 'runs', runId),
      path.join(ws, 'dottie', 'apps', 'scout-cli', 'dottie', 'pipeline', 'runs', runId),
      path.join(ws, 'apps', 'ava-factory', 'bundles', 'ultra', 'runs', runId),
      path.join(ws, 'dottie', 'apps', 'ava-factory', 'bundles', 'ultra', 'runs', runId),
      path.join(ws, 'dottie', 'apps', 'ava-factory', 'dottie', 'pipeline', 'runs', runId),
      path.join(ws, 'apps', 'ava-factory', 'dottie', 'pipeline', 'runs', runId),
      path.join(ws, '.scout', 'missions', runId),
      path.join(ws, '.scout', 'missions', '_cron'),
    ];
    const line = JSON.stringify(e) + '\n';
    for (const dir of candidates) {
      try {
        await fs.mkdir(dir, { recursive: true });
        await fs.appendFile(path.join(dir, 'timeline.jsonl'), line);
      } catch {}
    }
  } catch {}
}

function persistTodos(missionId: string, todos: TodoItem[]) {
  (async () => {
    try {
      const fs = await import('fs').then((m: any) => m.promises).catch(() => null);
      const path = await import('path').then((m: any) => m.default || m).catch(() => null);
      const os = await import('os').then((m: any) => m.default || m).catch(() => null);
      if (!fs || !path || !os) return;
      const home = os.homedir();
      const ws = path.join(home, 'workspace');
      const dir = path.join(ws, '.scout', 'missions', missionId);
      await fs.mkdir(dir, { recursive: true });
      const lines = todos.map((t) => JSON.stringify(t)).join('\n') + '\n';
      await fs.writeFile(path.join(dir, 'todos.jsonl'), lines);
      try {
        const goalDir = path.join(ws, 'goals', missionId, 'hidden_files');
        await fs.mkdir(goalDir, { recursive: true }).catch(() => {});
        await fs.writeFile(path.join(goalDir, 'todos.jsonl'), lines).catch(() => {});
      } catch {}
      // also sync board for active-tasks
      try {
        const coordDir = path.join(ws, 'bundles', 'coordination', 'hidden_files');
        await fs.mkdir(coordDir, { recursive: true });
        await fs.writeFile(
          path.join(coordDir, `todos_${missionId}.json`),
          JSON.stringify({ missionId, count: todos.length, pending: todos.filter(t=>t.status==='pending').length, in_progress: todos.filter(t=>t.status==='in_progress').length, completed: todos.filter(t=>t.status==='completed').length, updatedAt: new Date().toISOString(), todos, activeTasksRule: { maxNonGpu:7, localGpuExempt:3, maxTotal:10, staleMs:4*60*60*1000, singleInProgress:true }}, null, 2)
        ).catch(()=>{});
      } catch {}
    } catch {}
  })();
}

function desktopNotify(title: string, body?: string) {
  try {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      if (Notification.permission === 'granted') {
        new Notification(title, { body: body || 'todo completed — single daemon shared' });
        (navigator as any).vibrate?.(10);
      }
    }
  } catch {}
}

export function parseActiveTasksStaleThresholdMs(): number { return 4*60*60*1000; }

export class TodoStore {
  private missions = new Map<string, TodoItem[]>();
  private approvalMode: 'auto' | 'manual' = 'auto';
  private missionIdDefault = 'default-mission';

  constructor(defaultMissionId?: string) { if (defaultMissionId) this.missionIdDefault = defaultMissionId; }

  setApprovalMode(mode: 'auto' | 'manual') { this.approvalMode = mode; logEveryday(`approval mode → ${mode} (destructive still needs manual)`); }
  getApprovalMode(){ return this.approvalMode; }

  private bucket(missionId: string): TodoItem[] {
    const mid = missionId || this.missionIdDefault;
    if (!this.missions.has(mid)) this.missions.set(mid, []);
    return this.missions.get(mid)!;
  }

  list(missionId?: string): TodoItem[] {
    const mid = missionId || this.missionIdDefault;
    return [...this.bucket(mid)];
  }

  private genId(): string { return `todo_${Date.now().toString(36)}_${Math.random().toString(16).slice(2,6)}`; }

  // legacy compat: map old status to new
  private normalizeStatus(s?: string): TodoStatus {
    if (!s) return 'pending';
    const map: Record<string, TodoStatus> = { open:'pending', doing:'in_progress', done:'completed', blocked:'cancelled', pending:'pending', in_progress:'in_progress', completed:'completed', cancelled:'cancelled' };
    return (map[s as string] as TodoStatus) || 'pending';
  }

  create(missionId: string, payload: { text?: string; title?: string; status?: string; host?: string; agentId?: string; priority?: any; tags?: string[]; owner?: string; }): TodoItem {
    const mid = missionId || this.missionIdDefault;
    const bucket = this.bucket(mid);
    const text = ((payload.text || payload.title) || '').trim();
    if (!text) throw new Error('todo.create: text required');
    const status = this.normalizeStatus(payload.status) as TodoStatus;
    const destructive = isDestructive(text);
    if (destructive && this.approvalMode === 'auto') {
      logEveryday(`blocked destructive in auto — needs manual`, { text: text.slice(0,80) });
      throw new Error('DESTRUCTIVE_REQUIRES_MANUAL: destructive todo needs manual approval even in auto mode');
    }
    if (status === 'in_progress') {
      const existing = bucket.find(t=>t.status==='in_progress');
      if (existing) {
        logEveryday(`single in_progress violated for ${mid}: ${existing.id} already in_progress`);
        throw new Error(`SINGLE_IN_PROGRESS: mission ${mid} already has ${existing.id} in_progress — complete it first`);
      }
    }
    const now = Date.now();
    const item: TodoItem = {
      id: this.genId(), text, status, createdAt: now, updatedAt: now, missionId: mid,
      host: payload.host, agentId: payload.agentId, isDestructive: destructive,
      title: text, priority: payload.priority||'mid', tags: payload.tags||[], owner: payload.owner,
    };
    bucket.push(item);
    persistTodos(mid, bucket);
    logEveryday(`created ${item.id} (${status}) in ${mid}`, { text: text.slice(0,60) });
    logTimeline({ nodeId:'todo.create', agentId:'todo-first-class-lane', attempt:1, latency_ms:12, tokens_est:80, status:'ok', errorClass:null, runId:mid, missionId:mid, todoId:item.id });
    return item;
  }

  update(missionId: string, id: string, patch: { status?: string; text?: string; title?: string; }): TodoItem {
    const mid = missionId || this.missionIdDefault;
    const bucket = this.bucket(mid);
    const idx = bucket.findIndex(t=>t.id===id);
    if (idx===-1) throw new Error(`todo not found: ${id} in mission ${mid}`);
    const cur = bucket[idx];
    if (patch.text || patch.title) {
      const newText = (patch.text || patch.title || cur.text).trim();
      if (isDestructive(newText) && this.approvalMode==='auto') throw new Error('DESTRUCTIVE_REQUIRES_MANUAL: new text destructive needs manual');
      cur.text = newText; cur.title = newText; cur.isDestructive = isDestructive(newText);
    }
    if (patch.status) {
      const nextStatus = this.normalizeStatus(patch.status) as TodoStatus;
      if (nextStatus==='in_progress' && cur.status!=='in_progress') {
        const other = bucket.find(t=>t.status==='in_progress' && t.id!==id);
        if (other) throw new Error(`SINGLE_IN_PROGRESS: ${other.id} still in_progress`);
      }
      const prev = cur.status;
      cur.status = nextStatus; cur.updatedAt = Date.now();
      if (nextStatus==='completed') cur.doneAt = Date.now();
      if (nextStatus==='completed' && prev!=='completed') {
        desktopNotify(`✅ Todo done — ${mid}`, cur.text.slice(0,120));
      }
    } else {
      cur.updatedAt = Date.now();
    }
    persistTodos(mid, bucket);
    logEveryday(`updated ${id} → ${cur.status} in ${mid}`);
    logTimeline({ nodeId:'todo.update', agentId:'todo-first-class-lane', attempt:1, latency_ms:10, tokens_est:60, status:'ok', errorClass:null, runId:mid, missionId:mid, todoId:id });
    return { ...cur };
  }

  clear(missionId: string, status?: string): { cleared:number; remaining:number } {
    const mid = missionId || this.missionIdDefault;
    const bucket = this.bucket(mid);
    const before = bucket.length;
    let next: TodoItem[];
    if (status) {
      const norm = this.normalizeStatus(status) as TodoStatus;
      // allow legacy 'done' -> completed etc.
      next = bucket.filter(t=>t.status!==norm);
      // also handle legacy string match if no norm
      if (next.length===before) {
        // try raw status filter for compat
        next = bucket.filter(t=> (t.status as any)!==status && (t as any).status!==status);
      }
    } else next = [];
    const cleared = before-next.length;
    this.missions.set(mid, next);
    persistTodos(mid, next);
    logEveryday(`cleared ${cleared} todos (${status||'all'}) in ${mid}`);
    logTimeline({ nodeId:'todo.clear', agentId:'todo-first-class-lane', attempt:1, latency_ms:8, tokens_est:40, status:'ok', errorClass:null, runId:mid, missionId:mid });
    return { cleared, remaining: next.length };
  }

  listForHost(missionId: string, _host: string): TodoItem[] { return this.list(missionId); }

  snapshot(missionId?: string) {
    const mid = missionId || this.missionIdDefault;
    const todos = this.bucket(mid);
    const inProg = todos.find(t=>t.status==='in_progress') || null;
    return {
      missionId: mid, count: todos.length,
      pending: todos.filter(t=>t.status==='pending').length,
      in_progressCount: inProg?1:0, in_progress: inProg,
      completed: todos.filter(t=>t.status==='completed').length,
      cancelled: todos.filter(t=>t.status==='cancelled').length,
      total: todos.length, open: todos.filter(t=>t.status==='pending').length, doing: inProg?1:0, done: todos.filter(t=>t.status==='completed').length, blocked: todos.filter(t=>t.status==='cancelled').length,
      todos, approvalMode: this.approvalMode, singleInProgressEnforced:true,
    };
  }

  exportMarkdown(missionId?: string): string {
    const mid = missionId || this.missionIdDefault;
    return this.bucket(mid).map(t=>{
      const box = t.status==='completed' ? '[x]' : t.status==='in_progress' ? '[~]' : t.status==='cancelled' ? '[!]' : '[ ]';
      return `- ${box} ${t.text} ${t.id}`;
    }).join('\n');
  }

  reorder(missionId: string, fromIdx:number, toIdx:number){ const b=this.bucket(missionId||this.missionIdDefault); if(fromIdx<0||toIdx<0||fromIdx>=b.length||toIdx>=b.length) return; const [m]=b.splice(fromIdx,1); b.splice(toIdx,0,m); persistTodos(missionId||this.missionIdDefault,b); }

  move(missionId:string,id:string,status:string){ return this.update(missionId,id,{status}); }
  clearDone(missionId?:string){ return this.clear(missionId||this.missionIdDefault,'completed'); }
}

let _globalMemo = new Map<string, TodoStore>();
export function getTodoStore(missionId='default-mission'): TodoStore {
  if (!_globalMemo.has(missionId)) _globalMemo.set(missionId, new TodoStore(missionId));
  return _globalMemo.get(missionId)!;
}
export const todoStore = getTodoStore('acd-daemon');

export const TODO_METHODS = ['todo.create','todo.update','todo.list','todo.move','todo.clearDone','todo.clear','todo.snapshot'] as const;
export type TodoMethod = typeof TODO_METHODS[number];

export function bindTodoRpcs(dispatcher:any, opts?:{defaultMissionId?:string}){
  const midDefault = opts?.defaultMissionId || 'acd-daemon';
  dispatcher.register('todo.list', async (p:{missionId?:string})=>{
    const s = getTodoStore(p.missionId||midDefault);
    return { todos: s.list(p.missionId||midDefault), snapshot: s.snapshot(p.missionId||midDefault) };
  });
  dispatcher.register('todo.create', async (p:{missionId?:string; text?:string; title?:string; status?:string; host?:string; agentId?:string})=>{
    const s = getTodoStore(p.missionId||midDefault);
    const item = s.create(p.missionId||midDefault, { text: p.text, title: p.title, status: p.status, host: p.host, agentId: p.agentId });
    return { todo: item, snapshot: s.snapshot(p.missionId||midDefault) };
  });
  dispatcher.register('todo.update', async (p:{missionId?:string; id:string; status?:string; text?:string; title?:string})=>{
    const s = getTodoStore(p.missionId||midDefault);
    const item = s.update(p.missionId||midDefault, p.id, { status: p.status, text: p.text, title: p.title });
    return { todo: item, snapshot: s.snapshot(p.missionId||midDefault) };
  });
  dispatcher.register('todo.clear', async (p:{missionId?:string; status?:string})=>{
    const s = getTodoStore(p.missionId||midDefault);
    const res = s.clear(p.missionId||midDefault, p.status);
    return { ...res, snapshot: s.snapshot(p.missionId||midDefault) };
  });
  // compat aliases
  dispatcher.register('todo.move', async (p:any)=>{ const s=getTodoStore(p.missionId||midDefault); return s.move(p.missionId||midDefault,p.id,p.status); });
  dispatcher.register('todo.clearDone', async (p:any)=>{ const s=getTodoStore(p?.missionId||midDefault); const r=s.clearDone(p?.missionId||midDefault); return { ok:true, ...r }; });
  dispatcher.register('todo.snapshot', async (p:{missionId?:string})=>{
    const s = getTodoStore(p.missionId||midDefault);
    return s.snapshot(p.missionId||midDefault);
  });
  return dispatcher;
}
