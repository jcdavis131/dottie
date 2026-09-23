"""Stage 3: decision families built from each paper and its metadata.

Every family is a question the model answers from a `state` that never
contains its own answer. Labels come from published metadata or recorded
outcomes, never from invention:

  family            type    state                         label from
  topic             choice  title, abstract               which tracked search found it (single-topic papers only)
  category          choice  title, abstract               arXiv primary category (author-chosen)
  cross_list        noul    title, abstract               arXiv cross-listing, one category per row
  peer_reviewed     noul    title, abstract, year         Semantic Scholar venue type or arXiv journal_ref (papers >= 1 year old)
  venue             choice  title, abstract, year         Semantic Scholar venue, top venues + other (peer-reviewed papers)
  impact            score   title, abstract, year         Semantic Scholar citations per year since posting (papers >= 1 year old)
  industry          noul    title, abstract, authors      any author affiliation ROR types as company (>= 75% of authors' affiliations known)
  first_country     choice  title, abstract, authors      country of the first author's ROR-matched institution
  teacher_quiz      choice  title, abstract               LLM-teacher comprehension question, length-balanced and thinned so the longest option scores chance (llm-teacher)
  contribution      choice  title, abstract               LLM-teacher paper type (label_source llm-teacher)
  code_release      noul    title, abstract               LLM-teacher reading of the abstract (label_source llm-teacher)

Nimble contrastive pairs (≤ 8-word flips) are mined, not generated: the same
paper and the same question asked about a real positive (an author, an
institution, a category the paper has) and a real hard negative (one that
co-occurs in the same topic but is not on this paper). Only the candidate
string differs between the two rows, and the label flips. Both rows share a
pair_id so a holdout split never separates them.

  author_of        noul    title, abstract, candidate author
  institution_of   noul    title, abstract, authors, candidate institution
  listed_in        noul    title, abstract, candidate arXiv category

Rows are jev-decision-schema-1.0.0 records; where each label came from lives
in a sidecar record keyed by the row id (curate.py), never in the state.
"""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from . import SCHEMA_ID
from .common import stable_id
from .harvest import TOPIC_LABELS
from .teacher import CONTRIBUTIONS, LETTERS, length_balanced

if TYPE_CHECKING:
    from collections.abc import Iterator

ABSTRACT_MAX = 1600
AUTHORS_MAX = 12
NIMBLE_MAX_WORDS = 8
# industry=no is only claimed when most authors' affiliations are known.
INDUSTRY_MIN_COVERAGE = 0.75

# Human names for the arXiv categories that recur in this corpus.
CATEGORY_NAMES = {
    "cs.LG": "Machine Learning",
    "cs.CV": "Computer Vision and Pattern Recognition",
    "cs.AI": "Artificial Intelligence",
    "cs.CL": "Computation and Language",
    "cs.RO": "Robotics",
    "cs.NE": "Neural and Evolutionary Computing",
    "stat.ML": "Machine Learning (Statistics)",
    "q-bio.NC": "Neurons and Cognition",
    "eess.IV": "Image and Video Processing",
    "eess.SY": "Systems and Control",
    "physics.comp-ph": "Computational Physics",
    "math.OC": "Optimization and Control",
    "cs.SD": "Sound",
    "eess.AS": "Audio and Speech Processing",
    "cs.MA": "Multiagent Systems",
    "cs.IR": "Information Retrieval",
    "math.DS": "Dynamical Systems",
    "cs.GR": "Graphics",
}

IMPACT_LEVELS = ["under 1 citation a year", "1 to 5 a year", "5 to 20 a year", "20 to 100 a year", "over 100 a year"]
IMPACT_EDGES = [1.0, 5.0, 20.0, 100.0]


def _now() -> datetime:
    return datetime.now(UTC)


def years_since(iso: str, now: datetime) -> float:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (now - t).days / 365.25)


def base_state(p: dict[str, Any], *, year: bool = False, authors: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"title": p["title"], "abstract": p["abstract"][:ABSTRACT_MAX]}
    if year:
        s["posted"] = p["published"][:4]
    if authors is not None:
        s["authors"] = ", ".join(authors[:AUTHORS_MAX]) + (f" and {len(authors) - AUTHORS_MAX} more" if len(authors) > AUTHORS_MAX else "")
    return s


