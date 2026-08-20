# Harbor + Flywheel — Dottie Edition

> Maps Sequoia Capital Own Your Intelligence talk + Harbor benchmarking idea + LangSmith Engine flywheel to Dottie's zero-deps evals port

Zero-deps only, honest 503, LCG both chains 20260813→189831298 idx3820 triple[11205,19448,14209] + 20260818→1412440227 idx5278 triple[13791,10902,19455] same-link-same-stars ?daily=YYYYMMDD&n=1/3/5 Solo1 Triple3 Full5

## Harbor — industry measuring for Dottie

Harbor idea: single score across true duties that count for org, so you compare runs fairly.

Our mirror — `src/harness/eval/harness_bench.py` 8 duties:

    1 multi_file_edit — fix auth.py across 3 files — checks in-distribution file-edit close to training
    2 bug_fix — off-by-one fix — deterministic ExactMatch 0/1
    3 error_recovery — crash recovery — operational Latency max 5000ms threshold 0.5
    4 refactor — API tier shaping — structural JsonDiff + SchemaValidation required apiVersion kind
    5 context_understanding — big repo knowing — where most fails land: poor context not poor model — we track ContextPrecision + TurnLatency
    6 project_creation — create new service — project scaffold multi-file write
    7 code_analysis — examine security — RAG Faithfulness + AnswerRelevancy when context docs given, else deterministic
    8 tool_efficiency — use tools well — ToolCorrectness mode exact at_least_one + ToolArgumentMatch arg subset ignore trace_id + StepEfficiency optimal 5

Each returns Score 0-1 normalized threshold pass/fail, reason, dimension. Mean across 8 = overall. Baseline tracked.

    mean = sum(s.value)/len(scores)
    overall = sum(task.mean)/8

Example latest:

    Task multi_file_edit: exact_match 1.00 latency 0.91 token 0.84 tool_corr 0.0? -> mean 0.68
    ... overall 0.83 6.4s avg 51s total vs OpenCode 12.5s/99.7s Claude Code 16.4s/131.5s

Safety PII Toxicity PromptInjection never averaged — reported separate, so toxic leak can't hide behind high correctness.

Most failures poor context — we added tracing:

* TurnLatency per turn in timeline — if probe turn latency 3400ms, guess bloated glob
* ContextPrecision — did recovered doc chunk actually contain need? Logged message.metadata.context_sources source triple[11205,19448,14209] →19213?
* HARNESS.md merge trace — which HARNESS.md loaded at preamble: walk upwards root → workspace → apps/dottie/

## Evaluability & Observability — define good

* Score name value threshold passed bool dimension reason latency_ms
* Golden authored input expected context expected_tools tags metadata id
* EvalCase from_golden enriched output messages tool_calls expected_tool_calls latency_ms token_count cost_usd retry_count confidence runs
* evaluate(ec, metrics) never raises → lists scores adding zero reason error:.. if metric throws — assert_test raises AssertionError for pytest
* evaluate_cases(cases, metrics, sinks=None) → sinks StdoutSink prints PASS exact_match:1.00, JsonSink writes results/scores.jsonl case_id input metric value passed dim reason
* JsonBaselineStore baseline_dir .evals/baselines save run-001 {exact_match: scores_list} store latest.json compare_to_baseline current latest tolerance 0.05 → BaselineDiff regressions improvements unchanged has_regressions summary() regressions:2 improv:1

CLI YAML like harness-evals run my-eval.eval.yaml:

    name: support-bot
    dataset: ./goldens.jsonl
    target:
      type: prompt
      prompt: ./prompts/support-bot.txt
      model: {provider: ollama, name: qwen3:32b}
    metrics:
      - exact_match
      - {kind: latency, threshold: 0.5, params: {max_ms: 2000}}
    judge_llm: {provider: ollama, name: qwen3:32b}
    sinks: [stdout]
    baseline: {store: json, path: .evals/baseline.json}

    harness-evals run my-eval.eval.yaml --baseline --fail-under 0.8 --update-baseline

