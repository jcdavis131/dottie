# Solo personal project, no connection to employer, built with public/free-tier only
"""Dupes — near-duplicate content detector core (openswap #28: Copyscape).

The paid enemy here is the worst shape of SaaS in this whole table: Copyscape's
"premium" plagiarism check works by UPLOADING the text you have not published
yet to someone else's index, per query, per page. This adapter inverts that
completely — the corpus is the local tree, the arithmetic is k-shingling with
hashlib fingerprints, and the manifest disables the network axis entirely, so
"the unpublished draft never left the box" is architectural rather than a ToS
promise. Nothing in this module opens a socket, a file or a subprocess: the
plugin CLI owns the ONE real I/O (reading local files as bytes) and hands this
module `bytes`/`str`, which is why the whole pipeline is unit-testable offline.

The algorithm (Broder's shingling, re-derived in stdlib):
- tokenize: markdown/HTML/plain text -> a lowercase word stream. The markup
  strippers are REUSED from prose #1 (extract_markdown blanks code fences,
  inline code, URLs and tags with a NUL sentinel that no word token can span;
  extract_html skips script/style/code/pre/kbd/samp), so a fenced code block
  cannot be mistaken for recycled prose and there is no second copy of that
  logic to drift. What that does NOT do is strip page chrome: extract_html
  keeps nav/footer/aside text, so a shared nav bar contributes shingles to
  every page that carries it. That is a stated limit, not a silent one — the
  fix is to feed analyze() the article bodies from extract #11 (whose whole job
  is link-density boilerplate removal) instead of raw HTML, which is exactly
  the "corpus sources" extension point below.
- shingle: every contiguous window of `k` tokens -> one blake2b digest over the
  tokens joined by a byte (0x1f) that cannot occur inside a token, so
  ["ab","c"] and ["a","bc"] are different shingles instead of colliding.
  Digests are `digest_bits` wide (64 by default = 16 hex chars); the birthday
  bound at 64 bits is ~5e9 shingles for an even-odds collision, i.e. far past
  any local corpus, and widening it is one config key.
- compare: Jaccard |A n B| / |A u B| for "these two pages are the same page",
  PLUS containment |A n B| / min(|A|,|B|) for "this short draft is a slice of
  that long published page" — the partial-lift case Jaccard structurally
  underweights when lengths differ, and the case a plagiarism checker exists
  for. Both are reported; either can trip a finding.
- cluster: pairs above the gates are union-found into connected components, so
  five recycled variants of one paragraph report as ONE cluster of five and not
  as ten pairs a human has to re-assemble.

Hot path (Carmack): the pairwise comparison never intersects sets. One pass
over the shingle->documents postings index yields the exact shared-shingle
COUNT for every pair that shares at least one shingle, and Jaccard/containment
are pure arithmetic on (shared, |A|, |B|). Pairs sharing nothing are never
visited at all — they cannot clear a positive threshold. `jaccard()` (the set
definition) and `jaccard_from_counts()` (the hot path) are both public and
tested against each other, so the fast path can never quietly diverge from the
definition it claims to implement.

Determinism is a hard requirement (a duplicate report belongs in git next to
the pages it judges, and must diff clean when nothing moved):
- fingerprints come from hashlib, NEVER from builtin hash(), whose seed is
  randomized per process (this repo has already shipped one hash()-as-seed bug)
- document ids are posix-style relative paths, so a report is identical on
  Windows and Linux
- shingle order is first-appearance, pair order is (kind, -similarity, a, b),
  cluster order is (-size, first member), and every list of ids is sorted

Honesty is enforced rather than documented — every reading has EITHER a value
OR a labelled reason, never both and never neither:
- a document too short to shingle gets `errors["shingles"]` naming the token
  count and the bound it missed; it is NEVER compared and NEVER reported as
  0.0 similar
- a document with no extractable words gets no content hash (a sha256 of the
  empty string is not evidence of content)
- an exact-content pair whose documents are both too short to shingle reports
  `similarity: None` with the reason, because no shingle sets exist to compare
- unmeasured documents are surfaced as info-level diagnostics, so "nothing was
  silently skipped" is checkable in the same envelope as the findings

Extension points:
- Thresholds/severities as config: merge_config() overlays a JSON dict onto
  DEFAULT_CONFIG (unknown keys raise rather than being silently ignored, which
  is how a typo'd threshold becomes an invisible pass), so per-surface policy
  needs no code edit.
- Corpus sources: analyze() takes documents as {"id", "text", "fmt"} dicts. Any
  producer works — the plugin walks a tree today; the seo #3 crawl store's page
  bodies and the extract #11 corpus ledger are the same shape.
- Native tier: there is none to prefer. Copyscape is SaaS; fdupes/rdfind/jdupes
  find BYTE-identical files only (they cannot see a reworded paragraph) and
  jscpd is a node code-clone detector, so they are surfaced by the plugin's
  detect and never executed.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from bigbang.core import logs, openswap, prose

# DERIVED from prose #1, never re-listed: extension-list drift between two
# modules that must agree is a known bug class in this repo.
DOC_EXTS = prose.PROSE_EXTS

# Every knob is data (policy-as-config); merge_config() validates an overlay.
DEFAULT_CONFIG: dict[str, Any] = {
    # shingle width in TOKENS. 5 is the classic web-page value: long enough that
    # a shared idiom is not a match, short enough to survive light editing.
    "k": 5,
    # a document with fewer tokens than this is not shingled at all — its
    # similarity would be dominated by sampling noise. Must be >= k.
    "min_tokens": 40,
    # Jaccard gate: "these are the same document"
    "threshold": 0.55,
    # containment gate: "the smaller one is a slice of the larger one"
    "containment_threshold": 0.80,
    "digest_bits": 64,
    # I/O guard consumed by the CLI: files above this are recorded as skipped
    # with the measured size, never silently dropped.
    "max_bytes": 4_000_000,
    "severity": {
        "exact": "error",
        "near": "warning",
        "partial": "suggestion",
        "unmeasured": "info",
    },
}

KINDS = ("exact", "near", "partial")
_KIND_RANK = {k: i for i, k in enumerate(KINDS)}

# separator byte for shingle hashing: 0x1f (US) cannot appear inside a token
# produced by prose.WORD_RE, so token boundaries survive into the digest
_GRAM_SEP = b"\x1f"


# ---- config -----------------------------------------------------------------


def _positive_int(cfg: dict[str, Any], key: str, minimum: int) -> int:
    value = cfg[key]
    # bool is a subclass of int; True is not a shingle width
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an int, got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{key} must be >= {minimum}, got {value}")
    return value


def _unit_float(cfg: dict[str, Any], key: str) -> float:
    value = cfg[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number, got {type(value).__name__}")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{key} must be within 0.0..1.0, got {value}")
    return value


def merge_config(overlay: dict[str, Any] | None = None) -> dict[str, Any]:
    """DEFAULT_CONFIG + an overlay, validated. Unknown keys RAISE.

    A silently-ignored `{"treshold": 0.9}` is a gate that never fires and a
    report nobody can explain, so a typo is a loud error here rather than a
    quiet default.
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in (overlay or {}).items():
        if key not in cfg:
            raise ValueError(
                f"unknown config key {key!r} (known: {', '.join(sorted(cfg))})"
            )
        if key == "severity":
            if not isinstance(value, dict):
                raise ValueError("severity must be a mapping of kind -> severity")
            for kind, sev in value.items():
                if kind not in cfg["severity"]:
                    raise ValueError(
                        f"unknown severity kind {kind!r} "
                        f"(known: {', '.join(sorted(cfg['severity']))})"
                    )
                if sev not in openswap.SEVERITIES:
                    raise ValueError(
                        f"severity[{kind}] must be one of "
                        f"{'|'.join(openswap.SEVERITIES)}, got {sev!r}"
                    )
            cfg["severity"].update(value)
        else:
            cfg[key] = value
    k = _positive_int(cfg, "k", 1)
    bits = _positive_int(cfg, "digest_bits", 32)
    if bits % 8 or bits > 512:
        raise ValueError(f"digest_bits must be a multiple of 8 and <= 512, got {bits}")
    if _positive_int(cfg, "min_tokens", 1) < k:
        raise ValueError(f"min_tokens ({cfg['min_tokens']}) must be >= k ({k})")
    _positive_int(cfg, "max_bytes", 1)
    cfg["threshold"] = _unit_float(cfg, "threshold")
    cfg["containment_threshold"] = _unit_float(cfg, "containment_threshold")
    return cfg


