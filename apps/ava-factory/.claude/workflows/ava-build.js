export const meta = {
  name: 'ava-build',
  description: 'Build phases P0-P5 of the Ava nano pilot: scaffold, datagen x4, model fixes, tokenizer, packing, trainer, bench',
  whenToUse: 'Run once from the foreman session to build everything up to (not including) the long nano training run. P6+ (training, evals-run, deploy) stays foreman-driven.',
  phases: [
    { title: 'Scaffold', detail: 'P0: env, config, Makefile (A1-A3)' },
    { title: 'Build', detail: 'P1: generators B1-B4 in parallel + P1\': model fixes D1-D2' },
    { title: 'DataPipeline', detail: 'P2 tokenizer -> P3 packing' },
    { title: 'Trainer', detail: 'P4: jlosses + train loop (F1-F2)' },
    { title: 'Gate', detail: 'P5: bench + budget lock + smoke rehearsal readiness' },
  ],
}

// ---- shared bits -----------------------------------------------------------
const REPO = '/home/user/ava-agi-factory-v6-4'
const RULES = `
WORKER RULES (binding):
- Repo: ${REPO}. Read your spec section FULLY before writing code.
- Implement EXACTLY the deliverable files your spec lists. Touching blueprint files is forbidden
  unless the spec says "surgical in-place fix" (only specs/04 allows that, for model_1b.py and multi_jspace_module.py).
- No network calls in produced code (HF hub and wandb are BLOCKED here). No new pip deps beyond scripts/setup_env.sh.
- All randomness seeded via config/CLI; same seed => byte-identical output.
- Ship the tests your spec names; run your acceptance command(s) yourself before returning.
- Do NOT run git commands. Do NOT commit.
`
const RESULT_SCHEMA = {
  type: 'object',
  required: ['task_id', 'status', 'files', 'acceptance_cmd', 'acceptance_passed', 'notes'],
  properties: {
    task_id: { type: 'string' },
    status: { type: 'string', enum: ['done', 'partial', 'failed'] },
    files: { type: 'array', items: { type: 'string' } },
    acceptance_cmd: { type: 'string' },
    acceptance_passed: { type: 'boolean' },
    notes: { type: 'string', description: 'deviations from spec, open concerns, raw failure output if any' },
  },
}
const task = (id, tier, prompt, phaseTitle) =>
  agent(`${RULES}\nTASK ${id}\n${prompt}`, {
    label: id, model: tier, phase: phaseTitle, schema: RESULT_SCHEMA,
  })

// ---- P0 Scaffold (blocking: everything depends on it) ----------------------
phase('Scaffold')
const a = await task('A1-A3', 'sonnet', `
Implement ALL of specs/01_environment.md: scripts/setup_env.sh (run it too), ava/__init__.py,
ava/config.py (AvaConfig + load(preset) + "python -m ava.config --preset nano --count-params" CLI;
model construction for param-count may import model_1b lazily and, if it fails pre-fix, compute the
count analytically from the config — note which path you used), verify configs/nano.yaml +
configs/nano_quick.yaml exist (create nano_quick.yaml as a copy of nano.yaml with tokens_total 15M
if missing), Makefile, pytest.ini, .gitignore additions, ava/datagen/base.py Generator ABC.
Acceptance: bash scripts/setup_env.sh && python -c "import torch, tokenizers, fastapi" &&
python -m ava.config --preset nano --count-params  (expect 13-16M).`, 'Scaffold')
if (!a || a.status === 'failed') { log('Scaffold failed — aborting'); return { aborted: 'A1-A3', detail: a } }

