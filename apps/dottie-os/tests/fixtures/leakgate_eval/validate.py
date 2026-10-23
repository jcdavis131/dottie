import json,glob,os,base64,collections,re,sys
# Mill validate.py d33e3330 + explicit ROOT argv + utf-8 reads + optional --dump of per-case reasons
ROOT=sys.argv[1]
STRUCT={'schema','id','tier','source','state','questions','labels','consent','trajectory_id','fixture'}
def gold(r):
    if r['tier']=='L3': return r['labels']['action']['choice']
    if 'domain' in r['labels']: return r['labels']['domain']['choice']
    return None
def gnum(r): return r['labels'].get('safe',{}).get('noul')
GOLDTOKENS=set()

def flatten(obj,prefix=''):
    out=[]
    if isinstance(obj,dict):
        for k,v in obj.items():
            out+=flatten(v,prefix+'/'+str(k))
    elif isinstance(obj,list):
        out.append((prefix,json.dumps(obj,ensure_ascii=False)))
    else:
        out.append((prefix,obj))
    return out

def candidate_fields(r):
    # non-message input fields: state.* except message, + injected top-level keys
    fields=[]
    st={k:v for k,v in r['state'].items() if k!='message'}
    fields+=flatten(st,'state')
    for k,v in r.items():
        if k not in STRUCT:
            fields+=flatten(v,'top/'+k)
    return fields

def msg_suffix_tokens(r):
    m=r['state']['message']; toks=set()
    for mm in re.finditer(r'//\s*(\{.*\})',m):
        try:
            for v in json.loads(mm.group(1)).values():
                toks.add(('msgsuffix',str(v)))
        except Exception: pass
    return toks

def detect(rows, sidecar):
    n=len(rows); golds=[gold(r) for r in rows]
    ndistinct_gold=len(set(golds))
    reasons=[]
    # 1) generic value->gold purity with repeated values
    colvals=collections.defaultdict(list)
    for r in rows:
        seen=set()
        for path,val in candidate_fields(r):
            key=re.sub(r'/\d+','/[]',path)
            colvals[key].append((val,gold(r)))
    for key,pairs in colvals.items():
        if len(pairs)<n: continue   # field not on all rows
        vals=[v for v,_ in pairs]; dv=len(set(vals))
        if dv<2 or dv>=n: continue  # constant, or all-unique (no generalization)
        pure=all(len({g for v2,g in pairs if v2==v})==1 for v in set(vals))
        distinguishes=len({g for _,g in pairs})>=2
        if pure and distinguishes:
            reasons.append(f'field {key}: {dv} values each map to one gold (value->gold)')
    # 2) exact numeric/string copy of a gold label value (score or choice)
    for key,pairs in colvals.items():
        if len(pairs)<n: continue
        match=sum(1 for (v,_),r in zip(pairs,rows) if str(v)==str(gnum(r)) or str(v)==str(gold(r)))
        if match==n and len(set(v for v,_ in pairs))>=2:
            reasons.append(f'field {key}: equals a gold label value on every row')
    # 3) decoded (base64) value predicts gold
    b64cols=collections.defaultdict(list)
    for r in rows:
        for path,val in candidate_fields(r):
            if isinstance(val,str) and re.fullmatch(r'[A-Za-z0-9+/=]{4,}',val):
                try: dec=base64.b64decode(val).decode()
                except Exception: continue
                b64cols[re.sub(r'/\d+','/[]',path)].append((dec,gold(r)))
    for key,pairs in b64cols.items():
        if len(pairs)<n: continue
        dv=len(set(v for v,_ in pairs))
        if 2<=dv<n and all(len({g for v2,g in pairs if v2==v})==1 for v in set(v for v,_ in pairs)):
            reasons.append(f'field {key}: base64-decoded value predicts gold')
    # 4) message JSON suffix tokens predict gold
    sufcol=collections.defaultdict(list)
    for r in rows:
        for tag,tok in msg_suffix_tokens(r): sufcol[tag].append((tok,gold(r)))
    for key,pairs in sufcol.items():
        if len(pairs)==n:
            dv=len(set(v for v,_ in pairs))
            if 2<=dv<n and all(len({g for v2,g in pairs if v2==v})==1 for v in set(v for v,_ in pairs)):
                reasons.append('message-suffix JSON token predicts gold')
    # 5) sidecar maps id->gold
    if sidecar:
        byid={s['id']:s for s in sidecar}
        if all(r['id'] in byid for r in rows):
            vals=[(byid[r['id']].get('action'),gold(r)) for r in rows]
            dv=len(set(v for v,_ in vals))
            if 2<=dv and all(len({g for v2,g in vals if v2==v})==1 for v in set(v for v,_ in vals)) and dv>=2 and dv<n:
                reasons.append('sidecar id->gold mapping leaks labels')
    return reasons

res={}
bad=[]
for d in sorted(glob.glob(f'{ROOT}/packs/*')):
    cid=os.path.basename(d)
    rows=[json.loads(l) for l in open(f'{d}/curated_pack_v2.jsonl',encoding='utf-8',newline='\n')]
    sc=None
    if os.path.exists(f'{d}/labels_sidecar.jsonl'): sc=[json.loads(l) for l in open(f'{d}/labels_sidecar.jsonl',encoding='utf-8',newline='\n')]
    reasons=detect(rows,sc)
    verdict='refuse' if reasons else 'accept'
    man=json.load(open(f'{ROOT}/MANIFEST.json',encoding='utf-8'))
    res[cid]=(verdict,reasons)
mani=json.load(open(f'{ROOT}/MANIFEST.json',encoding='utf-8'))
expect={c['case']:c['expect'] for c in mani['case_list']}
ok=0
for cid,(verdict,reasons) in sorted(res.items()):
    exp=expect[cid]
    flag='' if verdict==exp else '  <<< MISMATCH'
    if verdict!=exp: bad.append((cid,exp,verdict,reasons))
    else: ok+=1
print(f'OK {ok}/{len(res)}')
for cid,exp,verdict,reasons in bad:
    print('MISMATCH',cid,'expect',exp,'got',verdict,'::',reasons[:2])

if len(sys.argv)>2:
    json.dump({c:{'verdict':v,'reasons':r} for c,(v,r) in sorted(res.items())},open(sys.argv[2],'w',encoding='utf-8',newline='\n'),indent=1,ensure_ascii=False)
print('verdicts',dict(collections.Counter(v for v,_ in res.values())),'expect',dict(collections.Counter(expect.values())))
