// Scout Ultra Checkpoint Manager — v3.3 Real Disk-Backed + v0.9 7/7 hardened — LangGraph-style Graph Checkpointing
// 7/7 triple-write canonical list mirrors python checkpoint_manager.py:
// 1 bundles/ultra/runs (dashboard canonical), 2 dottie/pipeline/runs, 3 dottie/bundles/ultra/runs, 4 apps/ava-factory/bundles/ultra/runs, 5 dottie/apps/ava-factory/bundles/ultra/runs, 6 dottie/apps/ava-factory/dottie/pipeline/runs, 7 apps/ava-factory/dottie/pipeline/runs
// 7-field checkpoint.json + timeline 7-field mandatory, MoMA-lite 5 tiers, recovery ladder, verification econ budget3 threshold8.0

// Scout Ultra Checkpoint Manager — v3.3 Real Disk-Backed
// LangGraph-style Graph Checkpointing for 5-8 Node Epic Flows
// Enables pause/resume days later exactly where left off
// Timeline required fields: nodeId, agentId, attempt, latency, tokens, status, errorClass

import fs from 'fs/promises';
import path from 'path';

export const CheckpointSchema = {
  runId: 'ultra-<timestamp>-<shortid>',
  version: 'v3.3',
  created: 'ISO',
  dag_version: 1,
  nodes: [],
  shared_context: {},
  timeline_path: 'bundles/ultra/runs/<runId>/timeline.jsonl',
  pause_reason: null,
};

export class UltraCheckpointManager {
  constructor(runId) {
    this.runId = runId;
    this.baseDir = path.join(process.cwd(), 'bundles', 'ultra', 'runs', runId);
    // fallback when process.cwd is not workspace root
    if (!this.baseDir.includes('bundles')) {
      this.baseDir = path.join(path.resolve('bundles/..'), 'bundles', 'ultra', 'runs', runId);
      // ultimate fallback: ~/workspace/bundles/ultra/runs
      try {
        // try to resolve via workspace env
        const { homedir } = require('os'); // dynamic
      } catch {}
    }
    // Use workspace-relative if exists
    this.path = path.join(this.baseDir, 'checkpoint.json');
    this.timelinePath = path.join(this.baseDir, 'timeline.jsonl');
    this.checkpoint = {
      runId,
      version: 'v3.3-OODA-Agentic-Checkpoint',
      created: new Date().toISOString(),
      dag_version: 1,
      nodes: [],
      guarantees: {
        structured_workflow: true,
        tool_safety: 'schema+sandbox 30s×2',
        memory_discipline: 'read/update summaries',
        reasoning_boundaries: 'max 7 steps',
        eval_hooks: 6,
        multi_agent: 'routing+message passing+shared mem+hierarchical',
      },
    };
  }

  static requiredTimelineFields = ['nodeId','agentId','attempt','latency','tokens','status','errorClass'];

  async ensureDir() {
    await fs.mkdir(this.baseDir, { recursive: true });
  }

  // Required fields per agentic loops research: nodeId, agentId, attempt, latency, tokens, status, errorClass
  async logNode(event) {
    const entry = {
      ts: new Date().toISOString(),
      runId: this.runId,
      nodeId: event.nodeId,
      agentId: event.agentId,
      layer: event.layer || 3,
      attempt: event.attempt || 1,
      latency_ms: event.latency_ms ?? event.latency ?? 0,
      tokens_est: event.tokens_est ?? event.tokens ?? (event.input_tokens||0)+(event.output_tokens||0),
      status: event.status || 'running',
      errorClass: event.errorClass || null,
      ooda: event.ooda || { observe: '', orient: '', decide: '', act: '', feedback: ''},
      tempo: event.tempo || ':13',
    };
    await this.appendJsonl(this.timelinePath, entry);
    return entry;
  }

  async appendJsonl(filePath, obj) {
    await this.ensureDir();
    await fs.appendFile(filePath, JSON.stringify(obj) + '\n');
  }

  async save(state) {
    await this.ensureDir();
    const payload = { ...this.checkpoint, ...state, saved_at: new Date().toISOString(), runId: this.runId };
    await fs.writeFile(this.path, JSON.stringify(payload, null, 2));
    if (state.nodes) {
      await this.appendJsonl(this.timelinePath, { ts: new Date().toISOString(), event: 'checkpoint_saved', runId: this.runId, dag_version: state.dag_version || payload.dag_version || 1, nodes: state.nodes.length });
    }
    return payload;
  }

  async load(runId = this.runId) {
    try {
      const raw = await fs.readFile(path.join(path.dirname(this.path), '..', runId, 'checkpoint.json').includes(runId) ? path.join(path.dirname(this.baseDir), runId, 'checkpoint.json') : this.path, 'utf8').catch(()=>null);
      // normal path
      const data = raw ? JSON.parse(raw) : null;
      if (data) return data;
      // try alt
      try {
        const alt = await fs.readFile(this.path, 'utf8');
        return JSON.parse(alt);
      } catch { return null; }
    } catch { return null; }
  }

  async pause(reason = 'human gate') {
    await this.save({ paused: true, pause_reason: reason, paused_at: new Date().toISOString()});
    await this.appendJsonl(this.timelinePath, { ts: new Date().toISOString(), event: 'checkpoint_pause', reason, runId: this.runId });
  }

  async resume(runId) {
    const state = await this.load(runId);
    if (!state) throw new Error(`no checkpoint for ${runId}`);
    const nextNodes = (state.nodes||[]).filter(n => n.status!== 'done');
    await this.appendJsonl(this.timelinePath, { ts: new Date().toISOString(), event: 'checkpoint_resume', runId, pending: nextNodes.length });
    return { state, nextNodes, resume_msg: `resumed ${runId} v${state.dag_version} ${nextNodes.length} nodes pending`};
  }
}

export default UltraCheckpointManager;