// ---- P1 fan-out: 4 generators (sonnet) + model fixes (opus) ----------------
phase('Build')
const buildSpecs = [
  ['B1', 'sonnet', 'Implement the B1 section of specs/02_data_generation.md: ava/datagen/logic.py + its tests in tests/test_datagen.py. Target >=30MB at seed 1234 into data/nano/raw/.'],
  ['B2', 'sonnet', 'Implement the B2 section of specs/02_data_generation.md: ava/datagen/math_gen.py + tests. >=40MB, includes P3 word problems and temporal workflow logs.'],
  ['B3', 'sonnet', 'Implement the B3 section of specs/02_data_generation.md: ava/datagen/encyclopedia.py AND ava/datagen/code_gen.py + tests. >=50MB combined. The canonical eval entities (spider/ant legs, France/China facts, soccer/rugby, Spanish/French pairs) MUST be covered with the paraphrase counts the spec requires — the 5 J-space eval tests depend on it.'],
  ['B4', 'sonnet', 'Implement the B4 section of specs/02_data_generation.md: ava/datagen/chat_safety.py + tests. >=20MB. Safety scenarios stay abstract/templated (scenario + refusal + benign near-twin).'],
  ['D', 'opus', 'Implement ALL of specs/04_model_and_configs.md: surgical in-place fixes to model_1b.py and multi_jspace_module.py (causal mask via SDPA, rotate_half layout, fusion precedence, _prev_workspaces detach + use_memory gate + batch-size guard, JacobianLens.top_concepts, verbalizer tied to lm_head, full size parameterization from AvaConfig, per-forward shared RoPE) + tests/test_model.py (causality perturbation test, rotary relative-position test, B=2-then-B=3 train steps, top_concepts realness, nano param count 13-16M). Acceptance: pytest tests/test_model.py -x -q green in <60s on CPU.'],
]
const build = await parallel(buildSpecs.map(([id, tier, p]) => () => task(id, tier, p, 'Build')))
const failedBuild = build.filter(r => !r || r.status === 'failed')
if (failedBuild.length) log(`Build failures: ${JSON.stringify(failedBuild.map(r => r?.task_id ?? 'crashed'))} — foreman must repair before P4/P6`)

// gen_all_data manifest once all four generators exist
const b5 = await task('B5', 'sonnet', `
Implement scripts/gen_all_data.py per specs/02_data_generation.md (seed-derivation table, per-file
sha256 manifest at data/nano/raw/MANIFEST.json). Run it end-to-end with --seed 1234, then run the
full pytest tests/test_datagen.py. Report corpus size per generator.`, 'Build')

// ---- P2 -> P3 pipeline (tokenizer then packing) ----------------------------
phase('DataPipeline')
const dataPipe = await pipeline(
  [{ id: 'C1' }],
  () => task('C1', 'sonnet', `
Implement ALL of specs/03_tokenizer.md: ava/tokenizer.py, train the BPE-8192 on the stratified
sample, save data/nano/tokenizer/ava_nano_bpe.json, tests/test_tokenizer.py.
Acceptance: 1k-doc round-trip exact; >=3.0 chars/token on heldout; load <1s; pytest green.`, 'DataPipeline'),
  () => task('E1', 'sonnet', `
Implement the packing section of specs/05_training.md: ava/data.py + scripts/build_dataset.py +
tests/test_data.py. Run scripts/build_dataset.py --preset nano. Acceptance: per-phase token counts
within +/-10% of configs/nano.yaml budgets; heldout files exist; decode-sample test green.`, 'DataPipeline'),
)

// ---- P4 trainer (opus) — needs D done; runs regardless and reports if blocked
phase('Trainer')
const f = await task('F1-F2', 'opus', `
Implement the trainer sections of specs/05_training.md: ava/jlosses.py (exact blueprint weighting,
reuse MultiJSpaceLosses) and ava/train.py (WSD, 6-phase manager with seq/RoPE transitions,
grad-accum to 8192 tok/step, checkpoint every 250 steps with model+optimizer+step+phase+RNG+sampler
state, --resume bit-exact, stable ckpt at 92%, metrics.jsonl schema per spec, --branch chat --init
<ckpt> with REAL load_state_dict + freeze_spaces + router bias, --device cpu|cuda with bf16 autocast
on cuda) + scripts/smoke_e2e.sh + tests/test_train_smoke.py.
Acceptance: pytest tests/test_train_smoke.py -x -q: 50-step lm_loss strictly decreasing on a small
slice, all j-loss terms finite+nonzero, kill-at-step-30 then --resume reaches identical step-50 loss
within 1e-4, metrics keys complete.`, 'Trainer')

// ---- P5 gate ----------------------------------------------------------------
phase('Gate')
const g = await task('G1', 'sonnet', `
Implement scripts/bench_throughput.py per specs/05_training.md, run it (seq 256/512/1024
steady-state tok/s), write runs/bench.json, apply budget rule clamp(tok_s*6h, 15M, 40M): report
which preset (nano vs nano_quick) is selected and the projected wall-clock for the base run.`, 'Gate')

return {
  scaffold: a,
  build,
  manifest: b5,
  data_pipeline: dataPipe,
  trainer: f,
  bench: g,
  next: 'Foreman: repair any failed/partial tasks, run scripts/smoke_e2e.sh (G2), update TODOS.md, commit, then launch P6 nano training per ORCHESTRATION.md.',
}