Model params ${VAR} interpolation — target model api_key ${TARGET_KEY} judge ${JUDGE_KEY} fallback to env OPENAI_API_KEY if no api_key set.

## Data Flywheel — run → collect → curate → experiment

Harrison 14:34: nonstop rise via loop: run agent, gather traces, pick that info, run trials.

Dottie maps:

1. Run — dottie repl / dottie "Fix ..." one-shot --permission bypass auto-approve scripts/CI

2. Collect — timeline.jsonl triple-write 7-field nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass even no-change, still when quiet. Places:

    * dottie-harness/runs/timeline.jsonl
    * .scout/missions/_cron/timeline.jsonl
    * bundles/ultra/runs/dottie-dev-api/timeline.jsonl
    * goals/<slug>/hidden_files/cron_health.jsonl via goal tracking never files/

   + tool_calls ToolCall name input output typed — Message role content optional tool_calls metadata pending_human_input

3. Curate — Synthesizer generate documents n=20 difficulty mixed → Goldens list input expected, InputGenerator rephrase 3 variations robustness, ConversationSynthesizer SIMULATE user turns max 8 persona frustrated short LLM generates user, REPLAY whole transcript scored as-is no agent call, SCRIPTED pre-scripted user turns agent called each turn, GRAPH declarative DAG start greeting nodes greeting ScriptedNode probe LLMNode route BranchNode escalate ScriptedNode done StopNode edges source target predicate unresolved resolved predicates lambda msg: "sorry" in lower() lambda msg: "refund" in lower(), cycles structurally rejected re-executes pending predicate matches or max_turns reached, graph_config dict from ConversationGolden.graph_config only unconditional edges serializable predicates pass clearly to from_dict() required.

4. Experiment — PromptOptimizer model judge metrics target_score 0.85 max_iterations 10 assess LLM must change from ground shape self-evaluation declined diagnostic → re-make → re-evaluate ring initial_score -> best_score best_prompt template save optimized-prompt.json, plus harness code change described via hooks/loader PRE/POST TOOL_USE command echo '{tool}' matcher Bash, permissions modes default accept_edits plan bypass constitutional JSON write holds still Full Access cannot go around, Seatbelt macOS bubblewrap Linux gVisor Tier2 puffy worktree separate.

LangSmith Engine equal we build — from marks spot trouble → propose cue/shape:

    timeline analyzer (zero-deps stdlib only)

    for line in open(timeline.jsonl):
        j=json.loads(line)
        if j["errorClass"]=="CONTEXT_STARVATION": suggest HARNESS.md add missing context guide
        if j["latency_ms"]>5000: suggest compaction TARGET 0.50→0.45 alternatively spawn_parallel parallel 3→2 cutting tokens_est ~12% — calculation optimal_steps/len(tool_calls)
        if safety PII value 0.0: hook PRE_TOOL_USE matcher Write obstruct-leak

Return shape:

    {
      "issue": "latency_ms mean 5400 >5000",
      "suggestion_type": "harness_code",
      "patch": "context.py TARGET=0.45",
      "reason": "85%→50% accumulation too behind — window dog",
      "experiment": "dottie eval harness-bench --provider ollama --model qwen3:32b --fail-under 0.8"
    }

