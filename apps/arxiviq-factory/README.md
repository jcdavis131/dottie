# arxiviq-factory: System One decision datasets from arXiv papers

Training-ready `jev-decision-schema-1.0.0` packs for a Jev-like decision model
that reads papers: typed Choice, Score and Noul questions about each paper,
answered from a state that never contains its own answer. Built from real arXiv
papers on the topics arxiviq tracks, their authors and institutions, and
LLM-teacher questions in the style of the original arxiviq exam app. Nimble
contrastive pairs are mined from the same real metadata.

This tree compiles and curates data. It trains nothing, promotes nothing and
serves nothing: every pack is `consent.champion=false`, a HELPER input like the
`apps/dottie-os` packs. Training stays on the GPU host (`apps/jev-v0`).

## Stages

```bash
python3 apps/arxiviq-factory/run.py harvest          # arXiv API -> sources/papers.jsonl.gz
python3 apps/arxiviq-factory/run.py enrich           # Semantic Scholar + arXiv HTML + ROR -> sources/enrich.jsonl.gz, ror.jsonl.gz
python3 apps/arxiviq-factory/run.py enrich --openalex  # fill remaining affiliations from OpenAlex (budget or OPENALEX_API_KEY)
python3 apps/arxiviq-factory/run.py teacher prepare  # batches + BRIEF.md for teacher agents -> data/teacher/
python3 apps/arxiviq-factory/run.py teacher ingest data/teacher/out/*.jsonl --teacher <model>
python3 apps/arxiviq-factory/run.py teacher prepare-revision   # batches of questions whose wrong options are too short
python3 apps/arxiviq-factory/run.py teacher ingest-revision data/teacher/revise_out/*.jsonl
python3 apps/arxiviq-factory/run.py curate           # -> data/packs/arxiviq-pack-1/ + PACK_MANIFEST.json + sample/
```

Stdlib only (network via `curl`). `sources/` holds the committed snapshots the
packs are rebuilt from; `data/` is gitignored and regenerable with `curate`.

| Stage | Source | What it adds |
|---|---|---|
| harvest | arXiv API | 10 topics × (90 most relevant + 60 most recent): title, abstract, authors, categories, dates, comment, journal ref. No fallback or templated papers; a topic that fails contributes nothing and is listed in `harvest_stats.json`. |
| enrich | Semantic Scholar batch API | citations, influential citations, venue and venue type, author ids and h-index |
| | arXiv HTML | per-author affiliation lines from the paper's own header, kept only where the LaTeXML block names each author separately and the name matches the arXiv author list; others are marked `unstructured`, not guessed |
| | ROR | affiliation string → organisation (ROR id, type such as company or education, country), accepted only when ROR marks the match `chosen` |
| enrich `--openalex` | OpenAlex | authorships with institutions already linked to ROR, filling only authors the sources above left empty. A separate pass because the keyless budget is shared per IP (it resets at midnight UTC); set `OPENALEX_API_KEY` (free) to run it any time. |
| teacher | an LLM teacher | per paper, from the abstract only: two 4-option comprehension questions with one correct answer, the paper type, and whether code or data are released. Records are validated and rejected, never repaired. |

## Decision families

| Family | Type | State | Label from |
|---|---|---|---|
| topic | choice | title, abstract | the tracked search that found it (single-topic papers only) |
| category | choice | title, abstract | arXiv primary category |
| cross_list | noul | title, abstract | arXiv cross-listing |
| peer_reviewed | noul | title, abstract, year | Semantic Scholar venue type or arXiv journal ref (papers at least a year old) |
| venue | choice | title, abstract, year | Semantic Scholar venue, top venues + other |
| impact | score | title, abstract, year | citations per year since posting (papers at least a year old) |
| industry | noul | title, abstract, authors | any author at a ROR company (only when ≥ 75% of affiliations are known) |
| first_country | choice | title, abstract, authors | first author's ROR country |
| teacher_quiz | choice | title, abstract | teacher question, options A–D, length-debiased (`llm-teacher`) |
| contribution | choice | title, abstract | teacher paper type (`llm-teacher`) |
| code_release | noul | title, abstract | teacher reading of the abstract (`llm-teacher`) |

**Teacher questions are debiased before they train anything.** A first teacher
pass put the right answer in slot B too often and made it the longest option
86% of the time, so a model could score well without reading the paper. The
fixes, in order:

1. Answer letters are shuffled with a seeded per-question permutation.
2. A revision pass rewrites only the wrong options, never the prompt, the right
   option or the letter. A rewrite is accepted only if every wrong option is
   within 20% (or 12 characters) of the right one's length. Otherwise the old
   question is kept and dropped at curation.
3. Balanced questions are thinned: when the right option is still the longest,
   the question is kept only at the rate that makes "pick the longest" score
   chance (see `PACK_MANIFEST.json` for the counts).

`code_release` is the teacher's reading of the abstract. It is not always
consistent on "code will be released" phrasing, so it is a weak label.

**Nimble contrastive pairs** (flips of ≤ 8 words) are mined, never generated.
The pair is the same paper and the same question, asked about a real positive
and a real hard negative from the same topic that is not on this paper. Only
the candidate string differs and the label flips. Both rows share a `pair_id`
so the holdout never separates them.

| Pair family | Candidate | Hard negative |
|---|---|---|
| author_of | an author of the paper | a prolific author in the same topic |
| institution_of | an author's ROR institution | a frequent institution in the same topic |
| listed_in | an arXiv category the paper is in | a common category it is not in |

## The pack

`data/packs/arxiviq-pack-1/`:

- `train.jsonl`, `holdout.jsonl`: strict jev records (`schema, id, state, questions, labels` only), each validated by `apps/jev-v0/decision_io.validate_record`.
- `provenance.jsonl`: per row id, the family, the paper, `label_source`, `pair_id` and split. Where a label came from is kept out of the state.
- `MANIFEST.json`, also copied to `PACK_MANIFEST.json` here: counts by family, type, label source and split, label distributions, rejects by reason, and sha256 of every file and source snapshot.

Curation rules:

- **Decontaminate** with the dottie-os bench regex.
- **Validate** with the frozen jev-v0 validator.
- **Drop duplicates.** Where the same state and question carry different labels, drop every copy.
- **Drop Nimble orphans.** A pair that lost one side is removed.
- **Hold out whole papers**, at least 20% of the rows, so no paper and no pair straddles the split.

`sample/pack_sample.jsonl` holds two rows per family for review.

## Tests

```bash
python3 -m unittest discover -s apps/arxiviq-factory/tests -v
```

Offline, on a tiny in-memory corpus. The tests cover:

- Atom and HTML parsing.
- Teacher rejection reasons.
- Every row validating against jev-v0.
- States never carrying their own answer.
- Outcome labels needing a year to mature.
- The industry label refusing to say no on thin data.
- Nimble pairs flipping on one short, real candidate.
- The whole-paper holdout.
