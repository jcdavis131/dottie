# Audit — repair_transcripts.jsonl

Corpus PROPOSAL only (data-flywheel L4). Nothing auto-ingests this file; it is
an audited artifact per the honesty doctrine. Generated 2026-07-23.

## Row counts

- **12 rows** from **7 recovered experiments** (out of 100 in the ledger copy;
  99 have an implementation, 70 failed validation and never recovered, and
  never-recovered experiments yield **zero** rows by design — the ledger holds
  no code known to fix their failures).
- Exporter output (verbatim):

```
db: C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3 sha256=5150bdf0c9bfc12d8a1fc277cb92d02f739847c883f0421b686ea98f10b489c4
wrote C:\Users\jcdav\dottie\tasks\artifacts\corpus_proposals\repair_transcripts.jsonl: 12 rows from 7 recovered experiments ['694633b2d354', '707493a77830', '71a62346df0a', '780f7675fb62', '87b8635f50f8', 'a9e22749f2ad', 'd7dfb087f3cb']
levels: {'static': 4, 'dry_run': 6, 'syntax': 2} | rows with a (recomputed) hint: 12/12
```

## Schema (one JSON object per line)

| field | type | meaning |
|---|---|---|
| experiment_id | str | ledger experiments.id (join key) |
| experiment_state | str | final ledger state (rejected / failed_training — recovery here means validation recovered; later stages may still have failed) |
| hypothesis_name | str\|null | hypothesis JSON `hypothesis_name` |
| module_name | str | candidate module class name |
| dry_run_contract | obj | `{class_name, init_kwargs, input_shape}` the validator instantiates with |
| attempt | int | validate.py history `attempt` index |
| failure_seq | int | 0-based index among this experiment's failed attempts |
| n_failed_attempts | int | failed attempts in this experiment's history |
| level | str | syntax \| static \| contract \| dry_run |
| status | str | validator status string |
| failure_detail | str | **verbatim** history detail (already truncated to 2000 chars by validate.py:743 at write time) |
| repair_hint | str\|null | `diagnose_failure(level, detail)` recomputed at export time |
| hint_source | str | constant disclaimer (see contamination #2) |
| corrected_code | str | the experiment's **final validated** code |
| corrected_code_role | str | constant `final_validated_code` (see contamination #1) |
| validated_detail | str | detail of the passing attempt (e.g. `forward ok on input [4, 16, 64] -> (4, 16, 64)`) |

## Provenance

- Source: `C:\Users\jcdav\dottie\tasks\artifacts\ledger_copy.sqlite3`
  (sha256 `5150bdf0c9bfc12d8a1fc277cb92d02f739847c883f0421b686ea98f10b489c4`,
  983,040 bytes) — a COPY of the research daemon's
  `apps/dottie/data/research/ledger.sqlite3`; the live DB was never opened.
- Exporter: `C:\Users\jcdav\dottie\apps\dottie\scripts\export_repair_transcripts.py`
  (tests: `apps/dottie/tests/test_export_repair_transcripts.py`).
- Hint function: `dottie.research.validate.diagnose_failure`, WORKING TREE at
  export time (last commit touching validate.py:
  `983505091c23c52f9608e902135d150584ed983d`; the file showed as modified in
  `git status` during this session — another agent edits it concurrently, so
  re-running the exporter later may yield different `repair_hint` text; all
  other fields are deterministic from the ledger copy).
- Failure text and corrected code were produced by the local research loop's
  LLM (qwen-family via Ollama) against the AVA factory harness — synthetic
  code, no third-party licensing or PII concerns.

## Known contamination / limits

1. **corrected_code is not the attempt+1 diff.** validate.py's history persists
   attempt/ok/level/status/detail but never the per-attempt candidate source,
   so every row of one experiment carries the same final validated code. For
   multi-failure experiments (5 of 7) the pairing "this failure → that code" is
   correct only in the weak sense that the final code no longer exhibits the
   failure. Dedup on `experiment_id` before any per-pair loss weighting.
2. **Hints are recomputed, not historical.** `repair_hint` comes from TODAY'S
   `diagnose_failure`. The hint table shipped 2026-07-22 (commits 54c43f4,
   9835050) and was **mined from this same ledger population** — including,
   plausibly, these very failures. Training on failure→hint and then evaluating
   hint quality on this ledger is circular. The corrector that actually
   produced the recoveries saw raw tracebacks only (no hints existed yet):
   12/12 rows now have a hint, whereas at run time 0/12 did.
3. **failure_detail is pre-truncated** at 2000 chars by the trainer
   (validate.py:743); a few ledger `failure` columns elsewhere cut off
   mid-traceback. History detail is the best available text, not guaranteed
   complete.
4. **Small corpus, survivor-biased.** Only 7 of 77 fail-touched experiments
   recovered; the recoveries over-represent easy failure classes (F821 typos,
   einsum, syntax corruption) and contain nothing for the 3 largest
   never-recovered classes (autograd-in-forward, no-forward-method, own-assert).
5. **experiment_state ≠ success.** All 7 source experiments later ended
   rejected (4) or failed_training (3). The pairs teach "repair to pass
   validation", not "repair to a good experiment". (Per the operator's ledger
   doctrine: the ledger's 3 `sota` rows are artifacts; none appear here.)
