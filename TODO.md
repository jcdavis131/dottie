# TODO — the single open-work list

**Generated 2026-07-26 by mechanical extraction.** Every `- [ ]` in `TODOS.md` (126)
and `tasks/todo.md` (15) is below — 141 items, nothing curated away, nothing invented.
Item text is the checkbox line plus up to two continuation lines; **the full reasoning
for each lives in its source file under the same heading** and is not reproduced here.

⚠ **This list is not triaged.** 141 open items is an inbox, not a plan. The ordered
next steps are the section immediately below; everything after it needs a triage pass
that no one has done.

---

## ▶ NEXT — ordered, do these first

1. **Fix the 2 defects producing wrong data.** `apps/ava-factory/scripts/minhash_dedup.py`:
   single-linkage clustering drops documents below its own advertised 0.8 threshold
   (worst intra-cluster true Jaccard **0.7143**); and `docs[key] = seg` silently
   overwrites same-named defs in one file — `bigbang/plugins/mcp/cli.py` defines
   `_check_sdk` twice under try/except, one returning `True` and one raising, **opposites**,
   only the second survives (4,567 pairs → 4,566 keys, invisible in the reported total).
2. **Add a task-shaped eval slice** before any embedding model is judged. The golden
   set's queries are commit messages, which flatter BM25; the agent tier's real queries
   are task descriptions. Judging a model only on commit messages is rigged the other way.
3. **Give `~/vector-unified` a remote.** 5,397 lines, one disk. Local git survives `rm`,
   not disk failure.
4. **Decide the authoritative surface for hoops 48-vs-64**, then fix the other three.
   `cd ~/vector-hoops && python pipeline/provenance_gate.py` exits 1 today, correctly.
5. **Re-derive or retract the hoops promote justification.** `0.363 → 0.757` lives in a
   comment (`composite_score.py:88-95`) and in no artifact. Same shape as the three
   research `sota` rows that were all artifacts.
6. **Then step 5 of the embedding sequence** — ONE encoder + LoRA adapters, hard
   negatives, pre-registered target beating **NDCG@10 0.622**.

### Waiting on the operator (not on an assistant)
- The 2 FROZEN edits to activate stack-v3 (`odc-by` verified; adapter + 27 tests ready;
  source enters at weight `0.00` or the collector spins).
- Docker Desktop restart → verifies the telemetry fix, unblocks training.
- Delete the 2 stale `vector-hoops` clones? Nothing was deleted.
- scout-cli `httpx<0.28` pin vs starlette upgrade — 21 tests cannot run.

---

## Extracted backlog (141 items, untriaged)

### `TODOS.md` — NEW 2026-07-25 — `.github/workflows/lint.yml` is a HARD gate that has been RED on every push

- [ ] **OPERATOR DECISION — a second ruff workflow contradicts the one in ci.yml, and it fails every time.** `gh run list --workflow "Ruff Lint"` -> **failure on 8 of the last 8 pushes**, including commits that predate today's work. A permanently-red required check is worse than an

### `TODOS.md` — NEW 2026-07-24 — ORCHESTRATION FLAW: concurrent build agents cannot see each other

- [ ] **My batch-4 workflow told each of 6 agents to overlap-check against the existing 47 plugins — and nothing about its 5 concurrent siblings.** So duplicate functionality between simultaneously-built plugins is structurally invisible, and each agent's overlap evidence is
- [ ] **Second flaw in the same rubric: I never defined what `claims_hold` means, so verifiers applied their own thresholds and the boolean is NOT comparable across plugins.** `a11y`'s verifier found **2 mutation survivors and returned `claims_hold: true`**; `contentgap`'s found

### `TODOS.md` — NEW 2026-07-24 — batch-4 `apm`: one vacuous assertion (code and metrics all hold)

- [ ] **tests/test_apm.py:721 cannot fail.** `assert "apm:slow" not in {d["rule"] for d in by_rule["apm:critical-latency"]}` — the bucket is KEYED by `d["rule"]`, so every element in it already has `rule == "apm:critical-latency"`;

### `TODOS.md` — 2026-07-24 — BATCH-4 HEADLINE: 5 of 5 verifiers found something the builder missed

