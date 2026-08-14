import { NextRequest, NextResponse } from "next/server";
// GET /api/pair/status?code=X7K9PQ → paired?  + queue depth (if using Supabase realtime or Redis)
// Extensible: replace counted in-memory file list with Redis XLEN dottie:queue or Supabase SELECT count
const STORE = (globalThis as any).__dottiePairStore as Map<string,any> || new Map();
(globalThis as any).__dottiePairStore = STORE;

export async function GET(req: NextRequest){
  const url = new URL(req.url);
  const code = (url.searchParams.get("code")||"").toUpperCase().trim().slice(0,6);
  if (code){
    const rec = STORE.get(code);
    if (!rec) return NextResponse.json({ ok:false, paired:false, code });
    return NextResponse.json({ ok:true, paired:!!rec.paired, code, exp:rec.exp, count: STORE.size });
  }
  return NextResponse.json({ ok:true, paired_count: STORE.size, queue_demo: "fs /ws/.dottie/queue or redis dottie:queue or Supabase realtime", tandem:"local+docker+website link" });
}
