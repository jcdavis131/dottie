import argparse
# leak-gate fixture generator, canonical v3 (Mill). stdlib-only.
# = Mill gen.py 5d7244a6 + Forge PR#89 CLI args/pinned timestamps (3097e27b) + S1 (explicit utf-8, newline='\n' on all I/O)
#   + accepts a {'synthetic':true,'rows':[...]} source wrapper; records source/gen sha256 in MANIFEST.
import json,hashlib,os,base64,copy,collections
parser=argparse.ArgumentParser()
parser.add_argument('--src',required=True)
parser.add_argument('--out',required=True)
parser.add_argument('--ts',default='20261018-230457')
parser.add_argument('--produced-at',default='2026-10-18T23:04:57-05:00')
_ARGS=parser.parse_args()
SRC=_ARGS.src
ts=_ARGS.ts
produced_at=_ARGS.produced_at
ROOT=_ARGS.out
with open(SRC,'r',encoding='utf-8',newline='\n') as _fh: _src_text=_fh.read()
_SRC_SHA=hashlib.sha256(_src_text.encode('utf-8')).hexdigest()
SYNTH=False
if SRC.endswith('.json'):
    _loaded=json.loads(_src_text)
    if isinstance(_loaded,dict) and isinstance(_loaded.get('rows'),list):
        SYNTH=bool(_loaded.get('synthetic')); rows=_loaded['rows']
    else:
        rows=_loaded if isinstance(_loaded,list) else [_loaded]
else:
    rows=[json.loads(l) for l in _src_text.splitlines() if l.strip()]
def has_choice(r): return any(isinstance(v,dict) and v.get('type')=='choice' for v in r['labels'].values())
def gold(r):
    if r['tier']=='L3': return r['labels']['action']['choice']
    return r['labels']['domain']['choice']
def gnum(r): return r['labels']['safe']['noul']
L3=[r for r in rows if r['tier']=='L3']
L2d=[r for r in rows if r['tier']=='L2' and 'domain' in r['labels']]
def take(lst,pred,n):
    out=[r for r in sorted(lst,key=lambda x:x['id']) if pred(r)][:n]; return out
BASE=[]
BASE+=take(L3,lambda r:gold(r)=='execute',5)
BASE+=take(L3,lambda r:gold(r)=='halt',4)
BASE+=take(L3,lambda r:gold(r)=='escalate',1)
BASE+=take(L2d,lambda r:gold(r)=='tool',3)
BASE+=take(L2d,lambda r:gold(r)=='web',1)
BASE+=take(L2d,lambda r:gold(r)=='algo',1)
BASE+=take(L2d,lambda r:gold(r)=='other',1)
assert len(BASE)==16,len(BASE)
GOLDS=sorted(set(gold(r) for r in BASE))
print('BASE',len(BASE),'golds',collections.Counter(gold(r) for r in BASE))

# ---- helpers ----
def set_path(obj,path,val):
    cur=obj
    for k in path[:-1]:
        cur=cur.setdefault(k,{})
    cur[path[-1]]=val
def bij(prefix,g): return prefix+str(g)          # bijective fn of gold -> perfect predictor
CONST='review'                                     # non-label constant -> zero correlation

# transforms: fn(row_copy, g, i, leaky) mutate in place; may return sidecar entry
def mk_keyval(path, valfn):
    def f(r,g,i,leaky):
        set_path(r, path, valfn(g) if leaky else CONST)
    return f
def t_message_suffix(r,g,i,leaky):
    if leaky:
        r['state']['message']+=' // '+json.dumps({"halt_class":bij("cls_",g)},ensure_ascii=False)
    else:
        r['state']['message']+=' // checked'
def t_json_in_extra(r,g,i,leaky):
    r['state']['meta']['extra']=json.dumps({"risk_hint": g if leaky else CONST},ensure_ascii=False)
def t_numeric_p(r,g,i,leaky):
    r['state']['meta']['p']= gnum(r) if leaky else 0.5
def t_base64(r,g,i,leaky):
    w=g if leaky else CONST
    r['state']['meta']['code']=base64.b64encode(w.encode('utf-8')).decode()
# unicode keys
CY='r\u0456sk_h\u0456nt'           # cyrillic i (U+0456)
FW='\uff52\uff49\uff53\uff4b\uff3f\uff48\uff49\uff4e\uff54'  # fullwidth risk_hint
ZWJ='risk_\u200dhint'              # zero-width joiner inside key

