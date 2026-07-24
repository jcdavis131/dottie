# External book/PDF sources — provenance decision + clean expansion plan

Operator ask (2026-07-24): "can you utilize [library.memoryoftheworld.org] to
get books/pdfs to expand your datasets to be grounded in external validated
sources?"

Short answer: **the goal is right; that specific source is not.** We are
already grounded in external *validated, license-clean* book and paper corpora.
Memory of the World is a shadow library of largely copyrighted works — ingesting
it would violate our own data-provenance SOP and regress the clean posture we
have. Below: the verdict with evidence, what we already use, and the clean way to
expand.

## Verdict on library.memoryoftheworld.org — FORBIDDEN source

**What it is (verified, not assumed):** "Memory of the World" (Marcell Mars /
Tomislav Medak) is an explicitly-named **shadow library** — a network of
interconnected private book collections shared via a Calibre extension ("let's
share books"), whose stated purpose is to contest "the limiting aspects of
intellectual property." It is catalogued as a shadow library alongside Library
Genesis / Sci-Hub. Sources: Monoskop "Shadow libraries" and "Public Library /
Memory of the World"; shadowlibraries.github.io; creatingcommons.zhdk.ch.

**Why it fails the SOP** (`data_provenance_SOP.md`): the works it distributes are
overwhelmingly **copyrighted, shared without a redistribution/training license**.
That means:
- It cannot be classified **REAL** — REAL requires a real *and legally usable*
  source with a recorded license. Unlicensed copyrighted text is not verifiable
  provenance; it is legal + reputational liability (the exact subject of active
  litigation over LibGen/Books3-style corpora).
- It contradicts the repo's standing posture: "public/free-tier only, no employer
  tie, credibility + provenance." Garbage-in here is *legal* garbage, not just
  noisy text.

**Rule (added to the SOP's FORBIDDEN class):** shadow libraries / unlicensed
copyright aggregators (Memory of the World, LibGen, Sci-Hub, Z-Library, Anna's
Archive, Books3, and the like) are **never** ingestion sources, regardless of
convenience or coverage. A book/PDF ships only with a verifiable public-domain or
open license recorded on its dataset card.

## We are ALREADY grounded in external validated sources

`apps/ava-factory/configs/sources.yaml` already registers license-clean external
corpora — the operator's instinct is already implemented:

| source | dataset | what | license basis |
|---|---|---|---|
| `gutenberg_hist` | sedthh/gutenberg_english | **public-domain books** | Project Gutenberg (US public domain) |
| `pes2o` | allenai/peS2o | **open-access academic full text** (papers) | ODC-By |
| `wikipedia_en` | wikimedia/wikipedia | encyclopedic | CC-BY-SA |
| `megawika_en` | hltcoe/megawika | Wikipedia-grounded multilingual | permissive |

Plus arXiv preprints already pulled into `research-engine/graphify_source/`. So
"books grounded in external validated sources" is a posture we already hold — the
task is to *broaden coverage without leaving the clean set.*

## Clean expansion options (the vetted allowlist)

To actually get **more books/PDFs**, ordered by fit to "external *validated*
sources," each onboarded per the SOP (license verified per item at ingestion):

1. **DOAB / OAPEN** — Directory of Open Access Books / OAPEN: peer-reviewed,
   **CC-licensed scholarly books**. This is the biggest real gap (peS2o covers
   papers, not books) and the best match for "validated sources." Open API +
   per-title license metadata.
2. **Full Project Gutenberg** — broaden beyond the current subset (e.g.
   `manu/project_gutenberg`, or PG-19 `deepmind/pg19` for long-context). Public
   domain. Free.
3. **Standard Ebooks** — curated, cleanly-typeset public-domain books.
4. **PubMed Central Open Access subset** — licensed biomedical full text
   (per-article CC / other open licenses; filter to the OA subset).
5. **Internet Archive — public-domain subset** — rights-filtered to PD/open only
   (never the general collection).
6. **Wikisource** — CC-BY-SA transcribed public-domain texts.

All are free/public-tier, consistent with the repo constraints.

## Onboarding path (the SOP, honored)

`configs/**` and the curriculum are a **frozen path** — new sources land as a
**proposal**, not a direct edit, per the adding-a-curriculum-generator
discipline:
1. **Name the real source + license** (the table above; verify the exact license
   field on the HF card / API before use).
2. **Pull a sample**, decontaminate against the eval/held-out stems (13-gram
   overlap, per `build_eval_data.py`), sample-audit N rows by hand.
3. **Stamp an HF-standard dataset card** (`data_provenance_SOP.md` §"Dataset card
   structure") with `provenance_classification: REAL` + the recorded license.
   This is what the Hub Artifact Registry renders.
4. **Propose** the `sources.yaml` entry (name/kind/dataset/split/text_field/
   phases/weight/gated) + the phase-mix rebalance; the operator applies it to the
   frozen config.
5. **Gate**: no PLACEHOLDER rows in any published metric; the card is present and
   REAL before the source trains.

## Recommendation + the decision needed

- **Do not** ingest Memory of the World (or any shadow library).
- **Recommended first expansion:** **DOAB/OAPEN open-access books** — it fills
  the real gap (validated *books*, not just papers), is CC-licensed, and matches
  "external validated sources" precisely. Second: broaden Gutenberg for
  public-domain long-form.
- **Operator decision:** which clean source to pilot first (DOAB/OAPEN books, or
  broaden Gutenberg, or PMC-OA)? On your pick, I'll build the read-only sample
  puller + the HF-standard dataset card + the `sources.yaml` proposal (I won't
  touch the frozen config directly, and nothing auto-ingests).
