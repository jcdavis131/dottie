# Audit — oapen_open_books.jsonl

Corpus PROPOSAL only (external-source expansion, operator directive: "expand
datasets to be grounded in external validated sources" + "scale up OAPEN").
Nothing auto-ingests; audited artifact per the honesty doctrine. Scaled pull
2026-07-24. OAPEN accessed strictly READ-ONLY via its public REST API.

## Source + method

- **Source:** OAPEN (`library.oapen.org`), the open-access content host behind the
  Directory of Open Access Books (DOAB) — peer-reviewed scholarly books.
- **Puller:** `apps/dottie/scripts/pull_oapen_books.py` (stdlib-only, read-only).
- **Query:** `dc.rights:*creativecommons*`, English filtered client-side. (The
  earlier `AND dc.language:English` server clause silently capped the result set
  at ~58 records; rights-only paginates the full ~600-record CC set.)
- **Text:** OAPEN's pre-extracted `.pdf.txt` bitstream per book (no PDF parsing);
  UTF-8, stripped. Full texts live gitignored at
  `apps/ava-factory/data/oapen_books/`; the committed sample stores a 12,000-char
  excerpt per book, with `text_chars` + `text_sha256` pinning the full text.

## Scale + license gate (the provenance gate)

**48 unique English books (47 CC-BY, 1 CC-BY-SA), 40.5M chars ≈ 10.1M tokens**,
via two paths deduped by content sha256:

1. **REST wildcard** (`pull_oapen_books.py`): scanned 600 → 19 books. Excluded
   542 non-English, 11 ND, 22 NC, 6 duplicate-content. The `dc.rights:*creativecommons*`
   search caps at ~600 records.
2. **OAI-PMH harvester** (`pull_oapen_oai.py`, `metadataPrefix=dim`): enumerates
   the full ~57k-record catalog (uncaps the ceiling), carrying per-record CC
   license URL + language. Yielded 33 new books (4 overlapped the REST set).
   Yield ~1% CC-BY-English — the catalog is heavily multilingual and much of it
   is "openAccess" without an explicit CC license (excluded: no verifiable license).

The same license gate runs in both. Both exclude any `*-ND` (training is a
derivative use), NonCommercial by default, and dedup by content sha256 (OAPEN
serves the same book under multiple handles — a real defect avoided). A larger
corpus just runs the OAI harvester longer. Per-book text sha256 for all 48 is in
the committed `oapen_open_books.jsonl` (`text_sha256` per row) + the manifest.

## Per-book provenance (the 19 REST-path books; all 48 sha-pinned in the jsonl)

| title | license | full chars | sha256 |
|---|---|---|---|
| Transforming Teaching in Higher Education | CC-BY | 801,634 | sha256=2e4bcfa49dbcec564157ec56d220850bb3de2144ca29dd9dd52478c1a056fa34 |
| Printing R-Evolution and Society 1450-1500 | CC-BY | 2,365,602 | sha256=af3eb54301e758e1b22d5a75a872246234c8e90655c54970c530b2e9490038fd |
| Distributing Knowledge | CC-BY | 395,379 | sha256=178a2740c940f5843c6d2d63d1976938c5dfb35756b0ccbc46bf0bf52f304701 |
| Nonsolution | CC-BY | 187,591 | sha256=0145ffad6db393e4f3f2891b2e06ea0302fac54c0a502c0911c4b76d1258019f |
| A Self-Reflexive Verista | CC-BY | 388,510 | sha256=668fa644b4bb2b027d8bcefce45a37356b0de49a5d0d93c76a2cdc5f4b4dfd40 |
| Freemasonry and the Orient | CC-BY | 285,549 | sha256=9116107b3d41db11c41e4b6fa853da8e5e3924b64610de029086d83e58a75005 |
| Vulnerable Workers in Times of Social Transformation | CC-BY | 454,539 | sha256=305cf190bb98c3988d28c9e0453db3bfeb85a8fefde10277ac92f33eca9d7a56 |
| Venetians and Ottomans in the Early Modern Age | CC-BY | 275,134 | sha256=58cc993614744338ebd63bed0c76748b080d8815102c51dbb09b70f13b3f2c09 |
| Between Texts, Beyond Words | CC-BY | 268,705 | sha256=68adfd6a45dba3c797cc5eea83b1362bbb7e3817b1f9e2eb1677cd1ed400f192 |
| New Steps in Japanese Studies | CC-BY | 425,279 | sha256=3847c839e7b2a05329b99b290033f386d27799438b567e1a0f525c04108fcc78 |
| The City of Ebla | CC-BY | 593,085 | sha256=edad82d71a2941715759f647076346fdadf346a4afc1ff9a7f1510e05955272c |
| Death and Desire in Contemporary Japan | CC-BY | 774,190 | sha256=ad1d5f748be6ee3fb9ba820d44e6f37351be42a0184723b9215b392a5765ef21 |
| Linking Ancient and Contemporary | CC-BY | 899,212 | sha256=084f5c638b7b9633c5b2fd05000f7b0d444a8d4ca7a922c645a709d8b3a7fb5c |
| Commensality and Ceremonial Meals in the Neo-Assyrian Empire | CC-BY | 817,463 | sha256=5018fa37cb5d399a055e2e1fdc5573d2f0fcdb0b849531bc27eb1de94b0c7b4f |
| The Reception and Application of the Encyclical | CC-BY | 877,211 | sha256=b942a52b966946ea8506757d92885122d98baf45a6883437cf069d8a78bc4a45 |
| Chiang Kai-shek and His Time | CC-BY | 529,470 | sha256=35c67367b56fc99ee3019dfad845da73a46623a776586d0907eb57a16db1dba3 |
| CLIL in Higher Education and the Role of Corpora | CC-BY | 326,104 | sha256=d926d3199028d810467b3f463beb1329fd942719d3c37a5d2a720293129b5d11 |
| Osmanlı Pâdişah Türbeleri (Ottoman rulers' tombs) | CC-BY | 100,980 | sha256=73ffcd60f3446a89ad75fd5ad1aa1bced6dd6aa1b32fbb8b7b1ef184427f4676 |
| The Ottoman-Venetian Border (15th–18th Centuries) | CC-BY | 397,447 | sha256=079934fd0dc91c9304727aa0de7fb2edb280bf273fc7ec8c6f590bdbd3618d40 |

## Provenance classification

**REAL** — real, peer-reviewed, openly-licensed books from a real public
repository (OAPEN/DOAB), each with a verified CC-BY license recorded. See
`data_provenance_SOP.md`.

## Known limitations

- **Publisher concentration:** most of the 19 are Edizioni Ca' Foscari (Venice
  University Press) English-language scholarly monographs — narrow provenance,
  HSS-skewed (history, area studies, linguistics). Fine as clean long-form text;
  not a balanced corpus. Broadening needs OAI-PMH/DOAB (more publishers).
- **Decontamination:** OAPEN is not among the current held-out generators, so it
  cannot overlap the current held-out; `HELDOUT_SEED` disjointness applies once
  it is registered as a source (see the card's Decontamination section).

## Personal and sensitive information

None beyond public authorship/publication metadata. Public scholarly monographs.
