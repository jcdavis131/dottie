"""Stage 4: LLM-teacher questions about each paper, as the original arxiviq exam app did.

The exam app (jcdavis131/arxiv_exam_app) asked an LLM for rigorous
multiple-choice questions per paper and shuffled the choices. Here the teacher
works from the title and abstract only, so every question is answerable from
the state the model will see, and writes per paper:
  questions      two 4-option comprehension questions, one correct answer each
  contribution   what kind of paper it is (closed set CONTRIBUTIONS)
  code_release   1 if the abstract says code, data or weights are released, else 0

`prepare` writes batch files for teacher agents; `ingest` validates their JSONL
(unknown ids, wrong option sets, answers outside the options and duplicate
options are rejected, never repaired), shuffles each question's options with a
seeded permutation so the answer letter carries no signal, and snapshots the accepted answers to
sources/teacher.jsonl.gz with the teacher named on every record. Labels from
this stage are teacher-written, not published facts, and rows built from them
say so (label_source "llm-teacher").

`prepare-fulltext` is the variant for skillified papers: batch rows carry the
paper package path (references/paper.md) and figure/table captions instead of
just the abstract. The brief requires every question to be answerable ONLY from
the paper body — never from the abstract alone — and to cite its source
(section, figure, or table).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from .common import DATA, SOURCES, read_jsonl, write_jsonl
from . import skillify

CONTRIBUTIONS: dict[str, str] = {
    "method": "Proposes a new model, algorithm or training method",
    "benchmark": "Introduces a dataset, benchmark or evaluation protocol",
    "theory": "Mainly theoretical: proofs, bounds, formal analysis",
    "empirical": "Empirical study or analysis of existing methods",
    "survey": "Survey, review or tutorial",
    "application": "Applies known methods to a specific domain problem",
    "position": "Position, perspective or opinion paper",
}
LETTERS = ("A", "B", "C", "D")

TEACHER_BRIEF = """You are the teacher for a decision-model dataset. For EACH paper in the batch file,
read only its title and abstract and write one JSON object per line to the output file:

{"arxiv_id": "<id from the batch>",
 "questions": [
   {"prompt": "<question answerable from the abstract alone>",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "answer": "<A|B|C|D>"},
   {... a second question on a different aspect ...}
 ],
 "contribution": "<one of: method, benchmark, theory, empirical, survey, application, position>",
 "code_release": <1 if the abstract says code, data or weights are released or available, else 0>}

Rules:
- Exactly two questions per paper, testing understanding (method, finding, setting, claim), not trivia
  such as the title's wording, author names, or numbers the abstract only mentions in passing.
- Exactly one correct option. Distractors must be plausible to someone who skimmed, the same length and
  style as the answer, and not "all/none of the above". Vary which letter is correct.
- Each prompt under 300 characters, each option under 200 characters. Plain text, no markdown.
- Never use knowledge beyond the abstract. If an abstract is too thin for two questions, still write two
  that the abstract does support.
- Output strictly one JSON object per line, one line per paper, every paper in the batch, nothing else.
"""


REVISE_BRIEF = """You are revising distractors in a decision-model dataset. Each line of the batch file is one paper:
{"arxiv_id", "title", "abstract", "questions": [{"prompt", "options": {"A".."D"}, "answer"}, ...]}.

The first pass made the correct option longer and more detailed than the wrong ones, so a model could
answer by picking the longest option. For EACH question, rewrite ONLY the three wrong options so that:
- each wrong option is about as long as the correct one: within 20% of its character count (or within 12
  characters when the correct option is short), and as specific and detailed in style;
- each is still clearly wrong according to the abstract, and plausible to someone who skimmed it;
- the four options stay distinct; no "all/none of the above".
Do NOT change the prompt, the correct option's text, or which letter is correct.

Write one JSON object per line to the output file, every paper in the batch, same shape as the input
but without title and abstract: {"arxiv_id": ..., "questions": [{"prompt", "options", "answer"}, ...]}.
Output strictly JSONL, nothing else.
"""


FULLTEXT_BRIEF = """You are the teacher for a decision-model dataset. For EACH paper in the batch file,
read the FULL PAPER TEXT (references/paper.md at the given paper_md_path) and its figure
captions. The decision model at test time will see the paper text, not just the abstract.

