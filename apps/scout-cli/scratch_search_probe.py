"""throwaway probe — verify ranking/query behavior before asserting it in tests"""
from pathlib import Path
import tempfile, os

from bigbang.core import search

tmp = Path(tempfile.mkdtemp())
corpus = tmp / "corpus"
corpus.mkdir()

(corpus / "dense.md").write_text("ranking ranking ranking\n", encoding="utf-8")
(corpus / "sparse.md").write_text("ranking " + ("filler word here " * 60) + "\n", encoding="utf-8")
(corpus / "noise1.md").write_text("nothing relevant at all\n", encoding="utf-8")
(corpus / "noise2.md").write_text("also nothing relevant\n", encoding="utf-8")
(corpus / "tokenizer-guide.md").write_text("scoring notes and other content\n", encoding="utf-8")
(corpus / "body.md").write_text("the tokenizer is described here in one place\n", encoding="utf-8")
(corpus / "phrase-a.md").write_text("alpha beta gamma\n", encoding="utf-8")
(corpus / "phrase-b.md").write_text("beta alpha gamma\n", encoding="utf-8")
(corpus / "accent.md").write_text("le café est chaud\n", encoding="utf-8")
(corpus / "ops.md").write_text("alpha and beta together\n", encoding="utf-8")

conn = search.open_index(":memory:")
res = search.index_paths(conn, [corpus], include=["*.md"], now=1000.0)
print("index:", {k: res[k] for k in ("added", "updated", "unchanged", "removed", "documents")})

def paths(q, **kw):
    r = search.query(conn, q, **kw)
    return [(Path(h["path"]).name, h["score"]) for h in r["hits"]], r["total"]

print("dense-vs-sparse:", paths("ranking"))
print("pathweight-high:", paths("tokenizer", path_weight=5.0, body_weight=1.0))
print("pathweight-low:", paths("tokenizer", path_weight=0.0, body_weight=1.0))
print("phrase:", paths('"alpha beta"'))
print("prefix:", paths("token*"))
print("diacritics cafe:", paths("cafe"))
print("diacritics café:", paths("café"))
print("literal ops:", paths("alpha and beta", literal=True))
try:
    paths("alpha AND")
except ValueError as e:
    print("syntax:", e)
print("subtree filter:", paths("ranking", path_glob=str(corpus)))
print("subtree filter miss:", paths("ranking", path_glob=str(tmp / "other")))
print("snippet:", search.query(conn, "ranking")["hits"][0]["snippet"])
print("pagination:", paths("ranking", limit=1), paths("ranking", limit=1, offset=1))
