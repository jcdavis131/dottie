---
pretty_name: OAPEN Open-Access Books (CC-BY sample)
license: cc-by-4.0
task_categories:
- text-generation
language:
- en
tags:
- books
- open-access
- scholarly
- long-context
- oapen
- doab
- dottie
size_categories:
- n<1K
configs:
- config_name: default
  data_files:
  - split: train
    path: oapen_open_books.jsonl
dataset_info:
  features:
  - name: handle
    dtype: string
  - name: item_url
    dtype: string
  - name: doi
    dtype: string
  - name: isbn
    dtype: string
  - name: title
    dtype: string
  - name: language
    dtype: string
  - name: license
    dtype: string
  - name: license_url
    dtype: string
  - name: nc
    dtype: bool
  - name: publisher
    dtype: string
  - name: subjects
    sequence: string
  - name: txt_url
    dtype: string
  - name: text_sha256
    dtype: string
  - name: text_chars
    dtype: int64
  - name: stored_chars
    dtype: int64
  - name: text
    dtype: string
  splits:
  - name: train
    num_examples: 10
  provenance_classification: REAL
---

# OAPEN Open-Access Books (CC-BY sample)

## Dataset Summary

Peer-reviewed, openly-licensed scholarly **books** pulled from
[OAPEN](https://library.oapen.org) — the open-access content host behind the
[Directory of Open Access Books (DOAB)](https://directory.doabooks.org). This is
the operator's "external validated sources" expansion (2026-07-24): real,
peer-reviewed, CC-licensed long-form text to ground the training corpus, filling
the gap left by `pes2o` (papers, not books). Structure modelled on
[The Stack v3](https://huggingface.co/datasets/HuggingFaceCode/stack-v3-train);
governance per `tasks/artifacts/data_provenance_SOP.md` and the clean-source
allowlist in `external_book_sources.md`.

This is a **10-book CC-BY sample** proving the pipeline + license discipline; the
puller scales to the full corpus. **Nothing auto-ingests this file** — audited
proposal artifact.

## Data Structure / Fields

One JSON object per line (JSONL). Row = one open-access book.

| field | type | meaning |
|---|---|---|
| handle | string | OAPEN handle (stable id / join key) |
| item_url | string | the book's OAPEN landing page |
| doi | string\|null | DOI of the book |
| isbn | string\|null | ISBN when present |
| title | string | book title (CC-BY attribution) |
| language | string | `dc.language` (English in this sample) |
| license | string | normalized license code — **CC-BY** for every row here |
| license_url | string | the exact `dc.rights` Creative Commons URL |
| nc | bool | NonCommercial license? (always false here; only true under `--allow-nc`) |
| publisher | string\|null | publisher / imprint (CC-BY attribution) |
| subjects | list[string] | subject tags from OAPEN metadata |
| txt_url | string | OAPEN `.pdf.txt` bitstream the text came from |
| text_sha256 | string | sha256 of the **full** book text (pins it even when excerpted) |
| text_chars | int64 | length of the full book text |
| stored_chars | int64 | chars stored in `text` (12,000 excerpt in this sample; full with `--full`) |
| text | string | the book text (excerpt in this sample) |

## Splits

| split | rows | coverage |
|---|---|---|
| train | 10 | English CC-BY scholarly books; 39 records scanned, 29 excluded by license |

## Dataset Creation

### Source data
OAPEN public REST API (`library.oapen.org/rest`), read-only, via
`apps/dottie/scripts/pull_oapen_books.py` (stdlib-only). Text is OAPEN's own
pre-extracted `.pdf.txt` bitstream per book (no PDF parsing). Query:
`dc.rights:*creativecommons* AND dc.language:English`.

### License verification (the provenance gate)
Every book's `dc.rights` is parsed and gated. Included: **CC-BY / CC-BY-SA / CC0**
(permissive, derivatives allowed). **Always excluded: any `*-ND`** (NoDerivatives
— training a model is a derivative use) and books with **no `dc.rights`**
(gratis OA is not an open license). **NonCommercial (`*-NC`)** is excluded by
default (opt-in via `--allow-nc`, flagged `nc=true`). In this pull, 10 of 39
scanned passed — all CC-BY; 10 were ND and 19 were NC. Per-book license + full
text sha256 in `oapen_open_books_audit.md`.

### Provenance classification
**REAL** — real, peer-reviewed, openly-licensed books from a real public
repository, each license verified and recorded. See `data_provenance_SOP.md`.

### Decontamination (required before training)
Not yet run. Before any training use, run the eval/held-out decontamination
(13-gram overlap vs the held-out stems, per `build_eval_data.py`) — this text is
new to the corpus and must be checked disjoint from the eval bins.

### Personal and sensitive information
None beyond public authorship/publication metadata. Public scholarly monographs.

## Considerations for Using the Data

1. **Excerpt, not full text, in this sample.** `text` holds the first 12,000
   chars per book; `text_sha256` + `text_chars` pin the full text. Regenerate
   complete texts with `--full` for real training.
2. **CC-BY requires attribution.** The `title` + `publisher` + `license_url` +
   `doi` travel with every row so attribution is preserved through training/use.
3. **Scholarly, humanities/social-science-skewed.** OAPEN's frontlist skews HSS
   (history, area studies, education); broaden the query for balance.
4. **English-only in this sample.** OAPEN is multilingual; widen `dc.language`
   for other languages.
5. **License codes are normalized from `dc.rights` URLs** — verify the exact URL
   (`license_url`) if a downstream use is license-sensitive.

## Licensing
Every book is **CC-BY 4.0** (see each row's `license_url`); the puller + the
derived table are MIT. Solo personal project, no connection to employer, built
with public/free-tier only.

## Citation
OAPEN / DOAB open-access books, pulled 2026-07-24 (read-only). Regenerate:
`python apps/dottie/scripts/pull_oapen_books.py --target 10 --out <dir>`
(add `--full` for complete texts, `--allow-nc` to include NonCommercial).
