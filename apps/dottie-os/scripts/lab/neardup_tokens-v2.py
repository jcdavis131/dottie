"""Mill near-dup tokenizer v2 (row extractor + confusable-hardened normalize). Standalone, stdlib only, no I/O except --verify / --diff-v1.
Replaces neardup_tokens-v1.py (sha 50d5015a...a173) for the #90 gate once Forge pins it. Golden: neardup_tokens-v2.golden.json
(python3 neardup_tokens-v2.py --verify). Fixes Critic #90@6f4cd833 B6-NOMSG and the combining-mark / Cyrillic+Greek homoglyph / filler evasions.

1. extract_text(row) -> str or NO_TEXT. Text PARTS are collected from a pack row in this EXACT order (absent / wrong-typed fields are skipped):
     a. row.state.message      b. row.state.text      c. row.state.messages
     d. row.state.prompt, row.state.input, row.state.instruction, row.state.question      (PROMPT_FIELDS, in that order)
     e. row.prompt, row.input, row.instruction, row.question                               (top level, same order)
   Each field value is expanded by parts(v): str -> [message_text(v)]; list -> parts of each item in list order; dict -> parts(v['text']) then
   parts(v['content']) (TEXT_KEYS, OpenAI/Anthropic content-part and {role,content} message shapes); anything else (None, numbers, bool) -> [].
   Nesting deeper than MAX_DEPTH=8 is ignored. message_text is v1's: a 'tool=shell; detail=<json>' string with a str 'command' (or 'cmd')
   yields that command. Parts whose normalize() is '' are dropped; the rest are joined with '\\n' (normalizes to one space). No dedup.
   If no part survives -> NO_TEXT. Not read, ever: ids, source.*, labels, questions, criteria, consent, meta, JSON keys.
   A row whose only text is state.message (str) gives exactly v1's text, so differences vs v1 come only from step 2.
2. normalize(text), in order: NFKC -> NFKD -> delete Mn/Me (combining marks) -> NFC -> delete every Cf (ZWSP U+200B, ZWNJ/ZWJ, WJ U+2060,
   BOM U+FEFF, soft hyphen U+00AD, bidi controls, tags U+E0000.. ...), every Cc that is not whitespace (NUL, ESC, DEL ...), and the FILLERS set
   (U+115F U+1160 U+3164 U+FFA0 U+2800 U+17B4 U+17B5 U+180E U+2062-2064 U+034F U+FE00-FE0F) -> fold CONFUSABLES (pinned table below; keys are
   Cyrillic/Greek/Armenian/Latin-extended lookalikes of both cases, values lowercase ASCII) -> str.casefold() -> fold CONFUSABLES again (catches
   Greek/Cyrillic produced by casefold, e.g. final sigma) -> delete Mn/Me again -> every Zs/Zl/Zp char becomes ' ' -> str.split() whitespace
   runs (incl. \\t \\n \\r \\v \\f \\x1c-\\x1f U+0085 U+2028 U+2029 NBSP U+1680 U+3000) collapse to ONE ASCII space -> strip.
3. tokens(text): UNCHANGED from v1: the SET of 5-code-point substrings of normalize(text); shorter non-empty text -> {text}.
   CHANGE: an empty normalized text returns NO_TEXT (v1 returned {''}). jaccard / near_dup UNCHANGED (|A&B|/|A|B|, near-dup iff >= 0.5) except
   they raise NoTextError on NO_TEXT or an empty set instead of returning 0.0 / silently skipping.
4. NO_TEXT is a singleton sentinel. Gates MUST test `toks is NO_TEXT` and REFUSE the row (fail closed). bool()/len()/iter() on it raise
   NoTextError, so a legacy `if cand_tokens:` crashes instead of skipping. A fingerprint file with an empty token list must also be refused.
residue / in_partition / token_digest are byte-identical to v1. No hash() / set iteration order is used in any output (PYTHONHASHSEED-free)."""
import hashlib,json,sys,unicodedata
VERSION='neardup_tokens-v2'; K=5; THRESHOLD=0.5; N_MOD=10; N_RESIDUES=(0,5); MAX_DEPTH=8
PROMPT_FIELDS=('prompt','input','instruction','question'); TEXT_KEYS=('text','content')
_PFX='tool=shell; detail='
class NoTextError(ValueError): pass
class _NoText(object):
    __slots__=()
    def __repr__(self): return 'NO_TEXT'
    def _r(self,*a): raise NoTextError('NO_TEXT: row has no tokenizable text; gate must refuse')
    __bool__=__len__=__iter__=__contains__=_r