# ---- decoding (pure; the CLI hands us bytes) --------------------------------


def decode_document(data: bytes) -> tuple[str, dict[str, Any]]:
    """bytes -> (text, encoding provenance), REUSING the logs #14 sniffer.

    Drafts on this box are not all UTF-8: the research-loop logs are UTF-16-LE
    with a BOM and PowerShell writes UTF-8 with one, so the encoding is sniffed
    (BOM table, then the BOM-less UTF-16 NUL-position heuristic, then strict
    UTF-8, then latin-1) instead of assumed. Decoding a UTF-16 draft as UTF-8
    yields mojibake, and mojibake shingles match nothing — a silent false
    "no duplicates". `errors="replace"` keeps a damaged tail from voiding a
    whole document; the verdict travels with the text so a surprising token
    count is explainable.
    """
    det = logs.detect_encoding(data[: logs.DETECT_BYTES])
    text = data[det["bom_len"] :].decode(det["encoding"], errors="replace")
    return text, det


def looks_binary(data: bytes) -> bool:
    """True for bytes that are not text: a NUL outside a wide encoding.

    A NUL byte is the classic marker, but UTF-16/32 text is FULL of NULs by
    construction — so the sniffer decides FIRST and a multi-byte code unit
    (unit > 1) settles it as text. Everything else with a NUL in the sampled
    head is a blob: note that a NUL-riddled binary can still be *valid UTF-8*
    (0x00-0x7f all decode), so keying this off the decode result alone would
    admit executables as documents. This is the same trap as reading a
    possibly-binary log with `grep` and no `-a`.
    """
    sample = data[: logs.DETECT_BYTES]
    if not sample:
        return False
    if logs.detect_encoding(sample)["unit"] > 1:
        return False
    return b"\x00" in sample


