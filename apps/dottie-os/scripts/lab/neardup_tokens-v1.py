"""Mill near-dup tokenizer v1 (message-only). Standalone, stdlib only, no I/O. Shared by Mill (pack builds, N safe-side screen) and, once
Forge pins it, the #90 gate. Golden vectors: neardup_tokens-v1.golden.json (verify with: python3 neardup_tokens-v1.py --verify).

Input is ONLY a row's state.message string (never JSON keys, questions, labels or ids).
1. message_text(message): if the message is an L3 tool call 'tool=shell; detail=<json>' whose JSON has a string 'command' (or 'cmd'),
   the text is that command string; otherwise the whole message. (The 'tool=shell; detail=' boilerplate is not tokenized.)
2. normalize(text): unicodedata NFKC -> delete every code point of Unicode category Cf (format chars: ZWSP U+200B, ZWJ, BOM U+FEFF, soft hyphen
   U+00AD, bidi marks ...) -> str.casefold() -> every maximal run of whitespace (str.split() semantics, incl. \\r \\n \\t \\v \\f U+2028 U+2029 U+0085
   and NFKC-mapped spaces) replaced by ONE ASCII space -> strip leading/trailing space.
3. tokens(text): the SET of all contiguous 5-code-point substrings of normalize(text) (character 5-shingles). If the normalized text is shorter
   than 5 code points, the set is {normalized_text} (one token, possibly the empty string).
4. jaccard(a,b) = |A & B| / |A | B| on the token sets (0.0 if both empty). Near-dup iff jaccard >= 0.5.
Also: residue(key) = int(sha256(key.encode('ascii')).hexdigest(),16) % 10 (N partition residues {0,5}); key = RAW source.uuid (no strip, no
case-fold) or, for uuid-less rows, the lowercase 64-hex content_uuid."""
import hashlib,json,re,sys,unicodedata
VERSION='neardup_tokens-v1'; K=5; THRESHOLD=0.5; N_MOD=10; N_RESIDUES=(0,5)
_PFX='tool=shell; detail='
def message_text(message):
    if not isinstance(message,str): raise TypeError('state.message must be str')
    if message.startswith(_PFX):
        try: d=json.loads(message[len(_PFX):])
        except ValueError: return message
        if isinstance(d,dict):
            c=d.get('command') if isinstance(d.get('command'),str) else d.get('cmd')
            if isinstance(c,str): return c
    return message
def normalize(text):
    s=unicodedata.normalize('NFKC',text)
    s=''.join(ch for ch in s if unicodedata.category(ch)!='Cf')
    return ' '.join(s.casefold().split())
def tokens(text):
    s=normalize(text)
    return frozenset([s]) if len(s)<K else frozenset(s[i:i+K] for i in range(len(s)-K+1))
def message_tokens(message): return tokens(message_text(message))
def jaccard(a,b):
    u=a|b
    return len(a&b)/len(u) if u else 0.0
def near_dup(m1,m2): return jaccard(message_tokens(m1),message_tokens(m2))>=THRESHOLD
def residue(key): return int(hashlib.sha256(key.encode('ascii')).hexdigest(),16)%N_MOD
def in_partition(key): return residue(key) in N_RESIDUES
def token_digest(ts): return hashlib.sha256('\n'.join(sorted(ts)).encode('utf-8')).hexdigest()
def verify(path):
    g=json.load(open(path,encoding='utf-8')); bad=[]
    for v in g['residue_vectors']:
        if residue(v['key'])!=v['residue']: bad.append(('residue',v))
    for v in g['normalize_vectors']:
        if normalize(v['text'])!=v['normalized']: bad.append(('normalize',v))
    for v in g['token_vectors']:
        t=message_tokens(v['message'])
        if len(t)!=v['n_tokens'] or token_digest(t)!=v['token_set_sha256']: bad.append(('tokens',v))
    for v in g['jaccard_vectors']:
        if round(jaccard(message_tokens(v['a']),message_tokens(v['b'])),6)!=v['jaccard'] or near_dup(v['a'],v['b'])!=v['near_dup']: bad.append(('jaccard',v))
    return bad
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--verify':
        import os; p=sys.argv[2] if len(sys.argv)>2 else os.path.join(os.path.dirname(os.path.abspath(__file__)),'neardup_tokens-v1.golden.json')
        b=verify(p); print('OK' if not b else b); sys.exit(1 if b else 0)
