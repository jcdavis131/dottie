# Solo personal project, no connection to employer, built with public/free-tier only
"""Ollama — local-model adapter core (openswap #17: ChatGPT Plus / hosted LLM APIs).

The paid enemy here is a subscription plus a metered key: ChatGPT Plus, the
Anthropic/OpenAI HTTP APIs, and every "AI feature" that bills per token and
keeps a copy of the prompt. This adapter inverts that — inference happens on
THIS box against a local ollama daemon on loopback, there is no API key
anywhere in the plugin (the manifest's secrets allowlist is empty), and the
usage ledger stores a prompt HASH rather than the prompt, because rebuilding
the hosted provider's prompt log locally would give back the thing #17 deletes.

Real I/O stays out of this module: the `ollama` plugin CLI owns the urllib
GET/POST to 127.0.0.1:11434 and injects it as a callable (the
bigbang/core/certmon.py + plugins/certmon/cli.py pattern), so the whole
pipeline — detection, catalog parsing, model choice, completion, degradation,
ledger, diagnostics — is unit-testable fully offline. Nothing here opens a
socket, and `resolve`/`complete` never raise.

RELATIONSHIP TO bigbang/core/llm.py (deliberate, not duplication): that module
is the httpx-based router the `agent`/`ava` planners already call, and it
returns None the moment httpx is absent. #17's premise is zero dependencies, so
the transport here is stdlib urllib and the fallback is a labelled template
instead of a None. Two other differences are substantive, not stylistic:
- llm.get_best_model() ranks a hardcoded PREFERRED_MODELS list biggest-first
  (qwen3:32b before qwen3:8b). pick_model() here is cost-first — explicit
  request, then a model already RESIDENT per /api/ps, then the SMALLEST
  installed — because this box runs ollama with NUM_GPU=0 and the largest
  installed model is the one that thrashes system RAM for minutes per token.
- llm returns prose or None. complete() always returns a record that states
  its provenance: source="model" or source="template" with degraded=True.

NEVER ASSUME GPU. /api/tags reports on-disk blob size and nothing about
placement, so parse_models() reports nothing about placement either. Placement
comes only from /api/ps's size_vram, and placement() maps a MISSING key to
"unknown" rather than "gpu" — printing "gpu" because the machine happens to
own a 4080 while ollama is loading into system RAM is exactly the lie this
family exists to kill.

Honest degradation is the load-bearing behavior. When no endpoint answers,
assemble_template() produces a scaffold built ONLY from the caller's own words
(verbatim echo, keyword intent match, stopword-filtered salient terms) whose
first line is DEGRADED_BANNER and which contains the literal marker
"NOT ANSWERED". It does not think, and it says so on every line of its header;
`run --fail-on-degraded` turns that into a nonzero exit for cron/CI.

Extension points:
- Endpoint override as config: candidate_bases(explicit, env) reads
  OLLAMA_BASE/OLLAMA_URL/OLLAMA_HOST from an INJECTED mapping, so tests and
  callers never depend on the developer's shell.
- Generation options as config: complete(options={...}) passes ollama's own
  option block through untouched (num_predict, temperature, num_gpu) — tune
  without touching code.
- Continuous liveness monitoring is NOT here: uptime (#2) already probes
  http://127.0.0.1:11434/api/version as a fleet target with its own damping and
  incident state machine. `detect` is a one-shot capability probe; duplicating
  the monitor would be a second parallel store of the same fact.
- Usage rollups: usage() reports the model-vs-template share (the honesty
  audit: how often did this box actually think?), token totals and tok/s
  percentiles; history() is the per-completion read contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from bigbang.core import openswap

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

DEFAULT_PORT = 11434
# loopback first: the local daemon is the product, and 127.0.0.1 skips the
# name-resolution round trip "localhost" pays on Windows
DEFAULT_BASES = ("http://127.0.0.1:11434", "http://localhost:11434")
# the env names ollama itself and bigbang/core/llm.py already honor, in that order
ENV_BASES = ("OLLAMA_BASE", "OLLAMA_URL", "OLLAMA_HOST")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

DB_REL = Path(".scout") / "ollama.db"
SCHEMA_VERSION = "1"

VERSION_PATH = "/api/version"
TAGS_PATH = "/api/tags"
PS_PATH = "/api/ps"
GENERATE_PATH = "/api/generate"

SOURCE_MODEL = "model"
SOURCE_TEMPLATE = "template"

# Placement is reported, never inferred from the hardware present.
PLACEMENT_CPU = "cpu"
PLACEMENT_GPU = "gpu"
PLACEMENT_SPLIT = "split"
PLACEMENT_UNKNOWN = "unknown"

DEGRADED_BANNER = (
    "[DEGRADED — no local model answered; this is TEMPLATE ASSEMBLY, not inference]"
)
NOT_ANSWERED = "NOT ANSWERED."

PROMPT_ECHO_CHARS = 400


# ---- endpoints ---------------------------------------------------------------


def normalize_base(value: str) -> str:
    """A user/env endpoint -> 'scheme://host:port', no trailing path.

    Accepts 'host', 'host:port', 'http://host:port/' and a full API path such as
    'http://host:11434/api/tags' (what people paste out of curl). A missing
    scheme becomes http (ollama serves plain http on loopback) and a missing
    port becomes 11434. Raises ValueError when there is no host at all, so a
    typo can never silently become a default that happens to answer.
    """
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("empty ollama endpoint")
    if "://" not in raw:
        raw = f"http://{raw}"
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"ollama endpoint must be http(s), got {value!r}")
    host = parts.hostname
    if not host:
        raise ValueError(f"ollama endpoint has no host: {value!r}")
    port = parts.port or DEFAULT_PORT
    host = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{host}:{port}"


def candidate_bases(
    explicit: str | None = None, env: Mapping[str, str] | None = None
) -> list[str]:
    """Endpoints to try, in order. An explicit base is EXCLUSIVE, not a first guess.

    Naming an endpoint and then answering from a different one would be the
    quiet lie this family refuses ("you asked :1, I answered from :11434"), so
    `explicit` suppresses the discovery chain entirely. With no explicit base the
    chain is env then loopback; `env` is injected (os.environ by default) so
    tests never depend on the developer's shell, and an unparseable entry is
    SKIPPED rather than raised — an exported OLLAMA_HOST typo must not take out
    the loopback default. A typo in an explicit base is a user error the caller
    validates instead.
    """
    if explicit and str(explicit).strip():
        try:
            return [normalize_base(explicit)]
        except ValueError:
            return []
    env = os.environ if env is None else env
    raw: list[str | None] = [env.get(k) for k in ENV_BASES]
    raw += list(DEFAULT_BASES)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not item:
            continue
        try:
            base = normalize_base(item)
        except ValueError:
            continue
        if base not in seen:
            seen.add(base)
            out.append(base)
    return out


def is_loopback(base: str) -> bool:
    """True only for localhost/127.0.0.1/::1 — the strict direction on purpose.

    An off-box endpoint is a hosted API wearing ollama's URL shape, which is the
    exact thing #17 deletes, so the CLI gates it against the user's persisted
    allowlist as well as the manifest. Anything this function cannot prove is
    loopback (a LAN IP, a tunnel host, 127.0.0.2) takes that stricter path.
    """
    host = (urlsplit(base).hostname or "").strip("[]").lower()
    return host in LOOPBACK_HOSTS


def resolve(
    probe: Callable[[str, str], dict[str, Any]],
    bases: list[str],
    *,
    path: str = VERSION_PATH,
) -> dict[str, Any]:
    """First base that answers 200 with JSON, plus the evidence of every attempt.

    `probe(base, path)` is injected — the CLI supplies the urllib GET, tests
    supply fakes (the offline invariant) — and must return
    {"status": int|None, "json": obj|None, "error": str|None} without raising.
    Recording every attempt is the point: "nothing answered" has to name what
    was tried, or the operator cannot tell a wrong port from a stopped daemon.
    """
    tried: list[dict[str, Any]] = []
    live: str | None = None
    payload: Any = None
    for base in bases:
        res = probe(base, path) or {}
        status = res.get("status")
        answered = status == 200 and res.get("json") is not None
        tried.append(
            {
                "base": base,
                "path": path,
                "status": status,
                "error": res.get("error"),
                "ok": answered,
            }
        )
        if answered:
            live = base
            payload = res.get("json")
            break
    return {
        "base": live,
        "reachable": live is not None,
        "path": path,
        "payload": payload,
        "tried": tried,
    }


def unreachable_reason(resolution: dict[str, Any]) -> str:
    """One actionable line naming every endpoint tried and how each failed."""
    parts = []
    for t in resolution.get("tried", []):
        detail = t.get("error") or (f"HTTP {t['status']}" if t.get("status") else "no answer")
        parts.append(f"{t['base']} ({detail})")
    tried = "; ".join(parts) or "no candidate endpoints"
    return f"no ollama endpoint answered {resolution.get('path', '')}: {tried}"


# ---- catalog / residency ----------------------------------------------------


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _gb(value: Any) -> float | None:
    n = _int_or_none(value)
    return None if n is None else round(n / 1_000_000_000, 2)


def parse_version(payload: Any) -> str | None:
    """/api/version -> the daemon's version string, or None."""
    if isinstance(payload, dict):
        v = payload.get("version")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def parse_models(payload: Any) -> list[dict[str, Any]]:
    """/api/tags -> normalized catalog rows, name-sorted. Tolerant of junk.

    A tag listing knows the on-disk blob size and NOTHING about placement — no
    GPU, no VRAM — so no placement key appears here. Where a model actually runs
    comes from parse_loaded() or from nowhere.
    """
    rows: list[dict[str, Any]] = []
    models = payload.get("models") if isinstance(payload, dict) else None
    for m in models or ():
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model")
        if not isinstance(name, str) or not name.strip():
            continue
        det = m.get("details") if isinstance(m.get("details"), dict) else {}
        rows.append(
            {
                "name": name.strip(),
                "family": det.get("family"),
                "parameter_size": det.get("parameter_size"),
                "quantization": det.get("quantization_level"),
                "size_bytes": _int_or_none(m.get("size")),
                "size_gb": _gb(m.get("size")),
                "modified": m.get("modified_at"),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def placement(size_bytes: int | None, size_vram: int | None) -> str:
    """Where a resident model lives — derived ONLY from what ollama reported.

    This box runs qwen3:8b with NUM_GPU=0, i.e. entirely in SYSTEM RAM, so the
    presence of a GPU proves nothing. No size_vram key at all is "unknown"
    (never "gpu"), size_vram == 0 is "cpu", size_vram >= size is "gpu", between
    is "split", and vram>0 with an unknown total stays "unknown" because the
    split is genuinely unknown rather than assumed.
    """
    if size_vram is None:
        return PLACEMENT_UNKNOWN
    if size_vram <= 0:
        return PLACEMENT_CPU
    if size_bytes is None:
        return PLACEMENT_UNKNOWN
    if size_vram >= size_bytes:
        return PLACEMENT_GPU
    return PLACEMENT_SPLIT


def parse_loaded(payload: Any) -> list[dict[str, Any]]:
    """/api/ps -> resident models with honest placement, name-sorted."""
    rows: list[dict[str, Any]] = []
    models = payload.get("models") if isinstance(payload, dict) else None
    for m in models or ():
        if not isinstance(m, dict):
            continue
        name = m.get("name") or m.get("model")
        if not isinstance(name, str) or not name.strip():
            continue
        size = _int_or_none(m.get("size"))
        vram = _int_or_none(m.get("size_vram"))
        rows.append(
            {
                "name": name.strip(),
                "size_bytes": size,
                "size_gb": _gb(size),
                "vram_bytes": vram,
                "vram_gb": _gb(vram),
                "placement": placement(size, vram),
                "expires_at": m.get("expires_at"),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def pick_model(
    available: list[dict[str, Any]] | None,
    *,
    want: str | None = None,
    loaded: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """Choose a model and SAY why: (name, reason); name None means do not run.

    Cost-first, and deliberately not "biggest wins" (see the module doc on
    llm.get_best_model): an explicit request, then a model already resident per
    /api/ps (warm, zero load cost), then the smallest installed model — the one
    most likely to answer at all when ollama is on CPU.

    An explicit request that is not installed returns None: substituting a
    different model for the one the caller named would be the quiet lie this
    family refuses. Ambiguous prefixes are refused for the same reason.
    """
    rows = [r for r in (available or ()) if r.get("name")]
    names = [str(r["name"]) for r in rows]
    if not names:
        return None, "no models installed — `ollama pull qwen3:8b`"
    if want and want.strip():
        w = want.strip().lower()
        for n in names:
            if n.lower() == w:
                return n, f"explicit request {want!r}"
        matches = [n for n in names if n.lower().startswith(w)]
        if len(matches) == 1:
            return matches[0], f"unique prefix match for {want!r}"
        if matches:
            return None, f"{want!r} is ambiguous — matches {matches}"
        return None, f"{want!r} is not installed — installed: {names}"
    for r in loaded or ():
        nm = r.get("name")
        if isinstance(nm, str) and nm in names:
            return nm, f"already resident ({r.get('placement')}) — no load cost"
    sized = [r for r in rows if r.get("size_bytes")]
    if sized:
        best = min(sized, key=lambda r: (r["size_bytes"], r["name"]))
        return (
            str(best["name"]),
            "smallest installed model — CPU-first (this box may run NUM_GPU=0)",
        )
    return names[0], "first installed model (no sizes reported)"


# ---- completion -------------------------------------------------------------


def parse_completion(payload: Any) -> dict[str, Any] | None:
    """/api/generate|/api/chat (stream=false) -> normalized fields, or None.

    None means "there is no completion in this payload" — never an empty string
    dressed up as an answer, which is how a broken backend starts looking like a
    laconic model. tok_per_s uses ollama's OWN eval_duration (nanoseconds) so it
    measures generation rather than our network and queue time, and it is
    omitted rather than guessed when the server does not report both numbers.
    """
    if not isinstance(payload, dict):
        return None
    text = payload.get("response")
    if not isinstance(text, str):
        msg = payload.get("message")
        text = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(text, str) or not text.strip():
        return None
    eval_count = _int_or_none(payload.get("eval_count"))
    eval_ns = _int_or_none(payload.get("eval_duration"))
    tok_per_s = None
    if eval_count and eval_ns and eval_ns > 0:
        tok_per_s = round(eval_count / (eval_ns / 1e9), 2)
    model = payload.get("model")
    return {
        "text": text,
        "model": model if isinstance(model, str) else None,
        "done_reason": payload.get("done_reason"),
        "prompt_tokens": _int_or_none(payload.get("prompt_eval_count")),
        "eval_tokens": eval_count,
        "eval_seconds": round(eval_ns / 1e9, 4) if eval_ns else None,
        "tok_per_s": tok_per_s,
    }


# ---- honest degradation: template assembly ----------------------------------

# keyword -> intent. Matched as substrings against the lowered prompt, first hit
# wins, and the verdict is labelled "keyword match, not comprehension" wherever
# it is printed. This is string matching; calling it understanding would be the
# same lie as printing "gpu" for a CPU load.
_INTENT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("summar", "tl;dr", "tldr", "recap", "condense"), "summarize"),
    (("list ", "enumerate", "bullet", "top ", "options for"), "list"),
    (("compare", "versus", " vs ", "difference between", "trade-off"), "compare"),
    (("code", "function", "script", "regex", "sql ", "implement"), "code"),
    (("why", "how ", "explain", "what is", "what are", "cause"), "explain"),
    (("fix", "debug", "error", "traceback", "failing", "broken"), "debug"),
    (("write", "draft", "email", "post", "reply"), "draft"),
)
INTENT_OTHER = "other"

# What the scaffold offers per intent. Every line is a slot the caller (or a
# real model) fills; none of them asserts anything about the subject.
_INTENT_SLOTS: dict[str, tuple[str, ...]] = {
    "summarize": ("source text to compress:", "claims worth keeping:", "what to cut:"),
    "list": ("candidate items:", "ordering rule:", "what disqualifies an item:"),
    "compare": ("option A:", "option B:", "axes to compare on:", "decision rule:"),
    "code": ("inputs and types:", "expected output:", "failure cases to handle:"),
    "explain": ("mechanism to describe:", "evidence for it:", "known unknowns:"),
    "debug": ("exact error text:", "last change before it broke:", "how to reproduce:"),
    "draft": ("audience:", "one thing they must do:", "tone constraints:"),
    INTENT_OTHER: ("restated request:", "constraints:", "what would count as done:"),
}

_STOPWORDS = frozenset(
    """a about all also an and any are as at be because been but by can could did do
does for from get give had has have how i if in into is it its just like make may me
more most my need no not of on one or our out over please should so some such than
that the their them then there these they this those to too under up us use used using
very want was we were what when where which who why will with would you your""".split()
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{1,}")


def classify_intent(prompt: str) -> str:
    """Keyword intent bucket for the scaffold. Substring matching, nothing more."""
    low = f" {str(prompt or '').lower()} "
    for needles, intent in _INTENT_RULES:
        if any(n in low for n in needles):
            return intent
    return INTENT_OTHER


def salient_terms(prompt: str, *, limit: int = 8) -> list[str]:
    """Frequency-ranked non-stopword terms taken VERBATIM from the prompt.

    Ties break alphabetically so the same prompt always yields the same terms —
    a degraded answer that changes between runs would look like a model. Every
    returned term is a substring of the prompt by construction: the scaffold
    introduces no vocabulary of its own about the subject.
    """
    counts: dict[str, int] = {}
    for raw in _WORD_RE.findall(str(prompt or "")):
        w = raw.strip(".-_").lower()
        if len(w) < 3 or w in _STOPWORDS:
            continue
        counts[w] = counts.get(w, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[: max(0, limit)]]


def assemble_template(
    prompt: str, *, reason: str, model_hint: str | None = None
) -> dict[str, Any]:
    """The degraded path: a labelled scaffold built only from the caller's words.

    Deterministic (same prompt + same reason -> byte-identical text), banner-led
    (DEGRADED_BANNER is line 1), and explicitly non-answering (the literal
    NOT_ANSWERED marker plus a sentence stating that no reasoning happened).
    The prompt is echoed verbatim, truncated at PROMPT_ECHO_CHARS, so the
    operator can see exactly what was not answered.
    """
    text_in = str(prompt or "")
    intent = classify_intent(text_in)
    terms = salient_terms(text_in)
    echo = text_in.strip().replace("\r\n", "\n")
    truncated = len(echo) > PROMPT_ECHO_CHARS
    if truncated:
        echo = echo[:PROMPT_ECHO_CHARS] + " …[truncated]"
    lines = [
        DEGRADED_BANNER,
        f"reason: {reason}",
        f"{NOT_ANSWERED} No model reasoned about the request below; the lines that",
        "follow are a scaffold assembled from your own words by string matching.",
        f"detected intent: {intent} (keyword match, not comprehension)",
        f"salient terms: {', '.join(terms) if terms else '(none extracted)'}",
        "",
        "--- your request, verbatim ---",
        echo,
        "",
        "--- scaffold to fill in (by you, or by a model once one is running) ---",
    ]
    lines += [f"- {slot}" for slot in _INTENT_SLOTS[intent]]
    if model_hint:
        lines.append(f"- rerun with: scout ollama run --model {model_hint} --prompt ...")
    return {
        "text": "\n".join(lines) + "\n",
        "intent": intent,
        "terms": terms,
        "prompt_truncated": truncated,
    }


def prompt_fingerprint(prompt: str) -> str:
    """First 16 hex of sha256(prompt) — dedupe/correlation WITHOUT a transcript.

    Truncated on purpose: it is long enough to correlate repeated prompts in the
    ledger and far too short to be a covert copy of the text.
    """
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:16]


def complete(
    post: Callable[[str, str, dict[str, Any]], dict[str, Any]],
    prompt: str,
    *,
    model: str | None,
    base: str | None,
    system: str | None = None,
    options: dict[str, Any] | None = None,
    reason: str = "",
    now: float | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """One completion attempt with an honest fallback. Never raises.

    `post(base, path, payload)` is injected — the CLI supplies the urllib POST,
    tests supply fakes — and must return {"status", "json", "error"}. Anything
    other than a 200 carrying a parseable completion degrades to
    assemble_template() with the failure recorded verbatim in `reason`: we never
    emit model-shaped prose that no model produced. With base or model None
    (nothing reachable, nothing installed) no request is attempted at all.

    The returned record is the ledger row and the CLI payload in one shape;
    `source` and `degraded` are the fields callers must branch on.
    """
    ts = clock() if now is None else float(now)
    rec: dict[str, Any] = {
        "ts": ts,
        "source": SOURCE_TEMPLATE,
        "degraded": True,
        "text": "",
        "model": model,
        "base": base,
        "prompt_sha256": prompt_fingerprint(prompt),
        "prompt_chars": len(str(prompt or "")),
        "reason": reason,
        "http_status": None,
        "elapsed_s": None,
        "prompt_tokens": None,
        "eval_tokens": None,
        "eval_seconds": None,
        "tok_per_s": None,
        "intent": None,
        "terms": [],
    }
    if base and model:
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = dict(options)
        t0 = clock()
        res = post(base, GENERATE_PATH, payload) or {}
        rec["elapsed_s"] = round(clock() - t0, 4)
        rec["http_status"] = res.get("status")
        parsed = parse_completion(res.get("json"))
        if res.get("status") == 200 and parsed:
            rec.update(
                source=SOURCE_MODEL,
                degraded=False,
                text=parsed["text"],
                model=parsed["model"] or model,
                reason=f"{model} answered via {base}{GENERATE_PATH}",
                prompt_tokens=parsed["prompt_tokens"],
                eval_tokens=parsed["eval_tokens"],
                eval_seconds=parsed["eval_seconds"],
                tok_per_s=parsed["tok_per_s"],
            )
            return rec
        detail = res.get("error") or (
            f"HTTP {res['status']} with no completion"
            if res.get("status")
            else "no response"
        )
        rec["reason"] = f"{model} at {base} did not complete: {detail}"
    assembled = assemble_template(prompt, reason=rec["reason"], model_hint=model)
    rec.update(
        text=assembled["text"],
        intent=assembled["intent"],
        terms=assembled["terms"],
    )
    return rec


# ---- ledger (its own file; a usage audit, NOT a prompt log) ------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS completions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    degraded INTEGER NOT NULL,
    model TEXT,
    base TEXT,
    prompt_sha256 TEXT NOT NULL,
    prompt_chars INTEGER NOT NULL,
    text_chars INTEGER NOT NULL,
    prompt_tokens INTEGER,
    eval_tokens INTEGER,
    eval_seconds REAL,
    tok_per_s REAL,
    elapsed_s REAL,
    http_status INTEGER,
    intent TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_completions_ts ON completions(ts);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# The columns that exist are the whole privacy story: lengths, a truncated
# hash, timings and provenance. There is deliberately NO prompt column and NO
# completion column — a local rebuild of the hosted provider's prompt log would
# hand back the exact artifact #17 deletes. Callers who want transcripts must
# store them somewhere they chose on purpose.


def open_ledger(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the usage ledger — its OWN sqlite file.

    Never the #2 uptime ledger: completions are bursty and would contend with
    the monitoring probe loop's write lock for no shared benefit (uptime already
    tracks the endpoint's liveness on its own timeline).
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()
    return conn


def record_completion(conn: sqlite3.Connection, rec: dict[str, Any]) -> int:
    """Append one completion record; returns the row id.

    Degraded attempts are recorded exactly like successful ones — dropping them
    would make the model_share rollup flattering and useless.
    """
    cur = conn.execute(
        "INSERT INTO completions(ts, source, degraded, model, base, prompt_sha256,"
        " prompt_chars, text_chars, prompt_tokens, eval_tokens, eval_seconds,"
        " tok_per_s, elapsed_s, http_status, intent, reason)"
        " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            float(rec.get("ts") or time.time()),
            rec.get("source", SOURCE_TEMPLATE),
            int(bool(rec.get("degraded", True))),
            rec.get("model"),
            rec.get("base"),
            rec.get("prompt_sha256", ""),
            int(rec.get("prompt_chars") or 0),
            len(str(rec.get("text") or "")),
            rec.get("prompt_tokens"),
            rec.get("eval_tokens"),
            rec.get("eval_seconds"),
            rec.get("tok_per_s"),
            rec.get("elapsed_s"),
            rec.get("http_status"),
            rec.get("intent"),
            rec.get("reason"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def history(
    conn: sqlite3.Connection, *, limit: int = 20, source: str | None = None
) -> list[dict[str, Any]]:
    """Newest-first completion records, optionally filtered to one source."""
    sql = "SELECT * FROM completions"
    params: list[Any] = []
    if source:
        sql += " WHERE source = ?"
        params.append(source)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(int(limit))
    return [dict(r) for r in conn.execute(sql, params)]


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return round(ordered[idx], 2)


def usage(conn: sqlite3.Connection, *, since: float | None = None) -> dict[str, Any]:
    """The honesty audit: what share of answers actually came from a model.

    model_share_pct is None — not 0.0, not 100.0 — when nothing has been
    recorded, because an empty ledger is not evidence of anything. tok/s
    percentiles cover model rows only; a template has no tokens and averaging it
    in would flatter the number.
    """
    sql = "SELECT * FROM completions"
    params: list[Any] = []
    if since is not None:
        sql += " WHERE ts >= ?"
        params.append(float(since))
    rows = [dict(r) for r in conn.execute(sql, params)]
    by_source: dict[str, int] = {SOURCE_MODEL: 0, SOURCE_TEMPLATE: 0}
    by_model: dict[str, int] = {}
    tokens = 0
    rates: list[float] = []
    for r in rows:
        src = r.get("source") or SOURCE_TEMPLATE
        by_source[src] = by_source.get(src, 0) + 1
        if src == SOURCE_MODEL:
            name = r.get("model") or "(unnamed)"
            by_model[name] = by_model.get(name, 0) + 1
            tokens += int(r.get("eval_tokens") or 0)
            if r.get("tok_per_s"):
                rates.append(float(r["tok_per_s"]))
    total = len(rows)
    return {
        "total": total,
        "by_source": by_source,
        "model_share_pct": (
            round(100.0 * by_source[SOURCE_MODEL] / total, 2) if total else None
        ),
        "eval_tokens": tokens,
        "tok_per_s": {"p50": _percentile(rates, 0.5), "max": _percentile(rates, 1.0)},
        "by_model": dict(sorted(by_model.items())),
        "first_ts": min((r["ts"] for r in rows), default=None),
        "last_ts": max((r["ts"] for r in rows), default=None),
    }


# ---- family diagnostics -----------------------------------------------------


def endpoint_diagnostics(
    resolution: dict[str, Any],
    *,
    loaded: list[dict[str, Any]] | None = None,
    models: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Map a detection result onto the openswap diagnostic schema.

    Unreachable is a WARNING, not an error: a stopped daemon is the normal state
    on a laptop and the fallback still works. A cpu/split placement is INFO and
    never a warning — NUM_GPU=0 is this box's documented configuration, not a
    fault; the diagnostic exists so nobody later reads "gpu" into silence.
    """
    diags: list[dict[str, Any]] = []
    base = resolution.get("base") or "ollama"
    if not resolution.get("reachable"):
        diags.append(
            openswap.diagnostic(
                path=base,
                line=0,
                col=0,
                rule="ollama:unreachable",
                severity="warning",
                message=unreachable_reason(resolution),
                suggestion="start the daemon (`ollama serve`) or pass --base",
                source="ollama",
            )
        )
        return openswap.sort_diagnostics(diags)
    if models is not None and not models:
        diags.append(
            openswap.diagnostic(
                path=base,
                line=0,
                col=0,
                rule="ollama:no-models",
                severity="warning",
                message="endpoint answers but no models are installed",
                suggestion="ollama pull qwen3:8b",
                source="ollama",
            )
        )
    for row in loaded or ():
        if row.get("placement") in (PLACEMENT_CPU, PLACEMENT_SPLIT, PLACEMENT_UNKNOWN):
            diags.append(
                openswap.diagnostic(
                    path=base,
                    line=0,
                    col=0,
                    rule="ollama:cpu-placement",
                    severity="info",
                    message=(
                        f"{row['name']} is resident as {row['placement']} "
                        f"(vram {row.get('vram_gb')} GB of {row.get('size_gb')} GB) "
                        "— do not assume GPU"
                    ),
                    source="ollama",
                )
            )
    return openswap.sort_diagnostics(diags)


def to_diagnostics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Completion records -> family schema; a degraded answer is a warning.

    Successful model completions emit nothing (there is no finding), so an empty
    list means every answer in this batch came from a real model.
    """
    diags: list[dict[str, Any]] = []
    for i, rec in enumerate(records or (), start=1):
        if not rec.get("degraded"):
            continue
        diags.append(
            openswap.diagnostic(
                path=rec.get("base") or "ollama",
                line=i,
                col=0,
                rule="ollama:degraded",
                severity="warning",
                message=(
                    f"answer {i} was template assembly, not inference: "
                    f"{rec.get('reason') or 'no reason recorded'}"
                ),
                suggestion="start ollama and rerun; --fail-on-degraded gates this",
                source="ollama",
            )
        )
    return openswap.sort_diagnostics(diags)


def dumps(payload: Any) -> bytes:
    """JSON request body as bytes — the one thing the CLI's POST needs from here.

    Lives beside the schema it encodes so the transport in the plugin stays a
    dozen lines of urllib with no formatting decisions of its own.
    """
    return json.dumps(payload).encode("utf-8")