def row(family: str, p: dict[str, Any], state: dict[str, Any], qid: str, question: dict[str, Any], label: dict[str, Any], *, label_source: str, pair_id: str | None = None, salt: str = "") -> dict[str, Any]:
    rid = f"arxiviq-{family}-{stable_id(p['arxiv_id'], family, qid, salt)}"
    return {
        "record": {"schema": SCHEMA_ID, "id": rid, "state": state, "questions": {qid: question}, "labels": {qid: label}},
        "meta": {"id": rid, "family": family, "arxiv_id": p["arxiv_id"], "label_source": label_source, "pair_id": pair_id, "topics": p.get("topics", [])},
    }


def words(s: str) -> int:
    return len(re.findall(r"\S+", s))


class Corpus:
    """Papers joined with enrichment, ROR matches and teacher answers."""

    def __init__(self, papers: list[dict[str, Any]], enrich: list[dict[str, Any]], ror: list[dict[str, Any]], teacher: list[dict[str, Any]], now: datetime | None = None):
        self.now = now or _now()
        self.papers = papers
        self.enrich = {e["arxiv_id"]: e for e in enrich}
        self.ror = {r["affiliation"]: r.get("match") for r in ror}
        self.teacher = {t["arxiv_id"]: t for t in teacher}

    def institutions(self, aid: str) -> list[dict[str, Any]]:
        """ROR-matched institutions of a paper, in author order, deduplicated."""
        e = self.enrich.get(aid)
        out, seen = [], set()
        for a in (e or {}).get("authors", []):
            for aff in a.get("affiliations", []):
                m = self.ror.get(aff)
                if m and m.get("ror") and m["ror"] not in seen:
                    seen.add(m["ror"])
                    out.append(m)
        return out

    def affiliation_coverage(self, aid: str) -> float:
        e = self.enrich.get(aid)
        if not e or not e.get("authors"):
            return 0.0
        return sum(1 for a in e["authors"] if a.get("affiliations")) / len(e["authors"])


def fam_topic(c: Corpus) -> Iterator[dict[str, Any]]:
    q = {"type": "choice", "instructions": "Which research topic is this paper about?", "criteria": dict(TOPIC_LABELS)}
    for p in c.papers:
        if len(p.get("topics", [])) != 1:
            continue  # found by several searches: no single right answer
        yield row("topic", p, base_state(p), "topic", q, {"type": "choice", "choice": p["topics"][0]}, label_source="arxiv-search-retrieval")


def top_categories(c: Corpus, k: int = 10) -> list[str]:
    counts = Counter(p["primary_category"] for p in c.papers)
    return [cat for cat, _ in counts.most_common(k)]


def fam_category(c: Corpus) -> Iterator[dict[str, Any]]:
    cats = top_categories(c)
    crit = {cat: CATEGORY_NAMES.get(cat, cat) for cat in cats}
    crit["other"] = "Any other arXiv category"
    q = {"type": "choice", "instructions": "Which arXiv category did the authors file this paper under as its primary?", "criteria": crit}
    for p in c.papers:
        label = p["primary_category"] if p["primary_category"] in cats else "other"
        yield row("category", p, base_state(p), "category", q, {"type": "choice", "choice": label}, label_source="arxiv-metadata")


def fam_cross_list(c: Corpus, seed: int) -> Iterator[dict[str, Any]]:
    """One cross-listing question per paper, about a common secondary category, balanced over yes and no."""
    rng = random.Random(seed)
    targets = [cat for cat in ("cs.CV", "cs.RO", "cs.AI", "stat.ML", "cs.NE", "q-bio.NC") if cat in CATEGORY_NAMES]
    for p in c.papers:
        secondary = set(p["categories"]) - {p["primary_category"]}
        yes = [t for t in targets if t in secondary]
        no = [t for t in targets if t not in p["categories"]]
        pool = yes if (yes and rng.random() < 0.5) or not no else no
        if not pool:
            continue
        t = rng.choice(pool)
        q = {"type": "noul", "instructions": f"Is this paper also cross-listed in the arXiv category {CATEGORY_NAMES[t]} ({t})?"}
        yield row("cross_list", p, base_state(p), "cross_listed", q, {"type": "noul", "noul": 1.0 if t in secondary else 0.0}, label_source="arxiv-metadata", salt=t)