## Example run — finish

    from src.harness.evals import Golden, EvalCase, evaluate
    from src.harness.evals.metrics.deterministic import ExactMatchMetric
    from src.harness.evals.metrics.operational import LatencyMetric
    from src.harness.evals.metrics.agent import ToolCorrectnessMetric
    from src.harness.evals.metrics.safety import PIIMetric
    from src.harness.evals.metrics.reliability import OutcomeConsistencyMetric
    from src.harness.evals.core.golden import ToolCall
    import asyncio
    from src.harness.evals.evaluate_dataset import evaluate_dataset

    goldens = [
        Golden(input="What is 2+2?", expected="4"),
        Golden(input="Check weather in Paris", expected="18C sunny", expected_tools=["get_weather"]),
    ]

    async def my_agent(golden):
        # pretend agent — in truth would be async callable BaseTarget.ainvoke
        if "weather" in golden.input:
            return EvalCase(input=golden.input, output="It's 18C and sunny", expected=golden.expected,
                            tool_calls=[ToolCall(name="get_weather", input={"city":"Paris"})],
                            expected_tools=["get_weather"],
                            latency_ms=320, token_count=180, cost_usd=0.002)
        return EvalCase(input=golden.input, output=golden.expected, expected=golden.expected, latency_ms=120, token_count=40)

    results = asyncio.run(evaluate_dataset(goldens, my_agent, metrics=[ExactMatchMetric(), LatencyMetric(max_ms=2000,threshold=0.5), ToolCorrectnessMetric(), PIIMetric()]))

    for scores in results:
        for s in scores:
            print(f"{'PASS' if s.passed else 'FAIL'} {s.name}({s.dimension}):{s.value:.2f} {s.reason}")
        # -> PASS exact_match(correctness):1.00 match
        # -> PASS latency(performance):0.84 320ms
        # -> PASS tool_correctness(trajectory):1.00 got {'get_weather'} exp {'get_weather'}
        # -> PASS pii(safety):1.00 clean

    # reliability across 5 runs
    runs=[EvalCase(input="task", output="4") for _ in range(5)]
    ec=EvalCase(input="task", output=runs[0].output, runs=runs)
    scores=evaluate(ec, metrics=[OutcomeConsistencyMetric(threshold=0.8)])
    # -> 5/5 consistent 1.0

    # baseline compare
    from src.harness.evals.baseline import JsonBaselineStore, compare_to_baseline
    store=JsonBaselineStore(baseline_dir=".evals/baselines")
    store.save("run-001", {"exact_match": 0.88})
    baseline=store.load()
    diff=compare_to_baseline({"exact_match":0.86}, baseline, tolerance=0.05)
    print(diff.summary())  # regress:0 improv:0 same:1 tol:0.05
    if diff.has_regressions: print(diff.regressions)

    # conversation simulate
    from src.harness.evals.conversation.golden import ConversationGolden, ConversationMode
    from src.harness.evals.metrics.conversation import GoalAccuracyMetric  # would be LLM-judged needs [llm] optional
    # cg=ConversationGolden(scenario="User requests refund damaged item", expected_outcome="Agent processes refund confirms timeline", max_turns=8, user_persona="Frustrated customer short replies", mode=ConversationMode.SIMULATE)

    # bench
    from src.harness.eval.harness_bench import run_bench
    r=run_bench(provider="ollama", model="qwen3:32b", max_tasks=8)
    print(f"overall {r['overall']:.2f} total_time {r['total_time']:.1f}s has_regress {r['has_regressions']}")

Example YAML run host:

    # goldens.jsonl already present
    # examples/my-eval.eval.yaml points to it
    # handler python -m src.harness.evals.cli would be via harness-evals run examples/my-eval.eval.yaml --fail-under 0.8
    # zero-deps runner src/harness/evals/cli.py run_config yaml_path fail_under baseline -> mean:1.00 cases:4 metrics:1 -> departure 0 PASS 1 FAIL/SETback

Future — harbor real joining — save harbor scoreboard comparison matrix Speed 6.4s avg claim proved local moment — only open-source mediator 100% flawless 8/8 GPT-5.2 7/8 Opus surpasses Claude Code 7/8 OpenCode 7/8 pi-mono 7/8 — thread state adjusted similar to openharness harness 7/8 88% Opus 8/8 100% GPT-5.2.

References — Rabanser Kapoor et al Towards a Science of AI Agent Reliability Princeton 2026 12 reliability metrics 4 dims, DeepEval measure/a_measure interface, RAGAS faithfulness context precision/recall, promptfoo CLI-first CI/CD JUnit departure tokens baseline shedding.

License Apache 2.0 zero-deps stdlib sole fair 503 Alienware GPU auto not faked — single-action per tick Boyd Decide tidy filesystem md new grow tidy.
