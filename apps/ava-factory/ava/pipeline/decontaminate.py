"""Eval decontamination — the project's integrity gate.

Every headline number the project reports depends on the training corpus never
having seen the eval prompts verbatim. This module removes any training doc that
reproduces a held-out eval string (from :mod:`evals.eval_sets`).

The fact-vs-prompt boundary (the whole subtlety)
------------------------------------------------
`encyclopedia.py` deliberately writes canonical *facts* ("a spider has eight
legs") into training so the model LEARNS them. The eval, however, probes those
facts with specific *prompt surface-forms*. We must decontaminate the eval
PROMPTS, never the underlying facts:

  * too lax  -> the eval prompt leaks into training, the model memorizes the
    answer, and every reported score is inflated (poisoned eval);
  * too strict -> we also strip the plain facts, the model never learns them,
    and it fails evals it should pass (lobotomized model).

We walk the line with **verbatim contiguous n-gram matching**, not semantic
matching:

  * For an eval string of >= ``ngram`` words we index all of its ``ngram``-word
    (13 by default) shingles. A training doc is contaminated iff it contains one
    of those 13-word runs verbatim. A 13-word verbatim overlap is essentially
    never coincidental, yet a fact re-stated in different words ("Spiders
    possess eight legs.") shares no 13-word run with the probe, so it survives.
  * For a short eval prompt (< ``ngram`` words, e.g. "the capital of France is
    Paris") there is no 13-gram, so we index the whole normalized phrase and
    match it as a contiguous word run. We refuse to index anything shorter than
    ``MIN_PHRASE_WORDS`` words — a 3-word phrase would nuke innocent text — which
    is why every entry in ``evals/eval_sets.py`` is authored to be >= 5 words
    and distinctive.

Because matching is on the *prompt surface-form*, encyclopedia facts (written in
a different surface-form) are never touched. That is the design contract; the
eval_sets docstring holds up the other end by keeping probe phrasings distinct
from plain-fact phrasings.

Reporting
---------
Per-source removal counts are appended to ``/packed/decontam_report.json`` under
an OS file lock, so concurrent curator replicas don't clobber each other's
tallies.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import regex as re

from evals.eval_sets import EVAL_SETS

try:  # POSIX file locking (curator runs in a Linux container).
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows host fallback
    _HAVE_FCNTL = False

DEFAULT_REPORT_PATH = "/packed/decontam_report.json"

#: Shortest eval phrase we are willing to ban outright. Below this a contiguous
#: match is too likely to be an innocent common phrase.
MIN_PHRASE_WORDS = 5

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> list[str]:
    """Lowercased word tokens — the unit n-grams are built from.

    Casing and punctuation are dropped so "The capital of France is Paris." and
    "the capital of France is Paris" collapse to the same shingles; a benchmark
    leak paraphrased only by punctuation/case must still be caught.
    """
    return _WORD_RE.findall(text.lower())


def _hash_gram(gram: tuple[str, ...]) -> str:
    return hashlib.sha1(" ".join(gram).encode("utf-8")).hexdigest()


class Decontaminator:
    """Detects verbatim overlap between a doc and the held-out eval prompts.

    Build once (it indexes every eval string), then call :meth:`is_contaminated`
    per doc. Thread-safe for reads: after construction the indexes are immutable.
    """

    def __init__(self, ngram: int = 13, eval_sets: dict[str, list[str]] | None = None) -> None:
        self.ngram = ngram
        eval_sets = eval_sets if eval_sets is not None else EVAL_SETS

        # For each distinct window size k that appears in the index, a map from
        # gram-hash -> the eval-set name it came from. Detection slides a window
        # of each k over the doc and checks membership.
        self._by_size: dict[int, dict[str, str]] = {}
        self._sizes: list[int] = []

        for set_name, texts in eval_sets.items():
            for text in texts:
                self._index(text, set_name)
        self._sizes = sorted(self._by_size)

    def _index(self, text: str, set_name: str) -> None:
        words = _words(text)
        n = len(words)
        if n == 0:
            return
        if n >= self.ngram:
            k = self.ngram
            grams = [tuple(words[i : i + k]) for i in range(n - k + 1)]
        elif n >= MIN_PHRASE_WORDS:
            # Too short for a 13-gram: index the whole phrase as one k-gram.
            k = n
            grams = [tuple(words)]
        else:
            # Too short/generic to ban safely; skip. eval_sets is authored to
            # avoid this, but we degrade safely rather than nuke common phrases.
            return
        bucket = self._by_size.setdefault(k, {})
        for g in grams:
            bucket.setdefault(_hash_gram(g), set_name)

    def is_contaminated(self, text: str) -> tuple[bool, str | None]:
        """Return ``(True, eval_set_name)`` if any eval n-gram appears in
        ``text``, else ``(False, None)``.

        First match wins; the returned name is which eval set the doc collided
        with (drives the per-set removal report).
        """
        words = _words(text)
        n = len(words)
        if n == 0:
            return False, None
        for k in self._sizes:
            if n < k:
                continue
            bucket = self._by_size[k]
            for i in range(n - k + 1):
                h = _hash_gram(tuple(words[i : i + k]))
                hit = bucket.get(h)
                if hit is not None:
                    return True, hit
        return False, None


def write_report(
    source_counts: dict[str, dict[str, int]],
    report_path: str | Path = DEFAULT_REPORT_PATH,
) -> None:
    """Append per-source removal counts to the JSON report, replica-safe.

    ``source_counts`` maps ``source -> {eval_set_name: n_removed, ...}``. Counts
    are merged (added) into any existing report under an exclusive file lock, so
    two curator replicas finishing shards at the same time don't lose updates.
    """
    if not source_counts:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Open r+ (create if missing), lock, read-modify-write, unlock.
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if _HAVE_FCNTL:
            fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(fd, "r+", encoding="utf-8") as f:
            raw = f.read()
            try:
                current = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                current = {}
            if not isinstance(current, dict):
                current = {}
            for source, counts in source_counts.items():
                dst = current.setdefault(source, {})
                for name, n in counts.items():
                    dst[name] = int(dst.get(name, 0)) + int(n)
            f.seek(0)
            f.truncate()
            json.dump(current, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        # fd is closed by fdopen context manager (releases the flock too).
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
