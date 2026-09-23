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
python3 apps/arxiviq-factory/run.py skillify [--limit N] [--since-year Y]  # papers -> sources/paper_skills/<id>/ + paper_skills.jsonl.gz
python3 apps/arxiviq-factory/run.py teacher prepare  # batches + BRIEF.md for teacher agents -> data/teacher/
python3 apps/arxiviq-factory/run.py teacher prepare --fulltext  # batches + BRIEF_FULLTEXT.md, reads paper packages -> data/teacher/fulltext/
python3 apps/arxiviq-factory/run.py teacher ingest data/teacher/out/*.jsonl --teacher <model>
python3 apps/arxiviq-factory/run.py teacher prepare-revision   # batches of questions whose wrong options are too short
python3 apps/arxiviq-factory/run.py teacher ingest-revision data/teacher/revise_out/*.jsonl
python3 apps/arxiviq-factory/run.py curate           # -> data/packs/arxiviq-pack-1/ + PACK_MANIFEST.json + sample/
```

Stdlib only (network via `curl`). `sources/` holds the committed snapshots the
packs are rebuilt from; `data/` is gitignored and regenerable with `curate`.
The one non-stdlib step, skillify's PDF extraction, shells out to the approved
external tool `paper_bundle.py` (Paper2Agent, MIT) via `PAPER_BUNDLE`; nothing
from it is vendored into this tree.

| Stage | Source | What it adds |
|---|---|---|
| harvest | arXiv API | 10 topics × (90 most relevant + 60 most recent): title, abstract, authors, categories, dates, comment, journal ref. No fallback or templated papers; a topic that fails contributes nothing and is listed in `harvest_stats.json`. |
| enrich | Semantic Scholar batch API | citations, influential citations, venue and venue type, author ids and h-index |
| | arXiv HTML | per-author affiliation lines from the paper's own header, kept only where the LaTeXML block names each author separately and the name matches the arXiv author list; others are marked `unstructured`, not guessed |
| | ROR | affiliation string → organisation (ROR id, type such as company or education, country), accepted only when ROR marks the match `chosen` |
| enrich `--openalex` | OpenAlex | authorships with institutions already linked to ROR, filling only authors the sources above left empty. A separate pass because the keyless budget is shared per IP (it resets at midnight UTC); set `OPENALEX_API_KEY` (free) to run it any time. |
| skillify | the paper's own PDF | a verified paper-skill package per paper: section-continuous text (`references/paper.md`), embedded figure crops, machine-readable table CSVs, bibliography. Covers papers with no arXiv/ar5iv HTML conversion. Committed to `sources/paper_skills/` for provenance; `reviewed:false` in `sources/paper_skills.jsonl.gz` until the review-aid queue is adjudicated and the package rebuilt. |
| teacher | an LLM teacher | per paper, from the abstract only: two 4-option comprehension questions with one correct answer, the paper type, and whether code or data are released. Records are validated and rejected, never repaired. |
| teacher `--fulltext` | an LLM teacher | per skillified paper, from the FULL paper text: two 4-option questions answerable ONLY from the paper body (never from the abstract alone), one figure-reading question, one table-reading question, each citing its source (section/figure/table). |

### Skillify decisions (Cameron, 2026-09-23)

1. **Storage**: packages committed to `sources/paper_skills/` for provenance (~7 MB/paper), not gitignored.
2. **Machine**: skillify runs on the Hatch VM (PDF deps installed there); results pass out via git.
3. **Subset**: most-recent-first, via `--limit N` and `--since-year Y`.
4. **State budget**: dynamic by complexity. `complexity = chars(paper.md) + 2,000 × sections + 3,000 × (figures + tables)`.
   Tiers: **full** (≤60k) → whole paper.md; **sections** (≤300k) → intro/methods/results/discussion sections
   at full length (heading-keyword match; whole text if nothing matches — prefer more, never less);
   **window** (above) → first 60k + last 20k chars of those sections with an explicit truncation marker.
   Figure/table caption lines always travel with every tier. Recorded per paper as `state_tier` in the manifest.
5. **paper2mcp**: deferred — tool-use trajectories stay a later pilot, nothing built here.

### Planned fulltext decision families

Not yet in `curate` — sketched here, to be wired when fulltext teacher records exist:

| Family | Type | State | Label from |
|---|---|---|---|
| teacher_quiz_fulltext | choice | title, abstract, paper body (state budget applies) | teacher question, options A–D, length-debiased (`llm-teacher`, `--fulltext`) |
| figure_reading | choice | figure crop + caption + nearby text | teacher question (`llm-teacher`, `--fulltext`) |
| table_reading | choice | table CSV + caption | teacher question (`llm-teacher`, `--fulltext`) |

All `label_source: "llm-teacher"` (teacher-written, not published fact). The same debias
pipeline applies: seeded answer-position shuffle, distractor revision, length-balance thinning.
"States never carry their own answer" still holds: the state includes the body text but not
the figure/table/section the question quotes.

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