# REFUSE specs: (case_key, path/desc, transform, note)
REF=[
 ('meta_risk_hint',      mk_keyval(['state','meta','risk_hint'],lambda g:g),            "exact key state.meta.risk_hint = gold action/domain (classic leak)"),
 ('meta_halt_class',     mk_keyval(['state','meta','halt_class'],lambda g:bij("cls_",g)),"state.meta.halt_class bijective to gold -> predicts label"),
 ('meta_provenance',     mk_keyval(['state','meta','provenance'],lambda g:bij("prov_",g)),"state.meta.provenance encodes gold"),
 ('meta_agent_config',   mk_keyval(['state','meta','agent_config'],lambda g:bij("cfg_",g)),"state.meta.agent_config value tracks gold"),
 ('state_category',      mk_keyval(['state','category'],lambda g:g),                    "state.category = gold (one level above meta)"),
 ('state_risk_hint',     mk_keyval(['state','risk_hint'],lambda g:g),                   "risk_hint directly under state"),
 ('deep_nesting',        mk_keyval(['state','meta','audit','trace','risk_hint'],lambda g:g),"deeply nested state.meta.audit.trace.risk_hint = gold"),
 ('toplevel_risk_hint',  mk_keyval(['risk_hint'],lambda g:g),                           "row top-level risk_hint = gold (leak ONLY if top-level is model input; included+labeled)"),
 ('key_Risk_Hint',       mk_keyval(['state','meta','Risk_Hint'],lambda g:g),            "case variant key Risk_Hint = gold"),
 ('key_RISK_DASH_HINT',  mk_keyval(['state','meta','RISK-HINT'],lambda g:g),            "separator variant RISK-HINT = gold"),
 ('key_riskHint',        mk_keyval(['state','meta','riskHint'],lambda g:g),             "camelCase riskHint = gold"),
 ('key_risk_dot_hint',   mk_keyval(['state','meta','risk.hint'],lambda g:g),            "dotted key 'risk.hint' = gold"),
 ('key_space_risk_hint', mk_keyval(['state','meta',' risk_hint'],lambda g:g),           "leading-space key ' risk_hint' = gold"),
 ('key_risk__hint',      mk_keyval(['state','meta','risk__hint'],lambda g:g),           "double-underscore risk__hint = gold"),
 ('unicode_cyrillic',    mk_keyval(['state','meta',CY],lambda g:g),                     "Cyrillic-lookalike key (U+0456) = gold"),
 ('unicode_fullwidth',   mk_keyval(['state','meta',FW],lambda g:g),                     "fullwidth-lookalike key = gold"),
 ('unicode_zwj',         mk_keyval(['state','meta',ZWJ],lambda g:g),                    "zero-width-joiner inside key = gold"),
 ('json_in_meta_extra',  t_json_in_extra,                                              "label smuggled as JSON string in state.meta.extra"),
 ('json_in_message_suffix',t_message_suffix,                                           "label JSON appended to message tail (message-channel leak)"),
 ('newkey_meta_hint',    mk_keyval(['state','meta','hint'],lambda g:g),                 "innocuous NEW key meta.hint = gold for every row"),
 ('newkey_meta_verdict', mk_keyval(['state','meta','verdict'],lambda g:g),             "innocuous NEW key meta.verdict = gold"),
 ('newkey_meta_tag',     mk_keyval(['state','meta','tag'],lambda g:g),                  "innocuous NEW key meta.tag = gold"),
 ('newkey_meta_p_numeric',t_numeric_p,                                                 "numeric meta.p = labels.safe.noul (gold score copied)"),
 ('base64_label',        t_base64,                                                     "base64(gold) in meta.code, aligned with label"),
 ('sidecar_labels',      None,                                                         "sidecar file in pack dir maps id->gold (labels leaked beside rows)"),
]

# over-refusal ACCEPT-only specs
def c_label_words(r,g,i,leaky):
    # label words in message, assigned by position, independent of gold
    words=['execute','halt','accept','escalate']
    r['state']['message']+=' && echo '+words[i%len(words)]+'  # grep halt log.txt'
def c_status_mixed(r,g,i,leaky):
    words=['execute','halt','escalate','accept']
    r['state']['meta']['status']=words[i%len(words)]   # mixed, NOT aligned to gold
def c_lang_tool(r,g,i,leaky):
    r['state']['meta']['lang']='py' if 'import' in r['state']['message'] else 'sh'
    r['state']['meta'].setdefault('tool','shell')
def c_substring(r,g,i,leaky):
    r['state']['meta']['categorical_features']=['len','depth']   # key merely CONTAINS 'categor'
    r['state']['message']+='  # categorical_features=none'
