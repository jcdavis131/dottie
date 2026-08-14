export * from './daemon';
export * from './peer';
export * from './version';
export * from './tunnel';
export * from './mux';
export * from './rpc';
export * from './guardrails';
export * from './scratchpad';
export * from './feedback';
export * from './compaction';
export * from './todo';

// barrel re-exports for convenience singleton getters
export { getGuardrails } from './guardrails';
export { getFeedbackHub, getFeedbackStore, getFeedbackStore as getFeedback, registerFeedbackRpc } from './feedback';
export { getCompactionEngine, getCompactionEngine as getCompactionLoop, getCompactionEngine as getCompactionHub, registerCompactionRpc, heuristicCompact } from './compaction';
export { getScratchpad, getThinUiScratchpadFacade } from './scratchpad';
export { getTodoStore, todoStore, bindTodoRpcs, isDestructive } from './todo';
export type { FeedbackEntry, FeedbackRating, FeedbackSubmitPayload, FeedbackAggregate } from './feedback';
export type { CompactionDigest, CompactionTriggerReason, CompactionConfig } from './compaction';
export type { TodoItem, TodoStatus } from './todo';
