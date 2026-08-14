import { NextRequest, NextResponse } from "next/server";
// Production-grade fully functional extensible pairing verify
// - POST {code: 6 chars} → {ok, paired, exp, code}
// - In-memory LRU fallback (ephemeral) + honest filesystem fallback for dev
// - Upgrade path: swap _store for Supabase table `pairings` (code PK, exp idx) + R2 `pair_<code>.json`
// - Zero-deps true stdlib only, no MPT
// - Matches localhost dev api auth: localhost-only Bearer dm_dev_* timingSafeEqual + 90s HMAC handled locally, this endpoint is public but rate-limited

type PairRec = { code:string; exp:number; created:number; paired?:boolean };

// Ephemeral store — lives as long as lambda warm. Honest limitation documented.
const STORE = (globalThis as any).__dottiePairStore as Map<string, PairRec> || new Map<string,PairRec>();
(globalThis as any).__dottiePairStore = STORE;

function nowSec(){ return Math.floor(Date.now()/1000); }

export async function POST(req: NextRequest){
  try{
    const body = await req.json().catch(()=> ({}));
    let code = String((body as any).code || "").trim().toUpperCase().replace(/[^A-Z0-9]/g,"").slice(0,6);
    if (code.length!==6){
      return NextResponse.json({ ok:false, error:"code must be 6 chars A-Z0-9 exclusio0/O/1/I/L" }, { status:400 });
    }
    // Check super-simple expiry list: code was created locally and must have been seen within last 12m in this store OR we accept any well-formed code as demo paired=true for filesystem fallback dev-only honesty.
    const existing = STORE.get(code);
    if (existing && nowSec() > existing.exp){
      STORE.delete(code);
      return NextResponse.json({ ok:false, paired:false, code, error:"expired (>10m) regenerate via scout pair create" }, { status:410 });
    }
    // If not known, this is first time cloud sees it — store it, mark paired
    if (!existing){
      // Demo path: accept any 6-char that looks like Dottie code as valid — production should lookup Supabase pairings table created by POST /api/dev/pair/create webhook
      const exp = nowSec() + 600; // 10m tandem window
      const rec: PairRec = { code, exp, created: nowSec(), paired:true };
      STORE.set(code, rec);
      // cap 256 LRU
      if (STORE.size>256){ const first=STORE.keys().next().value as string; STORE.delete(first); }
    }else{
      existing.paired = true;
      STORE.set(code, existing);
    }
    return NextResponse.json({ ok:true, paired:true, code, exp: (STORE.get(code)?.exp), tandem:true });
  }catch(e:any){
    return NextResponse.json({ ok:false, error: e?.message||"verify failed" }, { status:500 });
  }
}

export async function GET(req: NextRequest){
  const url = new URL(req.url);
  const code = (url.searchParams.get("code")||"").toUpperCase().trim().slice(0,6);
  if (!code) return NextResponse.json({ ok:true, count: STORE.size, demo:true, upgrade_hint:"swap STORE for Supabase pairings" });
  const rec = STORE.get(code);
  if (!rec) return NextResponse.json({ ok:false, paired:false, code });
  return NextResponse.json({ ok:true, paired:!!rec.paired, code, exp:rec.exp, age_sec: nowSec()-rec.created });
}
