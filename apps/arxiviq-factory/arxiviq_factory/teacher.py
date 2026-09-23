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
options are rejected, never repaired) and snapshots the accepted answers to
sources/teacher.jsonl.gz with the teacher named on every record. Labels from
this stage are teacher-written, not published facts, and rows built from them
say so (label_source "llm-teacher").
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .common import DATA, SOURCES, read_jsonl, write_jsonl

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
                "questions": [{"prompt": q["prompt"].strip(), "options": {k: str(q["options"][k]).strip() for k in LETTERS}, "answer": q["answer"]} for q in rec["questions"]],
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
    p2 = sub.add_parser("ingest")
    p2.add_argument("files", nargs="+", type=Path)
    p2.add_argument("--teacher", required=True, help="model that wrote the answers, recorded on every record")
    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        for p in prepare(args.batches, args.limit):
            print(p)
        return 0
    stats = ingest(args.files, args.teacher)
    (SOURCES / "teacher_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