- [ ] **Every single independent verifier found a real gap, and 3 of 5 found an assertion that cannot fail.** flows ✅ · a11y ✅ (2 survivors, judged minor) · contentgap ⚠️ (2 survivors + overlap claim stale) · dupes ⚠️ (17th surviving mutant + 1 vacuous test) · apm ⚠️ (1 vacuous

### `TODOS.md` — NEW 2026-07-24 — batch-4 `contentgap`: 2 low-severity mutation survivors

- [ ] Verifier refuted "15/15 caught, survivors: none": (a) `expected_count()` `round(rate * max(0, draft_tokens), 2)` -> `round(rate * draft_tokens, 2)` survives, but `token_count()` can never be negative so the guard is unreachable either way; (b)

### `TODOS.md` — NEW 2026-07-24 — batch-4 `dupes`: two TEST defects to fix before it ships (code is fine)

- [ ] **The adversarial verifier refuted the build's "16/16 mutations caught, survivors: none". There is a 17th that survives all 40 tests.** `bigbang/core/dupes.py:539` `both = bool(set_a) and bool(set_b)` -> `or` survives, and it is NOT an equivalent mutant.
- [ ] **One vacuous assertion, tests/test_dupes.py:142.** `blob = bytes([0,1,2,3]) * 500; assert blob.decode("utf-8") is not None` — max byte is 3, so the blob is pure ASCII and `decode()` cannot raise; `decode()` returns `str`, so

### `TODOS.md` — NEW 2026-07-24 — `apps/scout-cli/docs/OPENSWAP.md` has a real NUL byte at offset 18278

- [ ] **Small docs bug, queued behind batch 4 (the file is modified by a live agent — do not clobber).** The line documenting the `logs` UTF-16 handling means to show the literal Python bytes-literal `b"\r\n\x00"`, but the file contains **actual CR, LF and NUL bytes** instead —

### `TODOS.md` — ✅ DONE 2026-07-25 — enforced, and enforcing it found three defects + a bigger hole

- [ ] **FOLLOW-UP, and this is the bigger hole: 16 of 47 write-capable plugins never call the gate at all.** `auth ava brain dev_loop herd lab mcp quality reviewgraph rtx secrets skill system tennis tools write`. That list is the inverse of reassuring — `auth` writes
- [ ] **FOLLOW-UP: the allowlist cannot express a dynamically-discovered root.** Defects 1 and 2 share this cause — reviewgraph tried to spell it `<root>`, tasks hardcoded one machine's answer. `.scout` only works because it is CWD-relative and `abspath` resolves
- [ ] **KNOWN GAP, stated not papered over:** a **symlink** inside an allowed directory pointing outside it still escapes `_path_matches`. Blocking it needs `realpath` on an existing tree, which the not-yet-created-write case rules out.

### `TODOS.md` — ✅ DONE 2026-07-25 — the dataset licence gate ADMITTED NC and ND (and was bypassed entirely on the ingest path)

- [ ] **FOLLOW-UP: `docs/crons/dataset-discovery-daily.md:21` still prescribes `--dry-run`.** With the gate fixed that cron is now correctly a no-op for candidate selection (fail closed), which means it produces nothing usable. Drop `--dry-run` from the documented cron:

### `TODOS.md` — 🧭 2026-07-26 — EMBEDDING SEQUENCE: bar measured, Option C decided, steps 4–5 in flight

- [ ] **Add a task-shaped eval slice before step 5 is judged.** The golden set's queries are commit messages — the right proxy for scoring a code-tree search, but the agent tier's real queries are natural-language task descriptions, which are longer and less identifier-dense,

### `TODOS.md` — ⚠ 2026-07-26 — MinHash + hard-negatives landed, but BOTH failed adversarial review

- [ ] **minhash: single-linkage clustering deletes documents below the advertised threshold.** `uf.union(a, b)` chains, so a doc can be dropped in favour of a survivor it is *not* near-duplicate to. Measured on the 44-cluster / 126-drop scout-cli run: worst
- [ ] **minhash: `docs[key] = seg` silently overwrites same-named defs in one file.** Concrete: `bigbang/plugins/mcp/cli.py` defines `_check_sdk` twice under try/except — one returns `True`, the other raises. **They are opposites, not duplicates**, and only the
- [ ] **minhash: unreadable files counted as scanned.** `files += 1` precedes `read_text`; `except OSError: continue` skips without incrementing `unparseable`.
- [ ] **minhash: `cluster_documents` returns whole-corpus `shingle_sets` + `signatures`** that `main()` never reads — pins 4,566×128 ints for the result's lifetime, which defeats the stated Phase-8 target of a larger corpus.
- [ ] **hard_negatives: `class_of` reads only the innermost class**, so `Outer.Inner.run` and `Other.Inner.run` collide and a record can list its own `(path, symbol)` as a negative. Latent (0 occurrences today) but ordinary Python triggers it.
- [ ] **hard_negatives: docstring claims order-independent output; it is not.** Records are appended in input order, so `--out` JSONL is not reproducible across walk orders. Fix the claim or the code.
- [ ] **Several real-repo test floors are far looser than claimed** (`same_package` 1000 vs 3,760 measured = 27%), so a 73% regression would pass green.

### `TODOS.md` — 🔬 2026-07-25 — THE RECURRING DEFECT CLASS: *a gate whose verdict nothing consumes*

- [ ] **Sweep the estate with that heuristic.** Instances 1–3 and 5 are fixed or documented; **#4 is open and lives in `~/vector-hoops`** — see the provenance-gate entry below.
- [ ] **Port the site's enforce-by-construction doctrine into the model repos.** The asymmetry above is the root cause, not any individual bug.

### `TODOS.md` — 🔬 2026-07-25 — `~/vector-hoops`: four published surfaces describe a model that is not shipped

- [ ] **Decide which surface is authoritative and fix the other three.** The gate deliberately does not autofix: the artifact is *usually* right and the docs stale, but a stale artifact with fresh docs is the same failure wearing the other hat.
- [ ] **Re-derive or retract the promote justification (instance #4 above).** `composite_score.py:88-95` records the artifact was promoted "not by clearing the CQS bar, which it does not", justified on a manual held-out top-5 comparison (0.363 → 0.757) that

### `TODOS.md` — ✅ 2026-07-25 — REDEPLOYED. The sha256 drift on www.bhenre.com is fixed (gate now PASSES)

- [ ] **GAP: G3-before-G4 was DEFEATED on this deploy and silently degraded to promote-then-verify.** `vercel deploy --prod --skip-domain` built into the production environment without moving the alias — correct — but the unaliased URL is behind **Vercel
- [ ] **GAP: the alias-guard pin is NOT version-controlled**, which weakens the rollback story above. `apps/bluehenre/.gitignore:1` ignores `data/`, so `data/last_good_deployment.txt` is untracked — `git ls-files` does not know it. I updated

### `TODOS.md` — 🔓 2026-07-25 — stack-v3 UNBLOCKED: licence is `odc-by`. Adapter built + tested; needs ONE frozen edit to activate

- [ ] **ACTIVATION — needs the operator's word, because both files are FROZEN** (bind-mounted into the live trainer; docker CLI is 500ing so I could not confirm whether a run is in flight, and my own note says "the tool cannot reach it" ≠ "it is not

### `TODOS.md` — NEW 2026-07-25 — 21 factory tests CANNOT RUN: httpx 0.28 removed `Client(app=...)`

- [ ] **`apps/ava-factory/tests/test_server_endpoints.py` — all 21 tests ERROR at setup** with `TypeError: Client.__init__() got an unexpected keyword argument 'app'`. Installed **httpx 0.28.1**; the `app=` shortcut was removed in 0.28, and starlette's

### `TODOS.md` — ⚠⚠ CORRECTION (05:01) — "takes effect at the 05:05 restart" was WRONG, five times over

- [ ] **Real defect for you**: restarting this loop is not safe with `Stop/Start-ScheduledTask` alone — it silently leaves an orphan and can double-run the drain loop (two workers claiming experiments, concurrent ledger writes). Either make the wrapper kill its child

### `TODOS.md` — ⚠ Earlier framing (superseded by the root cause above): "unexplained daemon death"

- [ ] Optional companion (not applied): shorten the trigger repetition from **PT1H** to ~PT15M. With `IgnoreNew` the extra firings are no-ops while healthy, so it only shortens the worst-case gap if the restart attempts are also exhausted. Your call — it is a
- [ ] **I could not determine the cause and am not going to guess.** Worth checking when you are back: Windows Event Viewer → Application/System around **05:25** for a process termination, and the Task Scheduler operational log for that instance. If it recurs,

### `TODOS.md` — 5.3.R4 — ⭐⭐⭐ DEGENERACY GATE'S FIRST PRODUCTION CATCH (06:32), cheapest yet

- [ ] NEXT: **re-run the constraint-8 comparison when n >= 20** in the post-restart bucket, scoping it by the `boot` lines rather than commit timestamps. If dry_run share has not moved, the axis-discipline guidance is not working and the dominant failure

### `TODOS.md` — 5.3.R5 — the baseline is CONTAMINATED, and no gate was looking

- [ ] NEXT (operator input): with contamination now detected automatically, decision #5 is sharper — **re-seed the baseline to 5.61982** (the pre-MLBR value) and the caveat clears itself. Until then every promotion verdict carries the contamination warning, which is

### `TODOS.md` — 5.3.R8 — validation ran at the WRONG WIDTH; candidates died at integration for it

- [ ] **I OVERRODE MY OWN HOLD, deliberately — recording the trade.** §5.3.R4 said not to ship a second dry_run intervention until constraint-8 was measurable, to keep the two separable. This change alters validation pass rates, so **the constraint-8 comparison is

### `TODOS.md` — 5.3.R12 — a THIRD of the search budget is spent on ideas that cannot be built

- [ ] **OPERATOR: the highest-leverage change here is CONFIG, not code.** The `--bottleneck` string in the scheduled task is generating the mismatch. A block-shaped bottleneck (e.g. *"the fusion block at the swap site underuses its capacity — find a token-mixing or gating
- [ ] Effect of the prompt change is **UNMEASURED**, and per §5.3.R8 the constraint-8 comparison is already confounded. Scope any future before/after by the `boot` lines, not by commit timestamps.

### `TODOS.md` — 5.3.R18 — the two failures are INDEPENDENT, and only ~5 real attempts have been made

- [ ] **Reframed guidance for the operator (supersedes the framing in item 8):** the fix is not better ranking of what the loop proposes, it is getting it to propose the right shape at all. In priority order: (a) the `--bottleneck` string (§5.3.R12) — config, yours;

### `TODOS.md` — 5.3.R19 — ask for capacity at IDEATION, ~8 minutes before the validator can catch it

- [ ] **FOLLOW-UP once the daemon runs current code:** measure what fraction of proposals actually fill `learnable_parameters`, and whether the zero-parameter rate falls from 55%. If compliance is high, promote the field to `required` in `parse_hypotheses`. Scope the

### `TODOS.md` — 5.3.R39 — REVISED RECOMMENDATION: restart NOW, do not wait for the measurement

- [ ] I cannot do it: the permission classifier blocks process control (§5.3.R9). Commands are there; `run.log` will show a `boot` line with the new `git_sha` when it takes.

### `TODOS.md` — 5.3.R21 — ⭐ THE DAEMON RESTARTED. Tonight's work is live (08:50:02)

- [ ] **NEXT, and now finally measurable** — scope all of these by `updated_ts >= boot`: - does the zero-parameter rate fall from **55%**? - does the category-error rate fall from **36%**?

### `TODOS.md` — 5.3.R24 — the "DEAD ENDS" list was teaching the mode collapse it was meant to prevent

- [ ] **Effect on actual proposal diversity is UNMEASURED** — this is a prompt change and §5.3.R12 already showed prompt changes are hard to attribute. It is now measurable the right way: the post-restart boundary is clean, and `scripts/post_restart_report.py` will

### `TODOS.md` — 5.3.R25 — first post-restart cycle: the machinery works. The RATES are not claimed.

- [ ] **R19 follow-up status:** compliance is 3/3, which is *consistent with* promoting `learnable_parameters` to `required` in `parse_hypotheses` — but 3 successes cannot distinguish "the model always complies" from "the model complied three times". Leave it

### `TODOS.md` — 5.3.R28 — the sequence-axis twin of R8, found live within minutes of the restart

- [ ] **Worth noting how this was found.** Not by review, and not by the gates — by *noticing a duration that did not fit* and pulling the thread. The 10.8 s figure was visible only because `dur_s` is logged per action (§5.2 instrumentation). Cheap

### `TODOS.md` — 5.3.R30 — the restart-lag is structural, and the report now says what it can attribute

- [ ] Consequence for the operator: a second restart would pick up R24/R28/R29, but it also **resets the measurement window to n=0**. Given the current window is 7 of the 20 needed, the cheaper order is: let this window finish, read it, then restart. The seq probe not

### `TODOS.md` — 5.3.R32 — the bundle's re-verification script has never been able to run

- [ ] **Pattern worth naming:** both of the last two findings were in **human-facing artifacts** (`PROMOTION.md`, `ab_nano.py`), not in the loop. Nothing the daemon executes touches either, so no test, gate, or production run was ever going to catch them. The

### `TODOS.md` — 5.3.R33 — the decision-#5 artifact was stale, and `promote` would never have fixed it

- [ ] **The generalisation, which is the actual lesson:** a fix to a generated artifact does not reach artifacts already generated. Three of tonight's findings (§5.3.R31, R32, R33) were all in the same dead zone — **written by code, read by a human, executed by nobody**.

### `TODOS.md` — 5.3.R34 — verified the operator's fix path WITHOUT running it (09:50)

- [ ] **When memory allows, run it for real against a temp `--data-dir`** with small `--steps`: `python -m dottie.research --data-dir <tmp> calibrate-baseline --steps 5 --overwrite`. That writes only to the temp ledger and leaves the live baseline untouched.

### `TODOS.md` — 5.3.R36 — read the prompt END TO END; found a THIRD contradiction and a typo

- [ ] **The generalisable lesson, and it is not about prompts.** A constraint document assembled from separately-authored sections drifts into self-contradiction, and every individual section reads fine. **Reading the artifact whole found in two ticks what

### `TODOS.md` — 5.3.R37 — a FOURTH contradiction, with a measurable fingerprint in the generated code

- [ ] **Four contradictions, one document, four separate ticks.** §5.3.R35 (search space), R36 (rigor section), R37 (codebase context) — plus the bottleneck framing in R12. Every section read fine alone. The count is the argument: **prompts are programs, and nobody was

### `TODOS.md` — 5.3.R38 — the corrector was running with none of the constraints

- [ ] **All three prompts have now been read whole**, and each one contained something that contradicted or undercut the others: §5.3.R35 search space, R36 rigor section, R37 codebase context, R38 missing constraints on retry. **Four of four.** Not one was visible

### `TODOS.md` — 5.3.R40 — the scheduler has a battery kill-switch nobody looked at

- [ ] **Operator fix (one command, reversible; I did not run it — modifying your scheduled task is your call, and the battery defaults exist to protect laptops):** ```powershell

### `TODOS.md` — 5.3.R41 — the night-model feature cannot work under the daemon, and was still armed

- [ ] **The recurring shape, now six for six:** I fixed a bug *in* an artifact and did not read the artifact. Same as the prompts (§5.3.R35–R38, four contradictions across three files I had been editing constantly) and the promotion bundle (§5.3.R31–R33). **Editing a

### `TODOS.md` — 5.3.R43 — read `evaluate.py` whole: mostly clean, one limitation I cannot measure

- [ ] **One genuine statistical limitation, stated as a limitation and NOT acted on.** The significance gate takes its noise estimate from `eval_ce_per_batch` — the spread across eval batches **within a single run**. But the comparison it feeds is **between runs**

### `TODOS.md` — 5.3.R44 — full cross-app sweep + one anomaly that measured clean (10:35)

- [ ] **State of the loop for the operator:** running healthy on `e8cc5b7`, cycling ideate → implement → train → evaluate with candidates reaching training and being rejected on merit. **12 runtime-affecting commits are queued behind a restart** (§5.3.R39 explains

### `TODOS.md` — 5.3.R47 — swept for doc drift instead of finding it one file at a time

- [ ] **Standing rule earned the hard way, worth keeping visible:** when a behaviour changes, the paragraph describing it is part of the change. Four instances tonight, every one introduced by me, every one found by reading rather than by any test — because **no test

### `TODOS.md` — 5.3.R48 — SECOND RESTART (10:35:02) — **CORRECTION: this was a CRASH, not a deliberate restart** (see §5.3.R51). The fixes did go live; the cause I implied was wrong.

- [ ] **This is now the window that matters.** It is the first time the whole set of fixes has run together, and the first honest test of whether any of tonight's reasoning about the proposal pipeline was right. If the category-error rate does not move from 36%, the

### `TODOS.md` — 5.3.R49 — ⭐⭐ the trainer was loading the validator's scratch files, not the module

- [ ] Side observation worth its own look: nearly every workspace's final module is named **`experimental_routing.py`** — the *example* value from the implementation schema (`"repo-relative path, e.g. ava/models/experimental_routing.py"`). The model is copying the

### `TODOS.md` — 5.3.R50 — the schema's own examples were being copied, and one caused a crash

- [ ] **The generalisable rule for this codebase:** any `e.g.` inside a JSON schema the model fills is a default, not an illustration. Where a concrete value is genuinely needed, make it obviously non-fillable (`<your_module_name_lowercased>`), or state the real constraint

### `TODOS.md` — 5.3.R51 — ⛔ TRAINING IS OFF, and the daemon had been crash-looping on memory

- [ ] The restart also picks up `1470426` (the trainer was loading validator scratch files), which is **not** in the daemon's last `5b0fdd6` — see §5.3.R49. ### 5.3.R52 — a memory guard, so the loop refuses visibly instead of dying silently

### `TODOS.md` — 5.3.R52 — a memory guard, so the loop refuses visibly instead of dying silently

- [ ] **Honest scope: this makes the failure visible, not impossible.** The box has ~16 GB, `llama-server` wants ~5 GB, the fleet plus VM ~3-4 GB, and desktop apps have been running 7+ GB. **The real fix is a memory budget, not a guard** — the guard just means the next

### `TODOS.md` — 5.3.R53 — END-TO-END smoke test through the real CLI: everything holds

- [ ] Still untested end-to-end: `ideate` and `implement` (both need Ollama, ~5 GB) and `calibrate-baseline` (needs the factory + corpus). Those wait for headroom — §5.3.R34 records the safe way to do the latter.

### `TODOS.md` — 5.3.R54 — two callers misread the ledger's contract; one of them was mine

- [ ] **The pattern worth extracting: I assumed an API's failure mode instead of reading it.** Same shape as §5.3.R45 (assumed `factory_trainer` classified load failures correctly because two of its three paths did). Both times the assumption was reasonable, both times it

### `TODOS.md` — 5.3.R55 — swept for more contract misreads; found none (bounded negative result)

- [ ] **Sweeps that find nothing still earn their tick.** They convert "I fixed one, there are probably others" into "there are two, both fixed" — and the second is actionable while the first is just anxiety. Same value as §5.3.R44 (the ideation-delivery anomaly measured

### `TODOS.md` — 5.3.R56 — one-command restart, which refuses to claim a success it did not observe

- [ ] **I cannot run it** — the classifier blocks task control, which is exactly why it is a script for you rather than something I attempted. Current preconditions: 2,292 MB free (would warn, not refuse), 0 orphans, task `Disabled`.

### `TODOS.md` — 5.3.R59 — the dashboard's honesty line described the wrong measurement

- [ ] **That completes the research package**: every module I touched tonight has now been read end to end. Eleven artifacts, nine findings. The two that read clean (`evaluate.py`, and `ledger.py`'s state machine) are recorded as clean, which is what keeps the other nine

### `TODOS.md` — 5.3.R61 — ⚠ the mutation harness left a mutation in my source, and I nearly shipped it

- [ ] **Two process lessons, both mine:** never commit on a suite result I have not read; and a background/timed-out command is not a completed one. Both cost real time tonight (§5.3.R22's false alarm was the same shape — acting on output I had not actually checked).

### `TODOS.md` — 5.3.R62 — seven MORE handlers blocking the event loop, including /generate and /chat

- [ ] **Third instance of the same personal error**: §5.3.R45 (fixed `train.py`, asserted `factory_trainer` was fine — it was not), §5.3.R46 (guarded two paths in a file, left the third), and now this. **Fixing an instance is not fixing a class**, and the honest way to

### `TODOS.md` — 5.3.R63 — swept the OTHER web app for the same class; definitively clean

- [ ] **The class is now closed across all THREE apps**, with the server one guarded by an AST invariant that fails on regression (§5.3.R62) rather than a name list that drifted. ### 5.3.R64 — closed the copy-bait CLASS; the fourth instance was one I introduced

### `TODOS.md` — 5.3.R64 — closed the copy-bait CLASS; the fourth instance was one I introduced

- [ ] Fifth heredoc mangling of the night en route (`[^ ]` collapsing into a real newline and breaking the test file). Caught by collection, fixed with an Edit and a regex that needs no

### `TODOS.md` — 5.3.R65 — closed the TrainResult-classification class; both survivors are legitimate

- [ ] **Four classes now closed by invariant rather than by inspection**: copy-bait examples (§5.3.R64), event-loop blocking (§5.3.R62/R63), skipped-counted-as-pass (§5.3.R15), and this. Each began as "I fixed the instance" and only stopped recurring when the *rule* was

### `TODOS.md` — 5.3.R66 — re-verified HEAD end to end before the operator's restart

- [ ] **HEAD is verified end to end and safe to restart into.** Remaining untested by a live run: `ideate`/`implement` (need Ollama, ~5 GB) and `calibrate-baseline` (needs the factory + corpus). Both wait on memory headroom; §5.3.R34 records the safe way to do the latter.

### `TODOS.md` — 5.3.R68 — my own fix reached one caller in five; the settings page lied about saving

- [ ] `createSession`/`touchSession`/`deleteSession` still discard the flag. Left deliberately: their failure loses a session list entry rather than credentials, and no UI currently claims success for them — so there is nothing lying yet. Recorded rather than fixed, so

### `TODOS.md` — 5.3.R70 — swept the views for the settings-page class; covered an untested invariant

- [ ] Webapp coverage is now: every file I touched tonight read end to end, every class I fixed swept, and the two subtle invariants (poll overlap, history filter) held by tests rather than by comments.

### `TODOS.md` — 5.3.R71 — verified item 7's fix is sound, after nearly filing a false alarm

- [ ] Standing correction to my own habit: before claiming *"nothing produces X"*, search the repo, not the directory I happen to be in — and confirm which artifact actually carries X. ### 5.3.R72 — re-verified my own scoped claims repo-wide; both hold

### `TODOS.md` — 5.3.R72 — re-verified my own scoped claims repo-wide; both hold

- [ ] Both survived, which is the useful outcome: after two scope errors the honest move was to re-test the claims rather than assume the pattern was confined to the two I noticed. Re-verification that confirms is not wasted — it is the difference between "probably fine"

### `TODOS.md` — 5.3.R73 — ⚠ UNCOMMITTED WORK FOUND IN A STASH FROM BEFORE THE MACHINE MOVE

- [ ] **OPERATOR — still live, and here is the data the decision needs (re-measured 2026-07-24 23:10, nothing applied/popped/dropped).** `stash@{0}: On main: pre-teleport`, created **2026-07-19**, base `8641fb9`, now **501 commits behind HEAD** (the earlier note

### `TODOS.md` — 5.3.R74 — ran the daemon itself, safely, and watched the new guard work

- [ ] **Every runtime path is now verified except the two that need resources this box does not currently have**: `ideate`/`implement` (Ollama, ~5 GB) and `calibrate-baseline` (factory + corpus). Both are blocked on memory, not on code.

### `TODOS.md` — 5.3.R75 — corrected a MEMORY that would have re-taught the false SOTA

- [ ] **Memory is the one artifact that outlives the transcript**, so a wrong entry there is worse than a wrong TODO — nothing in the next session's context contradicts it. This is the same class as §5.3.R59 (a status line describing a measurement the loop no longer took),

### `TODOS.md` — 5.3.R76 — swept the rest of memory; two more stale entries, one in the always-loaded index

- [ ] The through-line for the whole session, one layer out: **the code was usually right and the descriptions of it usually were not** — comments, docstrings, guards, prompts, dashboards, and finally the memory that outlives them all.
- [ ] NOTE for the operator's re-seed decision (#5): the re-seed should supply `metric_sem` from a **measured** run if one is available. A baseline re-seeded as a bare number is honest but keeps the loop on the weaker one-sample test indefinitely.
- [ ] CONSIDERED AND DECLINED: renaming the verdict key `significant` → `beyond_noise`. Grepped every consumer: only `evaluate.py` and the tests read it — no webapp, API, or package does. The misleading-name risk is real but internal, the direction is already
- [ ] NEXT: **improve dry_run correction feedback — but NOT until constraint-8 is measurable.** dry_run is 77% of genuine failures, and the likely lever is handing the corrector the actual tensor shapes at the failure point instead of a raw traceback.
- [ ] SUPERSEDED, kept for the record: did the constraint-8 refinement reduce dry_run? It was written to attack the dominant failure mode (77% of genuine deaths). Compare dry_run share of genuine failures for experiments created before vs after the prompt
- [ ] SUPERSEDED, kept for the record: **`validate_with_correction` pins `class_name` from the FIRST parse.** If a correction renames the class — plausible, since the corrector sees only code plus a traceback — every subsequent dry run looks for a class

### `TODOS.md` — 5.3.R106 — F821 sweep found 2 REAL undefined-name bugs in model/training code (not mine)

- [ ] **Recorded, NOT fixed by me — this needs the operator's intent.** Bug 1's fix is either "add `use_short_conv=False, use_relative=False, relative_max_distance=<N>` to `get_model`'s signature" OR "remove them from the call" — *which* depends on whether `DottieModel1B` is

### `TODOS.md` — 5.3.R105 — swept the WHOLE tree for the R103 bug class; one more, pre-existing, in the data pipeline

- [ ] **Recorded, not fixed by me:** it is pre-existing, not mine, and in a ruff-reformatted file — editing it pre-B0 would grow the merge for someone else's bug. Best fixed by the operator during B0 (or right after), where the ruff pass + this one-line change land together.

### `TODOS.md` — 5.3.R104 — read the operator's new ruff CI; it changes the B0 proof step and recipe

- [ ] **Net: B0 is now fully de-risked from my side.** Verified: the 21-conflict set, the `--ours`+ruff resolution, a py311-clean diff (§5.3.R103), the pytest suite as the true proof step, the ruff-version + red-CI gotchas, and (above) that `ci.yml` passes while `lint.yml`

### `TODOS.md` — 5.3.R102 — traced the false "training stale" alert to its exact line; corrects R100

- [ ] **Still correctly blocked:** the fix edits `dottie_continuous_loop.py`, which origin reformatted — so applying it pre-B0 grows the merge, and it can only be *verified* with the fleet up (to see real `metrics_nano.jsonl` vs the fallback). So B4 stays behind B0/B1, but

### `TODOS.md` — 5.3.R101 — /auto-mode engaged: spec gate satisfied, and the honest board for "build end to end"

- [ ] **What I WILL do autonomously each auto-mode tick without widening the merge:** keep `SPEC.md` / `TODOS.md` accurate as the source of truth, add only NEW files when a genuine new-capability task is confirmed, and re-verify state. I will NOT edit reformatted code

### `TODOS.md` — 5.3.R100 — the "training stale" monitor watches an agent-task log; false alarms guaranteed

- [ ] ⚠ **RE-VERIFIED LIVE 2026-07-24 23:19 — NOT low urgency any more, and NOT fixed. It was RENAMED.** `telemetry.py:598` now reads `training_monitor.get("metrics",{}).get("loss")`, which looks fixed until you follow it: line 560 defines

### `TODOS.md` — 5.3.R98 — git has diverged: 243 ahead / 2 behind, and the 2 are a repo-wide reformat

- [ ] **The durable lesson for the ops file:** I made ~25 commits before checking the remote, in a repo whose own discipline note says to check first. "Parallel sessions are active" is not a fact to record once; it is a check to run before the FIRST commit of a session. A

### `TODOS.md` — 5.3.R96 — the RE-SEED tool built the very weakness the re-seed exists to remove

- [ ] **Operator action, now a clean one-liner with a known result:** to clear the unreachable baseline, `python -m dottie.research calibrate-baseline --overwrite` (uses seeds 0,1,2). It will install ≈**5.737, SEM ≈0.099, n=3** — the measured honest baseline. Still your call

### `TODOS.md` — 5.3.R94 — measured the per-seed cost I had guessed; it was 20× too high

- [ ] Still the operator's call to implement (it changes what the loop trains), but now on accurate figures. Recorded here so the decision is not made against my inflated estimate.

### `TODOS.md` — 5.3.R93 — ❌ I RETRACT R91. The candidate is WORSE at every seed. Real wins: still ZERO.

- [ ] **The other half — `factory_trainer.py` must record `per_seed`.** The reorder alone changes nothing for the factory trainer's promotions because it records ONLY `eval_ce_per_batch` (confirmed live: `5a7232ffea24`'s verdict would now carry the warning,

### `TODOS.md` — 5.3.R92 — I hand-rolled a seed sweep the loop had already generated for me

- [ ] ⏳ `ab_nano.py` running (launched 15:14, 6 runs ≈ 80 min at ~13 min each). Its verdict is the canonical one and **supersedes R91's single-seed result** either way. R91 settled the mechanism with controls no seed sweep can replace; this settles reproducibility.

### `TODOS.md` — 5.3.R91 — ✅ CONTROL RESULT: the capacity confound is REFUTED. This is a REAL WIN.

- [ ] **Consequence for `2fd923b`:** the `CAPACITY-CONFOUNDED BASELINE` caveat now shown in `status.json` says this bar *"partly measures capacity rather than the idea."* **For THIS baseline that is now measured to be false.** The generic check is still right — it flags a
- [ ] Re-run cost is now known and non-trivial: **~13 min/variant under memory pressure** (~3× the recorded 249 s), 40 min total. Worth budgeting before the seed sweep.
- [ ] **⏳ SEED SWEEP RUNNING** (launched 14:59, ~55 min). R91 settled the *mechanism* but not *reproducibility*: every variant ran at the single default seed 1234, so the headline delta rests on one run per arm and cross-seed variance is unmeasured. Adds **seeds 0 and 1** to

### `TODOS.md` — 5.3.R89 — "one `uv pip install typer`" was wrong; scout-rtx needs a real env, so I stopped

- [ ] `apps/scout-rtx` stays **NOT VERIFIABLE** on the board, now with the true cost attached so the next reader is not misled into a five-second fix that is not one.

### `TODOS.md` — 5.3.R88 — I FABRICATED EVERY TIMESTAMP IN R72–R87. Second time this session.

- [ ] Everything measured in R72–R87 stands — suite counts, ledger reads, parameter deltas and memory figures were all read from tools. **Only the clock was invented.** Which is precisely why it survived: none of my verification passes ever checked the one field I was

### `TODOS.md` — 5.3.R87 — ⚠ I WITHDRAW QUEUE ITEM 9. `apps/dottie` IS GREEN: 199 passed.

- [ ] **Worth doing, small:** `resolve.py`'s error should say *"set AVA_FACTORY_ROOT — on this box the working value lives in `research_orchestration/research_env.local.ps1`"*. The message lists probed paths but never names the file that already holds the answer, which is

### `TODOS.md` — 5.3.R86 — ⚠ THERE IS A THIRD SOTA ROW, AND "REAL WINS = ZERO" IS NO LONGER TRUE

- [ ] **THE DECISIVE EXPERIMENT — ⏳ RUNNING as of 14:31, results pending.** Not blocked after all: it needs the TRAINER, not Ollama, and `train` is exactly the stage the memory guard permits. Script: `$CLAUDE_JOB_DIR/tmp/capacity_control.py`; results land in

### `TODOS.md` — 5.3.R84 — ran R83's follow-up; the second wrong number on my board was mine

- [ ] NEXT: the corrected board should be re-stated in one place. R78's table now has a known-wrong row (ava-skills 66 → 80) and a stale one (ava-factory 461 → 485).

### `TODOS.md` — 5.3.R83 — 15 tests had not been running, and the suite reported it as "470 passed"

- [ ] NEXT: the same collection-diff check on the other suites. ava-factory was the only one with an ignore hook, but "only this suite has one" is an assumption I have not measured — and this entry exists because an unmeasured assumption hid 15 tests.

### `TODOS.md` — 5.3.R82 — read the three unread webapp modules; the bug was in the tests, not the code

- [ ] **NOTED, not fixed — a latent falsy-zero bug at `manifest.py:318`:** `now + (lease_seconds or self.lease_seconds)`. An explicit per-claim `lease_seconds=0` (meaning "expire immediately") would silently fall back to the manifest default instead.

### `TODOS.md` — 5.3.R81 — the live loop is already encoding-clean; the restart script was lying about 14b

- [ ] Memory is recovering on its own: **3,051 MB at 12:49 → ~3,880 MB at 13:18**, still short of the 6,183 MB an `ideate` now requires. `wsl --shutdown` is what closes that gap.

### `TODOS.md` — 5.3.R80 — went looking for writes, found seven scripts living in two places at once

- [ ] **NEXT (unchanged priority):** the 203 encoding-less writes from R79 are still unfixed; `PYTHONUTF8=1` remains the recommended one-line answer for the whole class, and the per-site work is belt-and-braces after that. Note the duplication means **any per-site

### `TODOS.md` — 5.3.R79 — the text-I/O class, measured properly: 360 sites, and ONE setting that fixes all

- [ ] **RECOMMENDED, operator's call because it is environment config:** set `PYTHONUTF8=1` for the venvs, the scheduled task, and the Docker images. That is one line per surface versus 360 edits, and it also covers every site added tomorrow. Python 3.15 makes UTF-8
- [ ] Keep fixing individual sites opportunistically as belt-and-braces — env config helps only where the env is set, and a script run by hand outside it gets the old behaviour. **Priority order: the 203 writes first**, and among those the ones writing files other

### `TODOS.md` — 5.3.R78 — measured EVERY suite for the first time; my board had been covering 3 of 11

- [ ] NOTE: `apps/scout-rtx` needs `typer` before it can be judged at all. ~~One `uv pip install typer` in the right env would move it from unknown to measured.~~ **WRONG — see §5.3.R89: 7 of 10 declared deps are missing and collection needs 4 of them, including the
- [ ] The three bugs this tick share one shape with the docstring/comment class: **text I/O that is correct on the machine it was written on.** Worth a repo-wide sweep for bare `read_text()`/`write_text()`/`open(...,"w")` in the remaining packages — graphify was the

### `TODOS.md` — 5.3.R — REVIEWER BRIEF for the MLBR bundle (written by the loop 2026-07-20 03:30)

- [ ] STILL OPEN (needs a design decision): paired-seed evaluation — same seeds for baseline and candidate would kill most of this variance rather than just gating on it. Also: baselines record no param count, so the param comparison is informational
- [ ] **DEEPEST ISSUE FOUND TONIGHT — the block-swap integration has a structural confound (queued, needs your call).** `factory_nano_block_swap` measures a candidate by REPLACING a real parameterized fusion block with it. So every parameter-free
- [ ] YOUR CALL on the live ledger: MLBR (`23bb41375804`) was promoted under the old bare-`<` rule and MOVED the baseline 5.61982→5.60506. Options: (a) leave it — the bundle is human-gated anyway and §5.3.R documents the truth; (b) re-seed the

### `TODOS.md` — 7.8 — factory server: three endpoints blocked the event loop (fixed 06:00)

- [ ] **Not done: caching.** `collect_status()` still recomputes per request, so N clients cost N walks. A 2–3 s TTL would make it robust regardless of caller behaviour. Left for you because it changes freshness semantics on a dashboard whose whole point is honesty

### `TODOS.md` — 8 — Known issues backlog (honest ledger, none import-breaking)

- [ ] test_api.py 4 env failures on this box (pre-existing, verified vs HEAD 2026-07-20): echo task / task counts / ollama honest-fail / flywheel gate all hit `DottieResolutionError: ava-...` — AVA_FACTORY_ROOT resolution, not code. Fix the env

### `TODOS.md` — New items (added 2026-07-19 evening)

- [ ] **PREVENTION (user action)**: register a machine-level Task Scheduler job — At startup, run `ollama serve` as your user "whether logged on or not" (needs your password at registration, so Claude can't do it) — or switch Ollama to a Windows
- [ ] **§5 TIMEOUT×CADENCE INTERACTION (measured 03:29, file before it bites again).** The 03:05 tick has been running 22+ min with no log line. Measured state: Ollama is healthy and responsive (v0.31.1) but **idle** — 0 CPU over an 8s sample — and the 14b
- [ ] ⚠⚠ **CORRECTION (04:00) — READ THIS BEFORE THE ENTRY BELOW. The runner is a DAEMON, and that invalidates most of my "lost tick" analysis.** The scheduled action is `research_worker.ps1 run …` with **no `--max-actions`**, which defaults to **0 = run
- [ ] ~~§5 ROOT CAUSE (03:42) — worker processes finish their work but never EXIT~~ **(SUPERSEDED by the correction above — the process-never-exits framing was wrong for the daemon; the orphan measurements below are still real and still useful.)** Measured after stopping the stuck
- [ ] **§5 runner incident 3 (03:00) — SAME zombie pattern, now understood.** The task sat in state `Running` with NO worker process alive (checked: no python/powershell from that instance), i.e. Task Scheduler still believed a run was in flight. With
- [ ] §5 runner incident 2 (02:15): the 01:05 runner instance died with 0xC000013A (console-interrupt semantics; cause UNEXPLAINED — no ExecutionTimeLimit is set) and its still-running corpse made `IgnoreNew` swallow the 02:05 trigger. Recovered by
- [ ] §7: after fleet rebuild, verify the Control Plane source tables show the 30-source registry and the new telemetry stream renders.

### `TODOS.md` — Weekly ops sweep (2026-07-20 00:45 — measured, safe actions taken)

- [ ] **Janitor does NOT rotate branch-run checkpoints**: /ckpt/tool = **51 GB** (~29 × 1.76 GB, every step file 50→1110 present; the 15-step crash cadence multiplied this). After tool_final lands + eval gate passes: keep tool_final + last 2 steps, delete the
- [ ] Deferred deliberately: build-cache prune (36.5 GB — it speeds the §2.1 rebuild; prune AFTER 2.1) and `docker image prune -a` (23 GB more — old images are rollback insurance until the rebuilt fleet proves out; prune after 2.2 verification).

### `tasks/todo.md` — Phase 2: GUIDE digest + agent tiles

- [ ] Agent-activity tiles (research loop / fleet / trainer) — deferred; the digest is the higher-value half and shipped first.

### `tasks/todo.md` — 🔴 THE GATE'S FIRST RUN FOUND A LIVE PROVENANCE DEFECT

- [ ] **Fix = redeploy** (G2, the operator's gated step per the plan — I did not deploy). After deploying, `--post` must go green before the alias moves.
- [ ] **S4** G4 writes `data/last_good_deployment.txt` (pin becomes an output of a passed gate, not a hand-edited input); deploy runbook becomes gate-driven.
- [ ] **S7** G5 watch loop — scheduled liveness + freshness probe. Stale WARNS, never fails: stale is a documented honest state, and a gate that fires on a legitimate state gets disabled (the `lint.yml` permanently-red lesson).
- [ ] **OPERATOR FORK — the assistant has no brain in production, and no amount of code changes that.** `api/assistant-chat.mjs` returns `source:"offline"` unless `DOTTIE_CHAT_URL` is set, and it is unset in prod because the box is

### `tasks/todo.md` — Then — Phase 3: MONITOR runtrack readout

- [ ] Bridge `runtrack` (scout-cli openswap, pure-sqlite) to the live trainer/research metrics + the ledger.
- [ ] Monitor card: live training curve(s), research experiments/promotions, fleet stats, run comparison. Real-measured; stale/offline honest.

### `tasks/todo.md` — External data expansion (operator directive — validated sources)

- [ ] Scale OAPEN (`--full` + higher `--target`), then the operator lands the `sources.yaml` entry (frozen config). Decon note: OAPEN can't overlap the CURRENT held-out (not a generator); `HELDOUT_SEED` disjointness applies
- [ ] Future clean expansions: broaden Gutenberg, Standard Ebooks, PMC-OA, Wikisource.

### `tasks/todo.md` — Adversarial code review (2026-07-24) — findings addressed

- [ ] Deferred (latent, no current card hits them): multiple-config `dataset_info` (sums across configs) + quoted/glob `path:` values. Fix when a card needs them.

### `tasks/todo.md` — Gated / dependency-blocked (Phase 4)

- [ ] **HF publish** (Hub ↔ real HuggingFace) — BLOCKED on `HF_TOKEN` rotation (provenance audit #6). Show an honest "mirror: awaiting token rotation" until rotated; then wire the authed push (operator runs the token step).
- [ ] **Engine ReAct trace** (Guide chat) — needs the factory hub `/assistant` to expose a stable `steps[]`; verify the engine field first, pass through `server.mjs` verbatim.

### `tasks/todo.md` — Operator calls (from the provenance audit — deliberately not auto-done)

- [ ] Rotate the previously-committed `HF_TOKEN` and place the new value in the gitignored `apps/ava-factory/.env` (I cannot write the secret).
- [ ] #7 baseline-provenance gate in `evaluate.py` (code defers it to operator).
- [ ] Equities checkpoint for real asset regen (KPI card + skills radar still synthetic-flagged); ~66% synthetic curriculum mix; stale config labels (frozen path); dead `train_1b_deepspeed.py` path.