def reviewed(p: dict[str, Any], e: dict[str, Any] | None) -> bool | None:
    s2 = (e or {}).get("s2")
    if p.get("journal_ref"):
        return True
    if not s2:
        return None
    return s2.get("venue_type") in ("conference", "journal")


def fam_peer_reviewed(c: Corpus) -> Iterator[dict[str, Any]]:
    q = {"type": "noul", "instructions": "Has this paper appeared at a peer-reviewed conference or in a journal?"}
    for p in c.papers:
        if years_since(p["published"], c.now) < 1.0:
            continue  # too new for the outcome to be known
        r = reviewed(p, c.enrich.get(p["arxiv_id"]))
        if r is None:
            continue
        yield row("peer_reviewed", p, base_state(p, year=True), "peer_reviewed", q, {"type": "noul", "noul": 1.0 if r else 0.0}, label_source="semantic-scholar+arxiv-journal-ref")


def venue_key(e: dict[str, Any] | None) -> str | None:
    s2 = (e or {}).get("s2") or {}
    if s2.get("venue_type") not in ("conference", "journal"):
        return None
    name = (s2.get("venue_name") or s2.get("venue") or "").strip()
    return name or None


def fam_venue(c: Corpus, k: int = 8) -> Iterator[dict[str, Any]]:
    counts = Counter(v for p in c.papers if (v := venue_key(c.enrich.get(p["arxiv_id"]))))
    tops = [v for v, n in counts.most_common(k) if n >= 5]
    if len(tops) < 2:
        return
    keys = {v: re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")[:48] for v in tops}
    crit = {keys[v]: v for v in tops}
    crit["other"] = "Another peer-reviewed venue"
    q = {"type": "choice", "instructions": "Where was this paper published?", "criteria": crit}
    for p in c.papers:
        v = venue_key(c.enrich.get(p["arxiv_id"]))
        if not v:
            continue
        yield row("venue", p, base_state(p, year=True), "venue", q, {"type": "choice", "choice": keys.get(v, "other")}, label_source="semantic-scholar")


def impact_level(cites: int, years: float) -> int:
    rate = cites / max(years, 1.0)
    return sum(1 for edge in IMPACT_EDGES if rate >= edge)


def fam_impact(c: Corpus) -> Iterator[dict[str, Any]]:
    q = {"type": "score", "instructions": "How often has this paper been cited per year since it was posted?", "criteria": list(IMPACT_LEVELS)}
    for p in c.papers:
        yrs = years_since(p["published"], c.now)
        s2 = (c.enrich.get(p["arxiv_id"]) or {}).get("s2") or {}
        if yrs < 1.0 or s2.get("citation_count") is None:
            continue
        yield row("impact", p, base_state(p, year=True), "impact", q, {"type": "score", "score": float(impact_level(int(s2["citation_count"]), yrs))}, label_source="semantic-scholar-outcome")


def author_names(c: Corpus, p: dict[str, Any]) -> list[str]:
    return [a["name"] for a in p["authors"]]


def fam_industry(c: Corpus) -> Iterator[dict[str, Any]]:
    q = {"type": "noul", "instructions": "Is at least one author affiliated with a company (industry lab)?"}
    for p in c.papers:
        if c.affiliation_coverage(p["arxiv_id"]) < INDUSTRY_MIN_COVERAGE:
            continue  # too little known to say no
        insts = c.institutions(p["arxiv_id"])
        if not insts:
            continue
        company = any("company" in (m.get("types") or []) for m in insts)
        yield row("industry", p, base_state(p, authors=author_names(c, p)), "industry", q, {"type": "noul", "noul": 1.0 if company else 0.0}, label_source="arxiv-html-affiliation+ror")


def first_institution(c: Corpus, aid: str) -> dict[str, Any] | None:
    e = c.enrich.get(aid)
    if not e or not e.get("authors"):
        return None
    for aff in e["authors"][0].get("affiliations", []):
        m = c.ror.get(aff)
        if m and m.get("country"):
            return m
    return None


def fam_first_country(c: Corpus, k: int = 10) -> Iterator[dict[str, Any]]:
    firsts = {p["arxiv_id"]: m for p in c.papers if (m := first_institution(c, p["arxiv_id"]))}
    counts = Counter(m["country"] for m in firsts.values())
    tops = [cc for cc, n in counts.most_common(k) if n >= 5]
    if len(tops) < 2:
        return
    names = {m["country"]: m.get("country_name") or m["country"] for m in firsts.values()}
    crit = {cc: names[cc] for cc in tops}
    crit["other"] = "Another country"
    q = {"type": "choice", "instructions": "In which country is the first author's institution?", "criteria": crit}
    for p in c.papers:
        m = firsts.get(p["arxiv_id"])
        if not m:
            continue
        yield row("first_country", p, base_state(p, authors=author_names(c, p)), "first_country", q, {"type": "choice", "choice": m["country"] if m["country"] in tops else "other"}, label_source="arxiv-html-affiliation+ror")


def length_rank(q: dict[str, Any]) -> int:
    """Where the right option falls when options are sorted longest first (0 = longest; ties go against it)."""
    right = len(q["options"][q["answer"]])
    return sum(1 for k, v in q["options"].items() if k != q["answer"] and len(v) >= right)


def _unit(*parts: str) -> float:
    """A stable number in [0, 1) from the parts, for deterministic thinning."""
    return int(stable_id(*parts)[:8], 16) / 0x100000000


def quiz_keep(c: Corpus) -> set[tuple[str, int]]:
    """Length-balanced teacher questions, thinned so "pick the longest option" scores chance.

    Balancing keeps every option within 20% of the right one's length, but the
    right option is still the longest more often than 1 in 4. Every question
    whose right option is not the longest is kept; those where it is are kept at
    the rate that brings rank 0 down to the mean of the other ranks.
    """
    ranked = [(p_id, i, length_rank(q)) for p_id, t in c.teacher.items() for i, q in enumerate(t["questions"]) if length_balanced(q)]
    by_rank = Counter(r for _, _, r in ranked)
    others = [by_rank[r] for r in range(1, len(LETTERS))]
    rate = min(1.0, (sum(others) / len(others)) / by_rank[0]) if by_rank[0] else 1.0
    return {(p_id, i) for p_id, i, r in ranked if r > 0 or _unit(p_id, str(i), "quiz-thin") < rate}


def fam_teacher(c: Corpus) -> Iterator[dict[str, Any]]:
    keep = quiz_keep(c)
    contrib_q = {"type": "choice", "instructions": "What kind of paper is this?", "criteria": dict(CONTRIBUTIONS)}
    code_q = {"type": "noul", "instructions": "Does the abstract say code, data or model weights are released?"}
    for p in c.papers:
        t = c.teacher.get(p["arxiv_id"])
        if not t:
            continue
        src = f"llm-teacher:{t['teacher']}"
        for i, q in enumerate(t["questions"]):
            if (p["arxiv_id"], i) not in keep:
                continue  # unbalanced, or thinned so the longest option is no giveaway
            question = {"type": "choice", "instructions": q["prompt"][:512], "criteria": {k: q["options"][k][:256] for k in LETTERS}}
            yield row("teacher_quiz", p, base_state(p), "answer", question, {"type": "choice", "choice": q["answer"]}, label_source=src, salt=str(i))
        yield row("contribution", p, base_state(p), "contribution", contrib_q, {"type": "choice", "choice": t["contribution"]}, label_source=src)
        yield row("code_release", p, base_state(p), "code_release", code_q, {"type": "noul", "noul": float(t["code_release"])}, label_source=src)


def _pairs(family: str, p: dict[str, Any], state: dict[str, Any], qid: str, template: str, pos: str, neg: str, label_source: str) -> Iterator[dict[str, Any]]:
    """A Nimble pair: same paper, same question, one real positive and one real hard negative."""
    pid = f"nimble-{family}-{stable_id(p['arxiv_id'], family, pos, neg)}"
    for cand, lab in ((pos, 1.0), (neg, 0.0)):
        q = {"type": "noul", "instructions": template.format(candidate=cand)}
        yield row(family, p, state, qid, q, {"type": "noul", "noul": lab}, label_source=label_source, pair_id=pid, salt=cand)


def nimble_author(c: Corpus, seed: int) -> Iterator[dict[str, Any]]:
    """Is <author> an author? Negatives are authors who publish in the same topic but not on this paper."""
    rng = random.Random(seed)
    by_topic: dict[str, Counter] = defaultdict(Counter)
    for p in c.papers:
        for t in p.get("topics", []):
            for a in p["authors"]:
                by_topic[t][a["name"]] += 1
    for p in c.papers:
        mine = {a["name"] for a in p["authors"]}
        pos_pool = [n for n in mine if words(n) <= NIMBLE_MAX_WORDS]
        cands = [n for t in p.get("topics", []) for n, k in by_topic[t].most_common(60) if n not in mine and words(n) <= NIMBLE_MAX_WORDS]
        if not pos_pool or not cands:
            continue
        yield from _pairs("author_of", p, base_state(p), "author_of", "Is {candidate} one of the authors of this paper?", rng.choice(sorted(pos_pool)), rng.choice(cands), "arxiv-metadata")


def nimble_institution(c: Corpus, seed: int) -> Iterator[dict[str, Any]]:
    """Is <institution> among the authors' affiliations? Negatives come from the same topic."""
    rng = random.Random(seed + 1)
    by_topic: dict[str, Counter] = defaultdict(Counter)
    for p in c.papers:
        for m in c.institutions(p["arxiv_id"]):
            for t in p.get("topics", []):
                by_topic[t][m["name"]] += 1
    for p in c.papers:
        insts = [m["name"] for m in c.institutions(p["arxiv_id"]) if m.get("name") and words(m["name"]) <= NIMBLE_MAX_WORDS]
        if not insts:
            continue
        mine = set(insts)
        cands = [n for t in p.get("topics", []) for n, _ in by_topic[t].most_common(40) if n not in mine and words(n) <= NIMBLE_MAX_WORDS]
        if not cands:
            continue
        state = base_state(p, authors=author_names(c, p))
        yield from _pairs("institution_of", p, state, "institution_of", "Is {candidate} among the authors' institutions?", rng.choice(sorted(insts)), rng.choice(cands), "arxiv-html-affiliation+ror")


def nimble_category(c: Corpus, seed: int) -> Iterator[dict[str, Any]]:
    """Is the paper listed in <category>? Negatives are categories common in the corpus that it is not in."""
    rng = random.Random(seed + 2)
    common = [cat for cat in top_categories(c, 12) if cat in CATEGORY_NAMES]
    for p in c.papers:
        pos = [cat for cat in p["categories"] if cat in CATEGORY_NAMES]
        neg = [cat for cat in common if cat not in p["categories"]]
        if not pos or not neg:
            continue
        a, b = rng.choice(pos), rng.choice(neg)
        yield from _pairs("listed_in", p, base_state(p), "listed_in", "Is this paper listed in the arXiv category {candidate}?", f"{CATEGORY_NAMES[a]} ({a})", f"{CATEGORY_NAMES[b]} ({b})", "arxiv-metadata")


FAMILIES = {
    "topic": lambda c, s: fam_topic(c),
    "category": lambda c, s: fam_category(c),
    "cross_list": fam_cross_list,
    "peer_reviewed": lambda c, s: fam_peer_reviewed(c),
    "venue": lambda c, s: fam_venue(c),
    "impact": lambda c, s: fam_impact(c),
    "industry": lambda c, s: fam_industry(c),
    "first_country": lambda c, s: fam_first_country(c),
    "teacher": lambda c, s: fam_teacher(c),
    "author_of": nimble_author,
    "institution_of": nimble_institution,
    "listed_in": nimble_category,
}


def build(c: Corpus, seed: int = 20260923) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fn in FAMILIES.values():
        out.extend(fn(c, seed))
    return out