NO_TEXT=_NoText()
FILLERS=frozenset([0x115F,0x1160,0x3164,0xFFA0,0x2800,0x17B4,0x17B5,0x180E,0x2062,0x2063,0x2064,0x034F]+list(range(0xFE00,0xFE10)))
# Pinned confusable table (src -> lowercase Latin). Edit = new version.
_CONF_PAIRS=(
 # Cyrillic lowercase
 'а a','в b','е e','ё e','һ h','і i','ї i','ј j','к k','ӏ l','м m','н h','о o','р p','с c','т t','у y','ў y','ү y','х x','ѕ s','ԁ d',
 'ԛ q','ԝ w','ѵ v','ь b','г r','п n','ɡ g','ԍ g','ꙇ i','ԃ d',
 # Cyrillic uppercase
 'А a','В b','Е e','Ё e','Һ h','І i','Ї i','Ј j','К k','Ӏ l','М m','Н h','О o','Р p','С c','Т t','У y','Ү y','Х x','Ѕ s','Ԁ d',
 'Ԛ q','Ԝ w','Ѵ v','Ь b','Ԍ g',
 # Greek lowercase
 'α a','β b','γ y','ε e','η n','ι i','κ k','ν v','ο o','ρ p','σ o','ς c','τ t','υ u','χ x','ϲ c','ϳ j','μ u','ω w','ϱ p','ϰ k',
 # Greek uppercase
 'Α a','Β b','Ε e','Ζ z','Η h','Ι i','Κ k','Μ m','Ν n','Ο o','Ρ p','Τ t','Υ y','Χ x','Ϲ c','Ϳ j',
 # Armenian / Latin extended
 'օ o','ս u','ց g','հ h','ո n','ı i','ȷ j','ɑ a','ɩ i','ʏ y','ɪ i','ᴏ o','ʀ r','ꜱ s','ᴄ c','ᴠ v','ᴡ w','ᴢ z',
)
CONFUSABLES={ord(p[0]):p[2] for p in _CONF_PAIRS}
assert len(CONFUSABLES)==len(_CONF_PAIRS)
def _strip_marks(s): return ''.join(ch for ch in s if unicodedata.category(ch) not in ('Mn','Me'))
def _keep(ch):
    c=unicodedata.category(ch)
    if c=='Cf' or ord(ch) in FILLERS: return False
    if c=='Cc' and not ch.isspace(): return False
    return True
def message_text(message):
    if not isinstance(message,str): raise TypeError('message must be str')
    if message.startswith(_PFX):
        try: d=json.loads(message[len(_PFX):])
        except ValueError: return message
        if isinstance(d,dict):
            c=d.get('command') if isinstance(d.get('command'),str) else d.get('cmd')
            if isinstance(c,str): return c
    return message
def normalize(text):
    s=unicodedata.normalize('NFKC',text)
    s=unicodedata.normalize('NFC',_strip_marks(unicodedata.normalize('NFKD',s)))
    s=''.join(ch for ch in s if _keep(ch))
    s=s.translate(CONFUSABLES).casefold().translate(CONFUSABLES)
    s=_strip_marks(s)
    s=''.join(' ' if unicodedata.category(ch) in ('Zs','Zl','Zp') else ch for ch in s)
    return ' '.join(s.split())
def parts(v,depth=0):
    if depth>MAX_DEPTH: return []
    if isinstance(v,str): return [message_text(v)]
    if isinstance(v,list):
        out=[]
        for x in v: out.extend(parts(x,depth+1))
        return out
    if isinstance(v,dict):
        out=[]
        for k in TEXT_KEYS:
            if k in v: out.extend(parts(v[k],depth+1))
        return out
    return []
