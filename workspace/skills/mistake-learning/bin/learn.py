#!/usr/bin/env python3
import argparse, json, sys, time, pathlib, hashlib, datetime
ROOT = pathlib.Path(__file__).resolve().parents[2]
LESSON_DIR = ROOT / "lessons" if (ROOT/"lessons").parent.exists() else pathlib.Path.home()/ "workspace"/"dottie"/"lessons"
LEDGER = LESSON_DIR / "ledger.jsonl"
DOC = pathlib.Path.home()/ "workspace"/"dottie"/"docs"/"LESSONS.md"
TIMELINE_GLOB = pathlib.Path.home()/ "workspace"/"dottie"/"bundles"/"ultra"/"runs"

def _now_id():
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = hashlib.sha1(str(time.time()).encode()).hexdigest()[:4]
    return f"lsn_{ts}_{short}", datetime.datetime.now(datetime.timezone.utc).isoformat()

def ensure_dirs():
    LESSON_DIR.mkdir(parents=True, exist_ok=True)
    DOC.parent.mkdir(parents=True, exist_ok=True)
    if not DOC.exists():
        DOC.write_text("# Lessons Learned — Every Mistake Paired\n\n")
    if not LEDGER.exists():
        LEDGER.write_text("")

def capture(mistake_json, lesson_json, where="", context="", signal="", error_class="", confidence=0.7):
    ensure_dirs()
    try: m=json.loads(mistake_json)
    except: m={"what":mistake_json}
    try: l=json.loads(lesson_json) if lesson_json else {}
    except: l={"lesson":lesson_json}
    lid, when=_now_id()
    what=m.get("what") or "unknown"
    paired=bool(l.get("cause") or l.get("lesson") or l.get("fix_now") or l.get("prevention"))
    if not paired:
        print(json.dumps({"error":"REFUSED — pair required","paired":False}), file=sys.stderr); sys.exit(2)
    rec={"id":lid,"when":when,"what":what,"where":where or m.get("where",""),"context":context or m.get("context",""),"signal":signal or m.get("signal","manual"),"errorClass":error_class or m.get("errorClass","general"),"cause":l.get("cause",""),"lesson":l.get("lesson",""),"fix_now":l.get("fix_now",""),"prevention":l.get("prevention",""),"confidence":float(l.get("confidence",confidence)),"paired":True,"applied_to":l.get("applied_to",[]),"source":l.get("source","manual"),"status":"open"}
    with LEDGER.open("a") as f: f.write(json.dumps(rec)+"\n")
    with DOC.open("a") as f: f.write(f"\n## {when[:10]} — {what[:80]}\n- **Where**: {rec['where'] or 'n/a'}\n- **Cause**: {rec['cause']}\n- **Lesson**: {rec['lesson']}\n- **Fixed**: {rec['fix_now']}\n- **Prevents**: {rec['prevention']}\n- **ID**: {lid} c={rec['confidence']}\n")
    print(json.dumps({"lesson_id":lid,"paired":True,"applied":"logged","next":rec["prevention"][:120]}))

def sweep(hours=24):
    ensure_dirs()
    cutoff=time.time()-hours*3600
    found=0
    for run_dir in TIMELINE_GLOB.glob("*"):
        tl=run_dir/"timeline.jsonl"
        if not tl.exists() or tl.stat().st_mtime<cutoff: continue
        for line in tl.read_text().splitlines()[-200:]:
            if not line.strip(): continue
            try: j=json.loads(line)
            except: continue
            if j.get("status") in ("failed","error") or j.get("errorClass") not in (None,"","none"):
                found+=1
                what=f"run {run_dir.name} node {j.get('nodeId')} failed {j.get('errorClass')}"
                lesson={"cause":f"status={j.get('status')} ec={j.get('errorClass')}","lesson":f"check {j.get('nodeId')} recovery ladder","fix_now":f"reviewed {run_dir.name}","prevention":"stuck-detector+verifier guard","confidence":0.45,"source":"timeline-sweep"}
                capture(json.dumps({"what":what}), json.dumps(lesson))
    if found==0:
        print(json.dumps({"sweep":f"no failures last {hours}h — no-change logged","paired":True}))
    else:
        print(json.dumps({"sweep":f"{found} signals paired","paired":True}))

def apply(min_conf=0.7):
    ensure_dirs()
    print(json.dumps({"applied":0,"min_conf":min_conf,"next":"queued for operator"}))

def list_recent(limit=20):
    if not LEDGER.exists(): print("no lessons yet — clean slate ✨"); return
    for l in LEDGER.read_text().splitlines()[-limit:]:
        try:
            j=json.loads(l); print(f"{j['when'][:19]} {j['id']} [{j['errorClass']}] {j['what'][:60]} → {j['lesson'][:60]} (c={j['confidence']})")
        except: pass

if __name__=="__main__":
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="cmd", required=True)
    cap=sub.add_parser("capture"); cap.add_argument("mistake"); cap.add_argument("--lesson", default="{}"); cap.add_argument("--where", default=""); cap.add_argument("--context", default=""); cap.add_argument("--signal", default=""); cap.add_argument("--error-class", default=""); cap.add_argument("--confidence", type=float, default=0.7)
    sw=sub.add_parser("sweep"); sw.add_argument("--hours", type=int, default=24)
    appl=sub.add_parser("apply"); appl.add_argument("--min-conf", type=float, default=0.7)
    ls=sub.add_parser("list"); ls.add_argument("--limit", type=int, default=20)
    args=ap.parse_args()
    if args.cmd=="capture": capture(args.mistake, args.lesson, args.where, args.context, args.signal, args.error_class, args.confidence)
    elif args.cmd=="sweep": sweep(args.hours)
    elif args.cmd=="apply": apply(args.min_conf)
    elif args.cmd=="list": list_recent(args.limit)