def c_numeric_unc(r,g,i,leaky):
    r['state']['meta']['latency_ms']=(i*37+11)%97                # uncorrelated with gold/score
CLEAN=[
 ('clean_base',          None,          ("untouched base rows; must ACCEPT (negative control)" if SYNTH else "untouched real rows; must ACCEPT (negative control)")),
 ('clean_label_word_in_command',c_label_words,"label words appear inside command text, uncorrelated with gold -> ACCEPT"),
 ('clean_status_mixed',  c_status_mixed,"meta.status holds label words but MIXED vs gold across pack -> ACCEPT"),
 ('clean_meta_lang_tool',c_lang_tool,   "normal meta.lang/meta.tool, not label-predictive -> ACCEPT"),
 ('clean_substring_key', c_substring,   "key name contains a leak substring ('categor') but value is not a label -> ACCEPT"),
 ('clean_numeric_uncorrelated',c_numeric_unc,"numeric meta field uncorrelated with scores -> ACCEPT"),
]

PKDIR=f'{ROOT}/packs'; os.makedirs(PKDIR)
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def split_rows(rs):
    tr=[];ho=[]
    for r in rs:
        h=int(hashlib.sha256(r['id'].encode('utf-8')).hexdigest(),16)
        (ho if h%4==0 else tr).append(r)
    if not ho: ho=[tr.pop()]
    if not tr: tr=[ho.pop()]
    return tr,ho
def write_pack(case_id, rs, sidecar=None):
    d=f'{PKDIR}/{case_id}'; os.makedirs(d,exist_ok=True)
    tr,ho=split_rows(rs)
    def dump(name,objs):
        b=''.join(json.dumps(o,ensure_ascii=False)+'\n' for o in objs).encode('utf-8')
        open(f'{d}/{name}','wb').write(b); return sha_bytes(b)
    sp=dump('curated_pack_v2.jsonl',rs); st=dump('curated_pack_v2_train.jsonl',tr); sh=dump('curated_pack_v2_holdout.jsonl',ho)
    man={'pack_id':f'leakfix-{case_id}','rows':len(rs),'train_rows':len(tr),'holdout_rows':len(ho),
         'sha256_pack':sp,'sha256_train':st,'sha256_holdout':sh,'eval_only':True,'not_for_train':True,
         'champion_touched':False,'ft_kicked':False,'live_gate_touched':False}
    if sidecar is not None:
        sb=''.join(json.dumps(o,ensure_ascii=False)+'\n' for o in sidecar).encode('utf-8')
        open(f'{d}/labels_sidecar.jsonl','wb').write(sb); man['sha256_sidecar']=sha_bytes(sb)
    with open(f'{d}/MANIFEST.json','w',encoding='utf-8',newline='\n') as _fh: json.dump(man,_fh,indent=1,ensure_ascii=False)
    return {'pack':sp,'train':st,'holdout':sh,**({'sidecar':man['sha256_sidecar']} if sidecar is not None else {})}

fixtures=[]           # annotated rows for fixtures.jsonl
pack_shas={}          # case_id -> shas
counts=collections.Counter()
caselist=[]           # (case_id, expect, twin_of, note)

def build_case(case_id, expect, twin_of, note, transform, leaky, sidecar_mode=False):
    rs=[]
    sidecar=None
    if sidecar_mode:
        sidecar=[]
    for i,base in enumerate(BASE):
        r=copy.deepcopy(base); g=gold(base)
        if sidecar_mode:
            sidecar.append({'id':r['id'],'action': g if leaky else 'mill'})
        elif transform is not None:
            transform(r,g,i,leaky)
        rs.append(r)
    pack_shas[case_id]=write_pack(case_id,rs,sidecar)
    for r in rs:
        fr=copy.deepcopy(r); fr['fixture']={'case':case_id,'expect':expect,'twin_of':twin_of,'note':note}
        fixtures.append(fr)
    counts[case_id]=len(rs)
    caselist.append((case_id,expect,twin_of,note))

# refuse + twin
for key,tf,note in REF:
    rc=f'leak_{key}'; tc=f'twin_{key}'
    sm=(key=='sidecar_labels')
    build_case(rc,'refuse',tc,note,tf,True,sidecar_mode=sm)
    build_case(tc,'accept',rc,'clean twin of '+rc+': same field/shape, value NOT label-correlated (constant) -> ACCEPT',tf,False,sidecar_mode=sm)
# clean over-refusal
for key,tf,note in CLEAN:
    build_case(key,'accept',None,note,tf,False)

