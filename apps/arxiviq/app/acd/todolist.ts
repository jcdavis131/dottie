/**
 * todolist alias — provides same API as daemon expects (bindTodoRpcs etc)
 * Wraps todo.ts TodoStore which is per-mission first-class
 */
export * from './todo';
import { getTodoStore } from './todo';

export type TodoListItem = any;

export function getTodoList(missionId='default') {
  // per-mission sharding would be added via getTodoStore scoping; for shim use singleton
  const store = getTodoStore();
  return {
    list: () => store.list(),
    create: (text:string, opts?:any) => store.create(text, opts),
    snapshot: () => store.snapshot(),
    _raw: store,
  };
}

export function bindTodoRpcs(register:(method:string, handler:(p:any)=>Promise<any>)=>void){
  const store = getTodoStore();
  register('todo.create', async (p:any)=> store.create(p.title ?? p.text, p));
  register('todo.update', async (p:any)=> {
    // todo.ts update expects id + patch
    const r = (store as any).update ? (store as any).update(p.id, p) : null;
    return r ?? { error:'not_found' };
  });
  register('todo.list', async (p:any)=> ({ items: store.list(p), total: store.list().length }));
  register('todo.move', async (p:any)=> {
    const r = (store as any).move ? (store as any).move(p.id, p.status) : (store as any).update?.(p.id, { status: p.status });
    return r ?? { error:'not_found' };
  });
  register('todo.clearDone', async ()=> { (store as any).clearDone?.(); return { ok:true }; });
  // compat alternate names used by some panels
  register('todolist.list', async (p:any)=> ({ items: store.list(p), total: store.list().length }));
  register('todolist.create', async (p:any)=> store.create(p.title ?? p.text, p));
}