def extract_parts(row):
    if not isinstance(row,dict): return []
    st=row.get('state'); vals=[]
    if isinstance(st,dict):
        vals+=[st.get('message'),st.get('text'),st.get('messages')]+[st.get(f) for f in PROMPT_FIELDS]
    vals+=[row.get(f) for f in PROMPT_FIELDS]
    out=[]
    for v in vals:
        for p in parts(v):
            if normalize(p): out.append(p)
    return out
def extract_text(row):
    ps=extract_parts(row)
    return '\n'.join(ps) if ps else NO_TEXT
def tokens(text):
    if text is NO_TEXT: return NO_TEXT
    s=normalize(text)
    if not s: return NO_TEXT
    return frozenset([s]) if len(s)<K else frozenset(s[i:i+K] for i in range(len(s)-K+1))
def message_tokens(message):
    """state.message alone (str, or list / content-part dict). Same as v1 for str except ''/blank -> NO_TEXT."""
    if isinstance(message,str): return tokens(message_text(message))
    ps=[p for p in parts(message) if normalize(p)]
    return tokens('\n'.join(ps)) if ps else NO_TEXT
def row_tokens(row): return tokens(extract_text(row))
def _chk(t):
    if t is NO_TEXT: raise NoTextError('NO_TEXT operand: gate must refuse')
    if not isinstance(t,(set,frozenset)) or not t: raise NoTextError('empty/invalid token set: gate must refuse')
def jaccard(a,b):
    _chk(a); _chk(b)
    return len(a&b)/len(a|b)
def near_dup(m1,m2): return jaccard(message_tokens(m1),message_tokens(m2))>=THRESHOLD
def row_near_dup(r1,r2): return jaccard(row_tokens(r1),row_tokens(r2))>=THRESHOLD
def residue(key): return int(hashlib.sha256(key.encode('ascii')).hexdigest(),16)%N_MOD
def in_partition(key): return residue(key) in N_RESIDUES
def token_digest(ts):
    _chk(ts)
    return hashlib.sha256('\n'.join(sorted(ts)).encode('utf-8')).hexdigest()
def _tv(t): return 'NO_TEXT' if t is NO_TEXT else {'n_tokens':len(t),'token_set_sha256':token_digest(t)}
def _jv(a,b):
    try: j=jaccard(a,b)
    except NoTextError: return 'NO_TEXT'
    return {'jaccard':round(j,6),'near_dup':j>=THRESHOLD}
def verify(path):
    g=json.load(open(path,encoding='utf-8')); bad=[]
    if g.get('version')!=VERSION: bad.append(('version',g.get('version')))
    for v in g['residue_vectors']:
        if residue(v['key'])!=v['residue'] or ('in_partition' in v and in_partition(v['key'])!=v['in_partition']): bad.append(('residue',v))
    for v in g['normalize_vectors']:
        if normalize(v['text'])!=v['normalized']: bad.append(('normalize',v))
    for v in g['token_vectors']:
        if _tv(message_tokens(v['message']))!=v['expect']: bad.append(('tokens',v))
    for v in g['row_vectors']:
        e=extract_text(v['row']); e='NO_TEXT' if e is NO_TEXT else e
        if e!=v['text'] or _tv(row_tokens(v['row']))!=v['expect']: bad.append(('row',v))
    for v in g['jaccard_vectors']:
        if _jv(message_tokens(v['a']),message_tokens(v['b']))!=v['expect']: bad.append(('jaccard',v))
    for v in g['row_jaccard_vectors']:
        if _jv(row_tokens(v['a']),row_tokens(v['b']))!=v['expect']: bad.append(('row_jaccard',v))
    for name,fn in (('bool',bool),('len',len),('iter',iter)):
        try: fn(NO_TEXT); bad.append(('no_text_'+name,'did not raise'))
        except NoTextError: pass
    for a in (frozenset(),NO_TEXT):
        try: jaccard(a,frozenset(['abcde'])); bad.append(('jaccard_refuse',repr(a)))
        except NoTextError: pass
    return bad
if __name__=='__main__':
    import os
    if len(sys.argv)>1 and sys.argv[1]=='--verify':
        p=sys.argv[2] if len(sys.argv)>2 else os.path.join(os.path.dirname(os.path.abspath(__file__)),'neardup_tokens-v2.golden.json')
        b=verify(p); print('OK' if not b else b); sys.exit(1 if b else 0)