# ---- tokenizing + shingling -------------------------------------------------


def tokenize(text: str, fmt: str = "text") -> list[str]:
    """Text -> the lowercase word stream that gets shingled.

    Markup stripping is prose #1's (fmt "markdown" | "html" | anything else =
    plain), so code fences, inline code, URLs and tags are blanked with its NUL
    sentinel before tokenizing and can never enter a fingerprint. Tokens are
    prose.WORD_RE's word definition, casefolded — the SAME definition the
    readability scorer uses, so token counts across the family agree.
    """
    if fmt == "markdown":
        lines = prose.extract_markdown(text)
    elif fmt == "html":
        lines = prose.extract_html(text)
    else:
        lines = text.splitlines()
    return [t.casefold() for t in prose.WORD_RE.findall("\n".join(lines))]


def shingle_digest(gram: list[str], *, digest_bits: int = 64) -> str:
    """One k-gram -> a stable hex fingerprint.

    hashlib, never builtin hash(): hash() is seeded per process, so a report
    built with it would differ between two runs of the same command on the same
    files. Tokens are joined by a byte that cannot occur inside a token, so
    ["ab","c"] and ["a","bc"] fingerprint differently.
    """
    if digest_bits % 8 or not 32 <= digest_bits <= 512:
        raise ValueError(
            f"digest_bits must be a multiple of 8 in 32..512, got {digest_bits}"
        )
    payload = _GRAM_SEP.join(t.encode("utf-8") for t in gram)
    return hashlib.blake2b(payload, digest_size=digest_bits // 8).hexdigest()


def shingles(tokens: list[str], k: int, *, digest_bits: int = 64) -> list[str]:
    """Every contiguous k-token window as a digest — unique, first-appearance order.

    Fewer than k tokens yields NO shingles (an empty list), never a whole-document
    pseudo-shingle: a 3-token file is not 100% similar to another 3-token file
    just because both are short. Duplicate windows collapse (the set is what
    Jaccard is defined over) while order stays deterministic for diffing.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if len(tokens) < k:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for i in range(len(tokens) - k + 1):
        d = shingle_digest(tokens[i : i + k], digest_bits=digest_bits)
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def content_hash(tokens: list[str]) -> str | None:
    """sha256 over the NORMALIZED token stream, or None when there are no tokens.

    Normalized identity is the point: two files that differ only in markdown
    wrapping, heading syntax, CRLF vs LF or letter case hash the SAME, which is
    the recycled-copy case fdupes structurally cannot see. No tokens means no
    content — sha256("") is not evidence, so the reading is absent and its
    reason is recorded by the caller.
    """
    if not tokens:
        return None
    return hashlib.sha256(_GRAM_SEP.join(t.encode("utf-8") for t in tokens)).hexdigest()


# ---- fingerprints -----------------------------------------------------------


def fingerprint(
    doc_id: str, text: str, *, fmt: str = "text", config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One document -> its row: facts, readings, and a reason for every absence.

    `errors` is a per-reading map, so a document that is measurable for exact
    duplicates but not for near ones says exactly that instead of being dropped:
      errors["content_sha256"]  no extractable words
      errors["shingles"]        fewer tokens than min_tokens (naming both)
    """
    cfg = config if config is not None else merge_config()
    tokens = tokenize(text, fmt)
    row: dict[str, Any] = {
        "id": doc_id,
        "fmt": fmt,
        "chars": len(text),
        "tokens": len(tokens),
        "content_sha256": None,
        "shingles": [],
        "shingle_count": 0,
        "errors": {},
    }
    digest = content_hash(tokens)
    if digest is None:
        row["errors"]["content_sha256"] = (
            f"no-tokens: no words extracted from {len(text)} chars"
        )
    else:
        row["content_sha256"] = digest
    if len(tokens) < cfg["min_tokens"]:
        row["errors"]["shingles"] = (
            f"too-short: {len(tokens)} tokens < min_tokens {cfg['min_tokens']}"
        )
        return row
    row["shingles"] = shingles(tokens, cfg["k"], digest_bits=cfg["digest_bits"])
    row["shingle_count"] = len(row["shingles"])
    return row


def unreadable_row(doc_id: str, error: str, *, fmt: str = "text") -> dict[str, Any]:
    """A document the CLI could not read -> a row that carries WHY, labelled.

    The failure mode this exists to kill: a duplicate checker that reports
    "0 duplicates" because it silently skipped the files it could not open.
    """
    return {
        "id": doc_id,
        "fmt": fmt,
        "chars": None,
        "tokens": None,
        "content_sha256": None,
        "shingles": [],
        "shingle_count": 0,
        "errors": {"read": error},
    }


def is_measurable(row: dict[str, Any]) -> bool:
    """Does this row have a shingle set to compare? (exact-only rows do not)."""
    return bool(row.get("shingles"))


def fingerprint_documents(
    documents: list[dict[str, Any]], *, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """{"id","text","fmt"} | {"id","error"} dicts -> fingerprint rows, sorted by id.

    Duplicate ids RAISE: two rows claiming one id would make every downstream
    lookup ambiguous and silently drop one of them.
    """
    cfg = config if config is not None else merge_config()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in documents:
        doc_id = doc["id"]
        if doc_id in seen:
            raise ValueError(f"duplicate document id {doc_id!r}")
        seen.add(doc_id)
        fmt = doc.get("fmt") or "text"
        if doc.get("error"):
            rows.append(unreadable_row(doc_id, doc["error"], fmt=fmt))
        else:
            rows.append(fingerprint(doc_id, doc.get("text") or "", fmt=fmt, config=cfg))
    rows.sort(key=lambda r: r["id"])
    return rows


def document_view(
    rows: list[dict[str, Any]], *, include_shingles: bool = False
) -> list[dict[str, Any]]:
    """The reportable projection of the rows: counts, not hundreds of digests.

    A 400-page corpus carries hundreds of thousands of shingle digests; dumping
    them buries the findings in a JSON envelope nobody will read. `shingle_count`
    is kept always (it is what makes a similarity checkable by hand against
    shared/union), and the digests themselves are opt-in for auditing.
    """
    view = []
    for row in rows:
        out = {k: v for k, v in row.items() if k != "shingles"}
        if include_shingles:
            out["shingles"] = list(row.get("shingles", ()))
        view.append(out)
    return view


# ---- similarity -------------------------------------------------------------


def jaccard(a: set[str], b: set[str]) -> float | None:
    """|A n B| / |A u B|, or None when both sets are empty (undefined, not 0.0).

    THE DEFINITION. jaccard_from_counts() is the hot path and is tested against
    this function so the two can never diverge.
    """
    union = len(a | b)
    if union == 0:
        return None
    return len(a & b) / union


def jaccard_from_counts(shared: int, size_a: int, size_b: int) -> float | None:
    """Jaccard from a shared-shingle COUNT — no set intersection on the hot path.

    |A u B| = |A| + |B| - |A n B| exactly, so the postings-index count is
    sufficient. A shared count larger than the smaller set is arithmetically
    impossible and raises rather than producing a similarity above 1.0.
    """
    if shared < 0:
        raise ValueError(f"shared count cannot be negative, got {shared}")
    if shared > min(size_a, size_b):
        raise ValueError(
            f"shared ({shared}) exceeds the smaller set ({min(size_a, size_b)})"
        )
    union = size_a + size_b - shared
    if union <= 0:
        return None
    return shared / union


def containment_from_counts(shared: int, size_a: int, size_b: int) -> float | None:
    """|A n B| / min(|A|,|B|) — "is the smaller one inside the larger one?".

    None when either set is empty. This is the reading that catches a 300-word
    draft lifted verbatim into a 5,000-word page, where Jaccard reads ~0.06.
    """
    smaller = min(size_a, size_b)
    if smaller <= 0:
        return None
    return shared / smaller


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


# ---- pairing ----------------------------------------------------------------


def shingle_index(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """shingle digest -> the document ids carrying it (input order preserved)."""
    idx: dict[str, list[str]] = {}
    for row in rows:
        for d in row.get("shingles", ()):
            idx.setdefault(d, []).append(row["id"])
    return idx


def shared_counts(rows: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    """Exact shared-shingle count for every pair that shares >= 1 shingle.

    This IS the candidate generation: a pair sharing no shingle has Jaccard 0
    and containment 0, so it can never clear a positive gate and is never
    visited. Keys are (lo, hi) sorted, so a pair is counted once.
    """
    counts: dict[tuple[str, str], int] = {}
    for ids in shingle_index(rows).values():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j]) if ids[i] <= ids[j] else (ids[j], ids[i])
                counts[key] = counts.get(key, 0) + 1
    return counts


def exact_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Documents grouped by normalized content hash — groups of 2+ only, sorted."""
    buckets: dict[str, list[str]] = {}
    for row in rows:
        digest = row.get("content_sha256")
        if digest:
            buckets.setdefault(digest, []).append(row["id"])
    groups = [
        {"content_sha256": digest, "members": sorted(ids)}
        for digest, ids in buckets.items()
        if len(ids) > 1
    ]
    return sorted(groups, key=lambda g: (-len(g["members"]), g["members"][0]))


def classify(
    similarity: float | None,
    containment: float | None,
    *,
    exact: bool,
    config: dict[str, Any],
) -> str | None:
    """(similarity, containment, exact) -> "exact" | "near" | "partial" | None.

    Order matters and is the severity contract: an identical normalized body is
    `exact` regardless of the thresholds; otherwise the Jaccard gate decides
    `near`; otherwise the containment gate decides `partial` (a slice, not a
    twin). None means "below every gate" and is dropped by find_pairs.
    """
    if exact:
        return "exact"
    if similarity is not None and similarity >= config["threshold"]:
        return "near"
    if containment is not None and containment >= config["containment_threshold"]:
        return "partial"
    return None


def compare_rows(
    row_a: dict[str, Any],
    row_b: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    shared: int | None = None,
) -> dict[str, Any]:
    """Two fingerprint rows -> the pair reading (value or labelled reason).

    `shared` comes from the postings index on the hot path; omitted, the shared
    count is computed from the sets directly (the definition path, and what the
    two-document `compare` command uses).
    """
    cfg = config if config is not None else merge_config()
    a, b = (row_a, row_b) if row_a["id"] <= row_b["id"] else (row_b, row_a)
    set_a, set_b = set(a.get("shingles", ())), set(b.get("shingles", ()))
    both = bool(set_a) and bool(set_b)
    exact = bool(
        a.get("content_sha256") and a.get("content_sha256") == b.get("content_sha256")
    )
    pair: dict[str, Any] = {
        "a": a["id"],
        "b": b["id"],
        "exact": exact,
        "similarity": None,
        "containment": None,
        "shared": None,
        "union": None,
        "error": None,
    }
    if not both:
        reasons = [
            f"{row['id']}: {row['errors'].get('shingles') or row['errors'].get('read') or 'no shingles'}"
            for row in (a, b)
            if not row.get("shingles")
        ]
        pair["error"] = "no shingle sets to compare — " + "; ".join(reasons)
        pair["kind"] = classify(None, None, exact=exact, config=cfg)
        return pair
    count = len(set_a & set_b) if shared is None else shared
    pair["shared"] = count
    pair["union"] = len(set_a) + len(set_b) - count
    pair["similarity"] = _round(jaccard_from_counts(count, len(set_a), len(set_b)))
    pair["containment"] = _round(containment_from_counts(count, len(set_a), len(set_b)))
    pair["kind"] = classify(
        pair["similarity"], pair["containment"], exact=exact, config=cfg
    )
    return pair


def _pair_sort_key(pair: dict[str, Any]) -> tuple[Any, ...]:
    # kind first (exact before near before partial), then strongest similarity,
    # then ids. An exact pair with no measurable similarity sorts as 1.0 — its
    # kind already put it first, and the fallback keeps the order total.
    sim = pair["similarity"]
    if sim is None:
        sim = 1.0 if pair["exact"] else 0.0
    return (_KIND_RANK.get(pair.get("kind"), len(KINDS)), -sim, pair["a"], pair["b"])


def find_pairs(
    rows: list[dict[str, Any]], *, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Every pair at or above a gate, deterministically ordered.

    Candidates are the union of (a) pairs sharing at least one shingle and (b)
    pairs with the same normalized content hash — (b) matters because two
    documents can be byte-for-byte identical in prose yet too short to shingle,
    and dropping them would be the exact silent miss this adapter exists to
    prevent.
    """
    cfg = config if config is not None else merge_config()
    by_id = {row["id"]: row for row in rows}
    counts = shared_counts([r for r in rows if is_measurable(r)])
    candidates: dict[tuple[str, str], int | None] = dict(counts)
    for group in exact_groups(rows):
        members = group["members"]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                candidates.setdefault((members[i], members[j]), None)
    pairs = []
    for (a_id, b_id), shared in sorted(candidates.items()):
        pair = compare_rows(by_id[a_id], by_id[b_id], config=cfg, shared=shared)
        if pair.get("kind") in _KIND_RANK:
            pairs.append(pair)
    return sorted(pairs, key=_pair_sort_key)


# ---- clustering -------------------------------------------------------------


def _root(parent: dict[str, str], node: str) -> str:
    while parent[node] != node:
        parent[node] = parent[parent[node]]  # path halving
        node = parent[node]
    return node


def cluster_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union-find the pairs into connected components (the reportable unit).

    Five recycled variants of one page are ONE cluster of five, not ten pairs
    for a human to re-assemble. `max_similarity` is None only when every pair
    in the cluster was exact-by-hash with no shingle sets, and `unmeasured`
    counts those — a None here is a stated absence, not a zero.
    """
    parent: dict[str, str] = {}
    for pair in pairs:
        for node in (pair["a"], pair["b"]):
            parent.setdefault(node, node)
    for pair in pairs:
        ra, rb = _root(parent, pair["a"]), _root(parent, pair["b"])
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        grouped.setdefault(_root(parent, pair["a"]), []).append(pair)
    clusters = []
    for members_pairs in grouped.values():
        members = sorted(
            {p["a"] for p in members_pairs} | {p["b"] for p in members_pairs}
        )
        sims = [p["similarity"] for p in members_pairs if p["similarity"] is not None]
        clusters.append(
            {
                "members": members,
                "size": len(members),
                "pairs": len(members_pairs),
                "kinds": sorted({p["kind"] for p in members_pairs}),
                "max_similarity": max(sims) if sims else None,
                "min_similarity": min(sims) if sims else None,
                "unmeasured": len(members_pairs) - len(sims),
            }
        )
    return sorted(clusters, key=lambda c: (-c["size"], -c["pairs"], c["members"][0]))


# ---- diagnostics + the whole pass -------------------------------------------


def _pair_message(pair: dict[str, Any]) -> str:
    if pair["similarity"] is None:
        return f"{pair['kind']} duplicate of {pair['a']} — {pair['error']}"
    return (
        f"{pair['kind']} duplicate of {pair['a']} — jaccard {pair['similarity']:.3f}, "
        f"containment {pair['containment']:.3f} ({pair['shared']}/{pair['union']} shingles)"
    )


def to_diagnostics(
    pairs: list[dict[str, Any]],
    rows: list[dict[str, Any]] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pairs (+ unmeasured documents) -> the family diagnostic schema.

    The duplicate is reported ON the second path with the first named in the
    message, so `--fail-on` gates and openswap.summarize() treat a recycled page
    exactly like a prose lint finding. Documents that could not be measured emit
    an info diagnostic carrying their labelled reason — a report that hid its own
    blind spots would be worse than no report.
    """
    cfg = config if config is not None else merge_config()
    sev = cfg["severity"]
    diags = [
        openswap.diagnostic(
            path=pair["b"],
            line=0,
            col=0,
            rule=f"dupes:{pair['kind']}-duplicate",
            severity=sev.get(pair["kind"], "warning"),
            message=_pair_message(pair),
        )
        for pair in pairs
    ]
    for row in rows or ():
        for reading, reason in sorted(row.get("errors", {}).items()):
            diags.append(
                openswap.diagnostic(
                    path=row["id"],
                    line=0,
                    col=0,
                    rule=f"dupes:unmeasured-{reading}",
                    severity=sev["unmeasured"],
                    message=f"{reading} unavailable — {reason}",
                )
            )
    return openswap.sort_diagnostics(diags)


def analyze(
    documents: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    include_shingles: bool = False,
) -> dict[str, Any]:
    """The whole deterministic pass: fingerprint -> pair -> cluster -> report.

    `documents` are {"id", "text", "fmt"} dicts, or {"id", "error"} for one the
    caller could not read (which is reported, never dropped). The returned
    `documents` are the reportable projection — pass include_shingles=True to
    audit the digests themselves.
    """
    cfg = config if config is not None else merge_config()
    rows = fingerprint_documents(documents, config=cfg)
    pairs = find_pairs(rows, config=cfg)
    unmeasured = [r for r in rows if r["errors"]]
    diags = to_diagnostics(pairs, unmeasured, config=cfg)
    measurable = [r for r in rows if is_measurable(r)]
    return {
        "config": cfg,
        "documents": document_view(rows, include_shingles=include_shingles),
        "counts": {
            "documents": len(rows),
            "shingled": len(measurable),
            "unmeasured": len(unmeasured),
            "shingles": sum(r["shingle_count"] for r in rows),
            # what the postings index bought: pairs actually compared vs the
            # n*(n-1)/2 a brute-force sweep would have touched
            "compared_pairs": len(shared_counts(measurable)),
            "possible_pairs": len(measurable) * (len(measurable) - 1) // 2,
        },
        "exact_groups": exact_groups(rows),
        "pairs": pairs,
        "clusters": cluster_pairs(pairs),
        "diagnostics": diags,
        "summary": openswap.summarize(diags),
    }