# fixtures.jsonl + README + MANIFEST
fx=''.join(json.dumps(o,ensure_ascii=False)+'\n' for o in fixtures).encode('utf-8')
open(f'{ROOT}/fixtures.jsonl','wb').write(fx)
# README
lines=["# Leak-gate adversarial fixtures (build-against set for Forge #85 kick() label-leak gate)","",
 "Each mini-pack under packs/<case_id>/ is a runnable curated_pack_v2 (pack/train/holdout[/sidecar]).",
 "A leak = a NON-message field whose VALUE predicts the gold label (action for L3, domain for L2) across the whole pack.",
 "Detection must be VALUE-based and PACK-level: refuse when a field's values predict gold across rows; accept when the",
 "same key exists but its values are constant/mixed/uncorrelated. Single-row coincidences must ACCEPT.","",
 (f"Base rows: 16 SYNTHETIC placeholder rows from {os.path.basename(SRC)} (no real commands/code/uuids; golds: {dict(collections.Counter(gold(r) for r in BASE))})." if SYNTH else
  f"Base rows: 16 real rows from ultradata_l3halt_lenmatch_20261018-224530 (golds: {dict(collections.Counter(gold(r) for r in BASE))})."),"",
 "## Cases"]
for cid,exp,tw,note in caselist:
    lines.append(f"- `{cid}` [{exp}]"+(f" (twin_of {tw})" if tw else "")+f": {note}")
lines+=["","## Why value-based (not key-name) detection is required",
 "- Key-name blocklists fail on case/separator variants (Risk_Hint, RISK-HINT, riskHint, risk.hint, ' risk_hint', risk__hint),",
 "  unicode look-alike keys (Cyrillic U+0456, fullwidth, zero-width-joiner), and brand-new innocuous keys (hint/verdict/tag).",
 "- They also false-positive on legitimate fields whose NAME contains a trigger substring (categorical_features) or on label",
 "  WORDS that legitimately occur in command text (echo execute, grep halt). Only label-correlation across the pack separates",
 "  a real leak (twin_* packs keep the suspicious key with a non-predictive value and must ACCEPT).",
 "- Leaks also hide in string values (JSON-in-string, base64), in numeric copies of the gold score (meta.p == safe.noul),",
 "  in a message suffix, and in a companion sidecar file keyed by id -> all must be caught by comparing values to gold."]
readme=('\n'.join(lines)+'\n').encode('utf-8'); open(f'{ROOT}/README.md','wb').write(readme)

man={'fixture_set_id':(f'leakgate_fixtures_synth-{ts}' if SYNTH else f'leakgate_fixtures-{ts}'),'produced_at':produced_at,
 'producer':'Mill (box; data only under /workspace/packs/)',
 'source_pack':(os.path.basename(SRC) if SYNTH else 'ultradata_l3halt_lenmatch_20261018-224530/curated_pack_v2.jsonl'),
 'base_rows':len(BASE),'base_gold_counts':dict(collections.Counter(gold(r) for r in BASE)),
 'gold_definition':'L3: labels.action.choice ; L2: labels.domain.choice ; numeric gold: labels.safe.noul',
 'total_fixture_rows':len(fixtures),'cases':len(caselist),
 'expect_counts_cases':{'refuse':sum(1 for c in caselist if c[1]=='refuse'),'accept':sum(1 for c in caselist if c[1]=='accept')},
 'expect_counts_rows':{'refuse':sum(len(BASE) for c in caselist if c[1]=='refuse'),'accept':sum(len(BASE) for c in caselist if c[1]=='accept')},
 'row_counts_by_case':{cid:counts[cid] for cid,_,_,_ in caselist},
 'case_list':[{'case':cid,'expect':exp,'twin_of':tw,'note':note} for cid,exp,tw,note in caselist],
 'mini_pack_sha256':pack_shas,
 'sha256_fixtures_jsonl':sha_bytes(fx),'sha256_readme_md':sha_bytes(readme),
 'not_for_train':True,'eval_only':True,'champion_touched':False,'ft_kicked':False,'live_gate_touched':False,
 'scope':'open adversarial build-against set; Critic holds a separate held-out set'}
if SYNTH: man.update({'source_synthetic':True,'sha256_source':_SRC_SHA})  # absent for real-source builds (keeps 888645 byte-identical)
with open(f'{ROOT}/MANIFEST.json','w',encoding='utf-8',newline='\n') as _fh: json.dump(man,_fh,indent=1,ensure_ascii=False)
print('ROOT',ROOT)
print('cases',len(caselist),'rows',len(fixtures))
print('expect cases',man['expect_counts_cases'])
print('sha fixtures',man['sha256_fixtures_jsonl'])
print('sha readme',man['sha256_readme_md'])
