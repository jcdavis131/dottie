/**
 * Invariant 06: No shell execution in daemon — All remote operations are typed RPCs.
 * Closes injection class by banning bash -c on caller-controlled strings.
 * Zero-deps, stdlib only.
 * Unified: todo first-class + scratchpad + feedback/compaction + guardrails
 */

export type RpcMethod =
  | 'pty.create'
  | 'pty.attach'
  | 'pty.resize'
  | 'pty.write'
  | 'pty.kill'
  | 'tunnel.open'
  | 'tunnel.close'
  | 'tunnel.status'
  | 'file.read'
  | 'file.write'
  | 'file.stat'
  | 'isl.host'
  | 'isl.request'
  | 'agent.spawn'
  | 'agent.signal'
  | 'version.handshake'
  | 'heartbeat.ping'
  | 'guardrail.list'
  | 'guardrail.check'
  | 'guardrail.toggle'
  | 'scratchpad.read'
  | 'scratchpad.write'
  | 'scratchpad.compact'
  | 'feedback.submit'
  | 'feedback.list'
  | 'feedback.snapshot'
  | 'feedback.push'
  | 'feedback.compact'
  | 'compaction.trigger'
  | 'compaction.snapshot'
  | 'compaction.last20'
  | 'compaction.heuristic'
  | 'todo.create'
  | 'todo.update'
  | 'todo.list'
  | 'todo.move'
  | 'todo.clearDone'
  | 'todo.clear'
  | 'todo.snapshot';

export type FeedbackSubmitPayload = {
  agentId: string;
  host: string;
  rating: 1|2|3|4|5;
  note: string;
  tags?: string[];
  confidence?: number;
  latency_ms?: number;
  lane?: string;
  source?: 'rpc'|'compaction'|'stuck-detector'|'sporadic'|'guardrail';
};

export type RpcPayloadMap = {
  'pty.create': { cols: number; rows: number; cwd: string; env: Record<string,string> };
  'pty.attach': { sessionId: string };
  'pty.resize': { sessionId: string; cols: number; rows: number };
  'pty.write': { sessionId: string; bytes: Uint8Array };
  'pty.kill': { sessionId: string; signal?: string };
  'tunnel.open': { host: string; port: number };
  'tunnel.close': { tunnelId: string };
  'tunnel.status': { tunnelId?: string };
  'file.read': { path: string; offset?: number; length?: number };
  'file.write': { path: string; content: Uint8Array; mode?: number };
  'file.stat': { path: string };
  'isl.host': { host: string; port: number };
  'isl.request': { method: string; url: string; headers: Record<string,string>; body?: Uint8Array };
  'agent.spawn': { cloneId: string; task: string; env?: Record<string,string> };
  'agent.signal': { agentId: string; signal: 'SIGTERM'|'SIGKILL'|'SIGHUP' };
  'version.handshake': { binaryHash: string; wireVersion: number };
  'heartbeat.ping': { ts: number };
  'guardrail.list': {};
  'guardrail.check': { input: string; agentId?: string };
  'guardrail.toggle': { id: string; enabled: boolean };
  'scratchpad.read': { missionId:string; offset?:number; limit?:number };
  'scratchpad.write': { missionId:string; append:boolean; text:string; author?:string };
  'scratchpad.compact': { missionId:string; keep_last_n?:number };
  'feedback.submit': FeedbackSubmitPayload;
  'feedback.list': { limit?: number };
  'feedback.snapshot': {};
  'feedback.push': { agentId?: string; taskId?: string; kind: 'thumbs_up'|'thumbs_down'|'correction'|'note'|'guardrail_hit'; message: string; strength: number };
  'feedback.compact': { recentMessages: string[] };
  'compaction.trigger': { missionId?: string; sessionId?: string; reason?: string; messages?: string[] };
  'compaction.snapshot': {};
  'compaction.last20': {};
  'compaction.heuristic': { messages: string[]; keepLast?: number };
  'todo.create': { missionId?: string; text?: string; title?: string; status?: 'pending'|'in_progress'|'completed'|'cancelled'|'open'|'doing'|'done'|'blocked'; host?: string; agentId?: string; owner?: string; priority?: string; tags?: string[]; linkedPty?: string };
  'todo.update': { missionId?: string; id: string; text?: string; title?: string; status?: 'pending'|'in_progress'|'completed'|'cancelled'|'open'|'doing'|'done'|'blocked'; owner?: string; priority?: string; tags?: string[] };
  'todo.list': { missionId?: string; status?: string; owner?: string; tag?: string };
  'todo.move': { missionId?: string; id: string; status: 'open'|'doing'|'done'|'blocked'|'pending'|'in_progress'|'completed'|'cancelled' };
  'todo.clearDone': { missionId?: string };
  'todo.clear': { missionId?: string; status?: 'pending'|'in_progress'|'completed'|'cancelled'|'open'|'doing'|'done'|'blocked' };
  'todo.snapshot': { missionId?: string };
};

