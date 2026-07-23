# Agentic Curriculum — research PDFs → packed shards

**One line:** expand Dottie's P0–P5 diet with *open-licensed* STEM + causal + human-factors
text so the model that powers `scout` can reason, attribute causes, and refuse fabrication.

**Doctrine:** provenance travels with every number; honest refusal over fabrication; no
copyright laundry. Upload-mirror sites (e.g. pdfcoffee) are **not** collection sources.

---

## Why this track (agentic assistants)

SOTA agent stacks win on: verifiable math/code, tool grounding, long-horizon recovery, and
**causal credit assignment** when a step fails (retriever vs tool vs planner). Pretraining
that only sees FineWeb-style prose under-prepares that. We add:

1. **Foundations** — math, stats, physics (symbols + worked reasoning)
2. **Minds & orgs** — psychology, judgment under uncertainty, safety human-factors
3. **Causal structure** — confounders, interventions, event/condition chains (DOE-style CFA
   for incidents; Pearl-style for inference)
4. **Agent ops** — already covered by `synth_tool_use` / `synth_scout_cli` / react adapters

The pdfcoffee "Causal Factor Analysis" example is Indonesian course notes citing **DOE
1997/1999** accident investigation (events = rectangles, conditions = ovals). Useful *genre*,
wrong *acquisition path*. Prefer US-gov public domain DOE handbooks + open causal texts
(see `configs/research_pdf_catalog.yaml`).

---

## Map onto live P0–P5 (do not invent new mix keys yet)

| Domain | Primary phases | Existing mix keys | Open seeds (catalog) |
|---|---|---|---|
| Logic / discrete math | P0–P1 | `logic`, `math` | already synth_logic / synth_math / zk_math |
| Statistics + probability | P1–P3 | `math`, `math_reasoning` | OpenStax Intro Stats, Think Stats |
| Causal inference + CFA | P2–P3–P5 | `encyclopedia`→`math_reasoning`→anneal | DOE CFA (public), Hernán open book, arXiv surveys |
| Physics | P2–P4 | `encyclopedia`, `long_docs` | OpenStax University Physics |
| Psychology / judgment | P2–P5 | `encyclopedia`, `chat`/`safety` | OpenStax Psychology 2e |
| Peer science prose | P2/P4/P5 | already `pes2o` | keep; do not let one history source dominate |
| Tool / agent traces | P2–P5 | `tool_use` | already wired |

**Activation rule (same as MegaWika / synpro):** new sources land at `weight: 0` → on-box
schema check → shave a same-phase general source → re-run
`tests/test_collector.py::test_every_phase_mixture_sums_to_one`.

---

## Pipeline (download → process → chunk → pack)

```
operator inbox (licensed PDFs/md)
        │
        ▼
scripts/ingest_research_pdfs.py     # local extract only (fitz→pdfminer→pdftotext)
        │  writes data/research_corpus/<domain>/*.md + manifest.jsonl
        ▼
synth generator `research_pdf`      # chunks → DOC_KEYS docs (offline)
        │
        ▼
collector (sources.yaml) → raw/*.jsonl.zst
        ▼
curator clean·dedup·decon·split·pack → packed/p{N}/…
        ▼
trainer (nano/mini/base1b presets)
```

Wiki path (`tools/pdf_wiki_ingest/`) stays a **knowledge** ingest. This track is the
**training** ingest. Do not conflate them.

---

## Priority order (build this first)

1. ✅ Catalog of open seeds + legal doctrine (`research_pdf_catalog.yaml`)
2. ✅ Offline PDF→chunk tooling + `research_pdf` generator (weight 0)
3. ✅ `causal_reason` synthetic generator (computed CFA + confounder drills; weight 0 staged)
4. Activate small P2/P3/P5 weights after one packed nano smoke
5. Grow domain shelves (math→stats→psych→physics) only from catalog `status: approved`

---

## OpenStax K12 bulk pull

```bash
cd "$AVA_FACTORY_ROOT"
python scripts/download_openstax_k12.py --out data/research_inbox/openstax-k12
# Then extract → corpus (per category folder):
for d in data/research_inbox/openstax-k12/*/; do
  [ -d "$d" ] || continue
  base=$(basename "$d")
  [[ "$base" == .* ]] && continue
  python scripts/ingest_research_pdfs.py --inbox "$d" --out data/research_corpus --domain "$base"
done
```

PDFs are **not** committed to git (`data/` is gitignored). Sidecar `.meta.json`
carries CC license + OpenStax source URL for every title.

---

## Explicit non-goals

- Scraping pdfcoffee / LibGen / Z-Library / similar mirrors
- Treating a single encyclopedia as ground truth (history doctrine already forbids this)
- Shipping copyrighted PDF binaries in git