Write one JSON object per line to the output file:

{"arxiv_id": "<id from the batch>",
 "questions_fulltext": [
   {"prompt": "<question answerable ONLY from the paper body>",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "answer": "<A|B|C|D>",
    "source": "<section 4.2 | Figure 3 | Table 1 — where the answer is grounded>"},
   {... a second question on a different aspect ...}
 ],
 "figure_reading": {"prompt": "<what the figure shows, what changes between panels, which curve or
     column supports the claim>", "options": {...}, "answer": "<A|B|C|D>", "source": "Figure N"},
 "table_reading": {"prompt": "<a value or trend that requires reading the table>",
     "options": {...}, "answer": "<A|B|C|D>", "source": "Table N"}}

Rules:
- Every question must be answerable from the paper body and NOT from the abstract alone.
  If a question can be answered from the abstract, discard it and write a deeper one.
- Each question cites its source (section, figure, or table); the answer must be
  checkable at that source.
- Exactly one correct option. Distractors must be plausible to someone who skimmed,
  the same length and style as the answer, and not "all/none of the above". Vary
  which letter is correct.
- Each prompt under 300 characters, each option under 200 characters. Plain text, no markdown.
- Never use knowledge beyond the paper package.
- Output strictly one JSON object per line, one line per paper, every paper in the batch, nothing else.
"""


def prepare_fulltext(n_batches: int, limit: int | None) -> list[Path]:
    """Batch files for the fulltext teacher: rows carry the paper package path, not the abstract."""
    papers = {p["arxiv_id"]: p for p in read_jsonl(SOURCES / "papers.jsonl.gz")}
    have = {r["arxiv_id"] for r in read_jsonl(SOURCES / "teacher_fulltext.jsonl.gz")}
    todo = []
    for row in sorted(read_jsonl(skillify.MANIFEST), key=lambda r: r["arxiv_id"]):
        aid = row["arxiv_id"]
        if aid in have or aid not in papers:
            continue
        paper_md = skillify.PKG_ROOT / aid / "references" / "paper.md"
        if not paper_md.is_file():
            continue
        todo.append((aid, papers[aid], paper_md))
    todo = todo[: limit or None]
    out_dir = DATA / "teacher" / "fulltext"
    out_dir.mkdir(parents=True, exist_ok=True)
    per = max(1, -(-len(todo) // n_batches))
    paths = []
    for b in range(n_batches):
        chunk = todo[b * per : (b + 1) * per]
        if not chunk:
            break
        p = out_dir / f"batch_{b:02d}.jsonl"
        rows = []
        for aid, paper, paper_md in chunk:
            captions = skillify.captions_from_text(paper_md.read_text(encoding="utf-8"))
            rows.append(
                {
                    "arxiv_id": aid,
                    "title": paper["title"],
                    "abstract": paper["abstract"],
                    "paper_md_path": str(paper_md),
                    "captions": captions,
                }
            )
        write_jsonl(p, rows)
        paths.append(p)
    (DATA / "teacher" / "fulltext" / "BRIEF_FULLTEXT.md").write_text(FULLTEXT_BRIEF, encoding="utf-8")
    return paths


def length_balanced(q: dict[str, Any]) -> bool:
    """No option gives the answer away by its length: every wrong option within 20% (or 12 chars) of the right one."""
    right = len(q["options"][q["answer"]])
    slack = max(0.2 * right, 12)
    return all(abs(len(v) - right) <= slack for k, v in q["options"].items() if k != q["answer"])


def prepare_revision(n_batches: int) -> list[Path]:
    papers = {p["arxiv_id"]: p for p in read_jsonl(SOURCES / "papers.jsonl.gz")}
    todo = [t for t in read_jsonl(SOURCES / "teacher.jsonl.gz") if not all(length_balanced(q) for q in t["questions"])]
    out_dir = DATA / "teacher" / "revise"
    out_dir.mkdir(parents=True, exist_ok=True)
    per = max(1, -(-len(todo) // n_batches))
    paths = []
    for b in range(n_batches):
        chunk = todo[b * per : (b + 1) * per]
        if not chunk:
            break
        p = out_dir / f"batch_{b:02d}.jsonl"
        write_jsonl(p, ({"arxiv_id": t["arxiv_id"], "title": papers[t["arxiv_id"]]["title"], "abstract": papers[t["arxiv_id"]]["abstract"], "questions": t["questions"]} for t in chunk))
        paths.append(p)
    (DATA / "teacher" / "REVISE_BRIEF.md").write_text(REVISE_BRIEF, encoding="utf-8")
    return paths


def ingest_revision(files: list[Path]) -> dict[str, Any]:
    """Accept revised distractors only where prompt, answer letter and answer text are unchanged and the lengths now balance."""
    keep = {r["arxiv_id"]: r for r in read_jsonl(SOURCES / "teacher.jsonl.gz")}
    stats: dict[str, int] = {"lines": 0, "questions_revised": 0}
    rejects: dict[str, int] = {}
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            stats["lines"] += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                rejects["invalid json"] = rejects.get("invalid json", 0) + 1
                continue
            cur = keep.get(rec.get("arxiv_id"))
            new_qs = rec.get("questions")
            if not cur or not isinstance(new_qs, list) or len(new_qs) != len(cur["questions"]):
                rejects["unknown paper or question count"] = rejects.get("unknown paper or question count", 0) + 1
                continue
            merged = []
            for old, new in zip(cur["questions"], new_qs, strict=True):
                ok = (
                    isinstance(new, dict)
                    and new.get("prompt") == old["prompt"]
                    and new.get("answer") == old["answer"]
                    and isinstance(new.get("options"), dict)
                    and sorted(new["options"]) == list(LETTERS)
                    and str(new["options"][old["answer"]]).strip() == old["options"][old["answer"]]
                )
                cand = {"prompt": old["prompt"], "options": {k: str(new["options"][k]).strip() for k in LETTERS}, "answer": old["answer"]} if ok else None
                why = None if ok else "prompt, answer or answer text changed"
                if cand and len({v.lower() for v in cand["options"].values()}) != 4:
                    why = "duplicate option"
                elif cand and not length_balanced(cand):
                    why = "still unbalanced"
                if why:
                    rejects[why] = rejects.get(why, 0) + 1
                    merged.append(old)
                else:
                    merged.append(cand)
                    stats["questions_revised"] += 1
            cur["questions"] = merged
            cur["distractors_revised"] = True
    write_jsonl(SOURCES / "teacher.jsonl.gz", sorted(keep.values(), key=lambda r: r["arxiv_id"]))
    qs = [q for r in keep.values() for q in r["questions"]]
    stats["balanced"] = sum(1 for q in qs if length_balanced(q))
    stats["questions"] = len(qs)
    stats["correct_is_longest"] = sum(1 for q in qs if max(q["options"].values(), key=len) == q["options"][q["answer"]])
    return {**stats, "rejected": rejects}


def prepare(n_batches: int, limit: int | None) -> list[Path]:
    papers = read_jsonl(SOURCES / "papers.jsonl.gz")
    have = {r["arxiv_id"] for r in read_jsonl(SOURCES / "teacher.jsonl.gz")}
    todo = [p for p in papers if p["arxiv_id"] not in have][: limit or None]
    out_dir = DATA / "teacher" / "batches"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    per = max(1, -(-len(todo) // n_batches))
    for b in range(n_batches):
        chunk = todo[b * per : (b + 1) * per]
        if not chunk:
            break
        p = out_dir / f"batch_{b:02d}.jsonl"
        write_jsonl(p, ({"arxiv_id": x["arxiv_id"], "title": x["title"], "abstract": x["abstract"]} for x in chunk))
        paths.append(p)
    (DATA / "teacher" / "BRIEF.md").write_text(TEACHER_BRIEF, encoding="utf-8")
    return paths


def shuffle_options(q: dict[str, Any], seed: str) -> dict[str, Any]:
    """Re-letter a question's options with a permutation seeded by the paper and question.

    Teachers favour some letters for the right answer (one batch put 160 of
    312 answers on B); like the exam app, the options are shuffled so the
    letter carries no signal. Only positions change, never text.
    """
    texts = [q["options"][k] for k in LETTERS]
    order = list(range(len(LETTERS)))
    random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)).shuffle(order)
    options = {LETTERS[new]: texts[old] for new, old in enumerate(order)}
    answer = LETTERS[order.index(LETTERS.index(q["answer"]))]
    return {"prompt": q["prompt"], "options": options, "answer": answer}


def check(rec: Any, known: set[str]) -> str | None:
    """Why a teacher record is rejected, or None when it is sound."""
    if not isinstance(rec, dict):
        return "not an object"
    if rec.get("arxiv_id") not in known:
        return "unknown arxiv_id"
    qs = rec.get("questions")
    if not isinstance(qs, list) or len(qs) != 2:
        return "needs exactly two questions"
    for q in qs:
        if not isinstance(q, dict) or not isinstance(q.get("prompt"), str) or not 10 <= len(q["prompt"]) <= 400:
            return "bad prompt"
        opts = q.get("options")
        if not isinstance(opts, dict) or sorted(opts) != list(LETTERS):
            return "options must be exactly A-D"
        texts = [str(v).strip() for v in opts.values()]
        if any(not t or len(t) > 256 for t in texts) or len({t.lower() for t in texts}) != 4:
            return "empty, overlong or duplicate option"
        if q.get("answer") not in LETTERS:
            return "answer outside A-D"
    if rec.get("contribution") not in CONTRIBUTIONS:
        return "contribution outside the closed set"
    if rec.get("code_release") not in (0, 1):
        return "code_release must be 0 or 1"
    return None


def ingest(files: list[Path], teacher: str) -> dict[str, Any]:
    known = {p["arxiv_id"] for p in read_jsonl(SOURCES / "papers.jsonl.gz")}
    keep = {r["arxiv_id"]: r for r in read_jsonl(SOURCES / "teacher.jsonl.gz")}
    rejects: dict[str, int] = {}
    seen = 0
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip().strip("`")
            if not line or not line.startswith("{"):
                continue
            seen += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                rejects["invalid json"] = rejects.get("invalid json", 0) + 1
                continue
            why = check(rec, known)
            if why:
                rejects[why] = rejects.get(why, 0) + 1
                continue
            keep[rec["arxiv_id"]] = {
                "arxiv_id": rec["arxiv_id"],
                "questions": [
                    shuffle_options({"prompt": q["prompt"].strip(), "options": {k: str(q["options"][k]).strip() for k in LETTERS}, "answer": q["answer"]}, f"{rec['arxiv_id']}#{i}")
                    for i, q in enumerate(rec["questions"])
                ],
                "options_shuffled": True,
                "contribution": rec["contribution"],
                "code_release": rec["code_release"],
                "teacher": teacher,
                "source_file": f.name,
            }
    write_jsonl(SOURCES / "teacher.jsonl.gz", sorted(keep.values(), key=lambda r: r["arxiv_id"]))
    return {"lines": seen, "accepted_total": len(keep), "rejected": rejects, "papers": len(known), "coverage": round(len(keep) / max(1, len(known)), 3)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare")
    p1.add_argument("--batches", type=int, default=8)
    p1.add_argument("--limit", type=int)
    pf = sub.add_parser("prepare-fulltext", help="batches for the fulltext teacher (reads paper packages from skillify)")
    pf.add_argument("--batches", type=int, default=8)
    pf.add_argument("--limit", type=int)
    p3 = sub.add_parser("prepare-revision")
    p3.add_argument("--batches", type=int, default=8)
    p4 = sub.add_parser("ingest-revision")
    p4.add_argument("files", nargs="+", type=Path)
    p2 = sub.add_parser("ingest")
    p2.add_argument("files", nargs="+", type=Path)
    p2.add_argument("--teacher", required=True, help="model that wrote the answers, recorded on every record")
    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        for p in prepare(args.batches, args.limit):
            print(p)
        return 0
    if args.cmd == "prepare-fulltext":
        for p in prepare_fulltext(args.batches, args.limit):
            print(p)
        return 0
    if args.cmd == "prepare-revision":
        for p in prepare_revision(args.batches):
            print(p)
        return 0
    if args.cmd == "ingest-revision":
        stats = ingest_revision(args.files)
        (SOURCES / "teacher_revision_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(stats, indent=2))
        return 0
    stats = ingest(args.files, args.teacher)
    (SOURCES / "teacher_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