export type RpcResponseMap = {
  'pty.create': { sessionId: string };
  'pty.attach': { sessionId: string; history: Uint8Array[] };
  'pty.resize': { ok: true };
  'pty.write': { bytesWritten: number };
  'pty.kill': { ok: true };
  'tunnel.open': { tunnelId: string; localPort: number };
  'tunnel.close': { ok: true };
  'tunnel.status': { tunnels: { tunnelId:string; host:string; uptimeMs:number }[] };
  'file.read': { content: Uint8Array };
  'file.write': { bytesWritten: number };
  'file.stat': { size:number; mtimeMs:number; isDir:boolean };
  'isl.host': { endpoint: string };
  'isl.request': { status:number; headers: Record<string,string>; body: Uint8Array };
  'agent.spawn': { agentId:string };
  'agent.signal': { ok:true };
  'version.handshake': { accepted:boolean; serverHash:string; serverVersion:number; redeployNeeded:boolean };
  'heartbeat.ping': { pong:number };
  'guardrail.list': { policies: any[]; snapshot: any };
  'guardrail.check': { ok: boolean; violations: any[] };
  'guardrail.toggle': { ok: boolean; policy?: any };
  'scratchpad.read': { entries:any[]; total:number; path:string; markdown?:string };
  'scratchpad.write': { ok:true; count:number; lastWriteTs:number };
  'scratchpad.compact': { ok:true; before:number; after:number };
  'feedback.submit': { ok: true; id: string; ts: number };
  'feedback.list': { entries?: any[]; signals?: any[]; aggregate?: any; total?: number };
  'feedback.snapshot': { last20Count:number; totalCount:number; avgRating:number; blockers:number; needsReview:number; isThinUiReadable:boolean };
  'feedback.push': { id: string; ts: number };
  'feedback.compact': { summary: string };
  'compaction.trigger': { ok: true; digest: any };
  'compaction.snapshot': { runs:number; lastTs:number; lastReason:string|null; messageCount:number; snapshotMs:number; snapshotOk:boolean };
  'compaction.last20': { digests: any[] };
  'compaction.heuristic': { summary: string; keptMessages: number; droppedTokensEst: number };
  'todo.create': { id?: string; todo?: any; snapshot?: any; title?: string };
  'todo.update': { id?: string; todo?: any; ok?: boolean; snapshot?: any };
  'todo.list': { items?: any[]; todos?: any[]; total: number; count?: number; snapshot?: any };
  'todo.move': { id: string; status: string; todo?: any };
  'todo.clearDone': { ok: true; cleared?: number; remaining?: number };
  'todo.clear': { cleared: number; remaining: number; snapshot?: any };
  'todo.snapshot': { missionId: string; count: number; pending:number; in_progressCount:number; completed:number; cancelled:number; todos:any[]; approvalMode:string; singleInProgressEnforced:boolean };
};

export type RpcRequest<K extends RpcMethod = RpcMethod> = {
  id: string;
  method: K;
  payload: RpcPayloadMap[K];
  authTag?: string;
};

export type RpcResponse<K extends RpcMethod = RpcMethod> = {
  id: string;
  method: K;
  ok: boolean;
  payload?: RpcResponseMap[K];
  error?: { code:string; message:string };
};

export class RpcDispatcher {
  private handlers = new Map<RpcMethod, (p:any)=>Promise<any>>();

  register<K extends RpcMethod>(method: K, handler: (payload: RpcPayloadMap[K])=>Promise<RpcResponseMap[K]>) {
    if (this.handlers.has(method)) throw new Error(`handler already registered for ${method}`);
    this.handlers.set(method, handler as any);
  }

  // allow re-register override for lane merges (idempotent bind)
  registerOrUpdate<K extends RpcMethod>(method: K, handler: (payload: RpcPayloadMap[K])=>Promise<RpcResponseMap[K]>) {
    this.handlers.set(method, handler as any);
  }

  has(method: RpcMethod){ return this.handlers.has(method); }

  async dispatch<K extends RpcMethod>(req: RpcRequest<K>): Promise<RpcResponse<K>> {
    const h = this.handlers.get(req.method);
    if (!h) {
      return { id:req.id, method:req.method, ok:false, error:{code:'UNKNOWN_METHOD', message:`unknown method ${req.method}`} };
    }
    if ((req.method as string).includes('bash') || (req.method as string).includes('exec')) {
      return { id:req.id, method:req.method, ok:false, error:{code:'FORBIDDEN', message:'shell execution forbidden by invariant 06'}};
    }
    try {
      const result = await h(req.payload);
      return { id:req.id, method:req.method, ok:true, payload: result };
    } catch (e:any) {
      return { id:req.id, method:req.method, ok:false, error:{code:'HANDLER_ERROR', message: e?.message ?? String(e)} };
    }
  }

  static assertNoShellStrings(code: string) {
    const forbidden = ['bash -c', 'sh -c', 'child_process.exec(', 'spawn(' , '`', '$('];
    for (const pat of forbidden) {
      if (code.includes(pat) && !code.includes('// allowed:')) {
        throw new Error(`Potential shell injection pattern detected: ${pat} — use typed RPC instead`);
      }
    }
    return true;
  }
}

export function createSecureDispatcher(): RpcDispatcher {
  const d = new RpcDispatcher();
  d.register('heartbeat.ping', async (p)=> ({ pong: Date.now() }));
  d.register('version.handshake', async (p)=> ({ accepted:true, serverHash:p.binaryHash, serverVersion:p.wireVersion, redeployNeeded:false }));
  return d;
}
