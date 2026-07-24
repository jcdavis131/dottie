# Audit — oapen_open_books.jsonl

Corpus PROPOSAL only (external-source expansion, operator directive 2026-07-24:
"expand datasets to be grounded in external validated sources"). Nothing
auto-ingests this file; it is an audited artifact per the honesty doctrine.
Generated 2026-07-24. OAPEN was accessed strictly READ-ONLY via its public REST
API.

## Source + method

- **Source:** OAPEN (`library.oapen.org`), the open-access content host behind
  the Directory of Open Access Books (DOAB) — peer-reviewed scholarly books.
- **Puller:** `apps/dottie/scripts/pull_oapen_books.py` (stdlib-only, read-only).
- **Query:** `dc.rights:*creativecommons* AND dc.language:English`, paginated.
- **Text:** OAPEN's pre-extracted `.pdf.txt` bitstream per book (no PDF parsing);
  UTF-8, stripped. The committed sample stores the first 12,000 chars per book
  (`stored_chars`); `text_chars` + `text_sha256` pin the FULL text, regenerable
  with `--full`.

## License verification (the provenance gate)

Every book's `dc.rights` was parsed to a normalized license code and gated:

- **Included — 10 books, all CC-BY** (permissive; derivatives allowed).
- **Excluded — 29 of 39 scanned:**
  - **NoDerivatives (`*-ND`): 10** — an ND license forbids derivative works, and
    training a model on the text is a derivative use. Never included.
  - **NonCommercial (`*-NC`, `*-NC-SA`): 19** — excluded by default (the org has a
    revenue mission; NC is a legal gray area). Opt-in only via `--allow-nc`, and
    each such row would carry `nc=true`.
  - Books with no `dc.rights` are excluded upstream (gratis OA ≠ open license;
    cannot be classified REAL).

This 29/39 exclusion rate is the SOP working as intended: "verified sources"
means license-verified, not merely reachable.

## Per-book provenance (each full text hash-pinned)

| title | publisher | license | full chars | sha256 |
|---|---|---|---|---|
| Transforming Teaching in Higher Education | UJ Press | CC-BY | 801,634 | sha256=2e4bcfa49dbcec564157ec56d220850bb3de2144ca29dd9dd52478c1a056fa34 |
| Printing R-Evolution and Society 1450-1500 | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 2,365,602 | sha256=af3eb54301e758e1b22d5a75a872246234c8e90655c54970c530b2e9490038fd |
| Distributing Knowledge | Open Book Publishers | CC-BY | 395,379 | sha256=178a2740c940f5843c6d2d63d1976938c5dfb35756b0ccbc46bf0bf52f304701 |
| A Self-Reflexive Verista | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 388,510 | sha256=668fa644b4bb2b027d8bcefce45a37356b0de49a5d0d93c76a2cdc5f4b4dfd40 |
| Freemasonry and the Orient | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 285,549 | sha256=9116107b3d41db11c41e4b6fa853da8e5e3924b64610de029086d83e58a75005 |
| Vulnerable Workers in Times of Social Transformation | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 454,539 | sha256=305cf190bb98c3988d28c9e0453db3bfeb85a8fefde10277ac92f33eca9d7a56 |
| Venetians and Ottomans in the Early Modern Age | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 275,134 | sha256=58cc993614744338ebd63bed0c76748b080d8815102c51dbb09b70f13b3f2c09 |
| Between Texts, Beyond Words | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 268,705 | sha256=68adfd6a45dba3c797cc5eea83b1362bbb7e3817b1f9e2eb1677cd1ed400f192 |
| New Steps in Japanese Studies | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 425,279 | sha256=3847c839e7b2a05329b99b290033f386d27799438b567e1a0f525c04108fcc78 |
| The City of Ebla | Edizioni Ca’ Foscari – Venice University Press | CC-BY | 593,085 | sha256=edad82d71a2941715759f647076346fdadf346a4afc1ff9a7f1510e05955272c |

## Provenance classification

**REAL** — real, peer-reviewed, openly-licensed books from a real public
repository (OAPEN/DOAB), each with a verified CC-BY license recorded. See
`tasks/artifacts/data_provenance_SOP.md` and the clean-source allowlist in
`external_book_sources.md`.

## Before this trains (required gates, not yet run)

1. **Decontamination** — run the eval/held-out decon (13-gram overlap vs the
   held-out stems, per `build_eval_data.py`) before any training use.
2. **Attribution** — CC-BY requires attribution; the per-book `title` +
   `publisher` + `license_url` + `doi` travel with every row for this.
3. **Scale-up** — `--full` for complete texts; broaden beyond English if desired.

## Personal and sensitive information

None beyond public authorship/publication metadata. Scholarly monographs from
public open-access repositories; no PII.
