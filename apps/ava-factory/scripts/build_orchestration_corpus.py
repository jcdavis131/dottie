#!/usr/bin/env python
"""Build the orchestration corpus: real mined traces + a seeded synthetic battery.

Sources (schema v1, one JSON object per line in corpus.jsonl):

  1. ultra_timeline    — real harness run timelines under bundles/ultra/runs.
                         NOTE: pipeline/runs is a byte-for-byte mirror of
                         bundles/ultra/runs; we read ONLY the bundles tree so
                         no cross-mirror dedupe is needed.
  2. workflow_journal  — metadata-only extraction from a workflow journal dir
                         (outside the repo; passed via --journal-dir). ZERO-TEXT
                         RULE: only numbers, booleans, timestamps,
                         closed-vocabulary categoricals, and opaque ids cross
                         into the corpus. No summaries, notes, file lists,
                         message/thinking/tool text, cwd, branch names, or raw
                         model ids are ever extracted.
  3. synthetic_battery — seeded template-grammar goals labeled by the SAME
                         heuristic functions the harness router uses
                         (apps/scout-cli/bigbang/plugins/harness/cli.py).
                         Battery labels are pure functions of the goal text —
                         we never call graph-plan, so the mutable
                         ~/.cache/scout/checkpoints state cannot drift labels.

Provenance is labeled per record AND per field: a record is 'measured' only
when all reward inputs (status + latency + tokens) are measured; everything
else is 'simulated'. Never present simulated numbers as measured.

CLI:
  python build_orchestration_corpus.py build [--out DIR] [--ultra-dir DIR]
         [--journal-dir DIR] [--battery-n N] [--seed S]
  python build_orchestration_corpus.py stats [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_AVA = Path(__file__).resolve().parents[1]   # apps/ava-factory
_REPO = Path(__file__).resolve().parents[3]  # repo root

# Import the harness heuristics directly (pure functions, deterministic —
# byte-identical outputs verified across invocations). Do NOT shell out to
# `scout harness route`: it crashes with KeyError on zero-keyword goals and
# in-process calls are ~100x faster for battery generation.
sys.path.insert(0, str(_REPO / "apps" / "scout-cli"))
from bigbang.plugins.harness.cli import (
    INTENT_KEYWORDS,
    _classify_moma,
    _complexity,
    _routed_agents,
    _score_intent,
)

SCHEMA_VERSION = 1

# FIXED ORDER — model lanes index their softmax by this vocab.
TIER_VOCAB = ["deterministic", "llm", "deep_research", "action_operator", "agentic_epic"]

DENSE_FEATURES = ["n_words", "n_chain_signals", "has_code_terms", "latency_ms", "tokens_est", "attempt"]

# Must stay the EXACT set of apps/scout-cli/bigbang/plugins/harness/timeline.py:28
# so reward semantics and the harness G_history miner agree ('blocked' is S=0,
# not a failure).
FAILURE_STATUSES = {"fail", "failed", "error", "timeout"}

CODE_TERMS = {
    "code", "build", "test", "deploy", "api", "bug", "fix", "refactor", "cli",
    "pipeline", "json", "python", "script", "repo", "harness",
}

INTENT_TO_TIER = {
    "agentic_loop": "agentic_epic",
    "deep_research": "deep_research",
    "complex_action": "action_operator",
    "deterministic": "deterministic",
}

PHASE_TO_TIER = {
    "recon": "deep_research",
    "proposals": "llm",
    "spec": "llm",
    "build": "agentic_epic",
    "validate": "action_operator",
}

# The single wall-clock-measured ultra timeline row (agents/cli.py:160-161,175);
# every other row's latency is a scripted constant.
MEASURED_ULTRA_NODE = "langchain.run.decide_act"

REWARD_CONFIG = {
    "weights": {"status": 0.6, "latency": 0.25, "tokens": 0.15},
    "weights_rationale": "0.6 > 0.25 + 0.15: speed can never buy back a failure",
    "failure_statuses": sorted(FAILURE_STATUSES),
    "status_score": "S = -1.0 if status in failure_statuses; S = 1.0/max(1, attempt) if status == 'ok'; else 0.0",
    "node_scale": {
        "latency": "R_lat = clip(1 - latency_ms/100.0, 0, 1)",
        "tokens": "R_tok = 1 - min(log(1+tokens_est)/log(1+256), 1)",
        "latency_scale_ms": 100.0,
        "tokens_log_cap": 256,
    },
    "agent_scale": {
        "latency": "R_lat = exp(-duration_s/600.0)",
        "tokens": "R_tok = 1 - min(log(1+output_tokens)/log(1+32768), 1)",
        "duration_tau_s": 600.0,
        "tokens_log_cap": 32768,
    },
    "reward": "clip(0.6*S + 0.25*R_lat + 0.15*R_tok, -1, 1)",
    "synthetic_battery_reward": "1.0 flat (labels are rule-derived from the same heuristic - label-match by construction), provenance simulated",
    "note": (
        "node-scale constants fitted on latency distribution min 0 / p50 35 / "
        "p95 55 / max 55 ms and tokens max 200 - but 12/15 of those latencies "
        "are SCRIPTED constants (45/30/35/55 hardcoded at "
        "apps/scout-cli/bigbang/plugins/agents/cli.py:146,167,171,223)"
    ),
}


# ---------------------------------------------------------------- shared features
# Other lanes replicate these definitions EXACTLY — keep them in named
# module-level functions and do not change the expressions.

def n_words(goal_text: str) -> int:
    return len(goal_text.split())


def n_chain_signals(goal_text: str) -> int:
    # Full expression of harness cli.py:64.
    t = goal_text.lower()
    words = len(goal_text.split())
    return len(re.findall(r"(->|then|after|next|→)", t)) + (1 if " and " in t and words > 10 else 0)


def has_code_terms(goal_text: str) -> bool:
    return any(tok in CODE_TERMS for tok in re.findall(r"[a-z0-9]+", goal_text.lower()))


def split_bucket(split_key: str) -> int:
    return int(hashlib.sha256(split_key.encode()).hexdigest(), 16) % 10


def split_name(bucket: int) -> str:
    # buckets 0-7 train, 8 val, 9 test
    if bucket <= 7:
        return "train"
    return "val" if bucket == 8 else "test"


# ---------------------------------------------------------------- reward

def status_score(status: str | None, attempt: int | None) -> float:
    s = str(status or "").lower()
    if s in FAILURE_STATUSES:
        return -1.0
    if s == "ok":
        return 1.0 / max(1, int(attempt or 1))
    return 0.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def node_reward(status: str | None, attempt: int | None, latency_ms: float | None, tokens_est: int | None) -> float:
    s = status_score(status, attempt)
    lat = float(latency_ms or 0.0)
    tok = int(tokens_est or 0)
    r_lat = _clip(1.0 - lat / 100.0, 0.0, 1.0)
    r_tok = 1.0 - min(math.log(1 + tok) / math.log(1 + 256), 1.0)
    return _clip(0.6 * s + 0.25 * r_lat + 0.15 * r_tok, -1.0, 1.0)


def agent_reward(status: str | None, attempt: int | None, duration_s: float | None, output_tokens: int | None) -> float:
    s = status_score(status, attempt)
    dur = float(duration_s or 0.0)
    tok = int(output_tokens or 0)
    r_lat = math.exp(-dur / 600.0)
    r_tok = 1.0 - min(math.log(1 + tok) / math.log(1 + 32768), 1.0)
    return _clip(0.6 * s + 0.25 * r_lat + 0.15 * r_tok, -1.0, 1.0)


# ---------------------------------------------------------------- record assembly

def base_features(goal_text: str) -> dict:
    return {
        "goal_text": goal_text,
        "n_words": n_words(goal_text),
        "n_chain_signals": n_chain_signals(goal_text),
        "has_code_terms": has_code_terms(goal_text),
        "latency_ms": None,
        "tokens_est": None,
        "attempt": None,
        "layer": None,
        "phase": None,
        "n_tool_calls": None,
        "duration_s": None,
        "output_tokens": None,
    }


def make_record(*, record_id: str, source: str, provenance_fields: dict, features: dict,
                label_tier: str, label_agents_n: int, reward: float,
                latency_ms: float | None, tokens_est: int | None,
                status: str, error_class: str | None, split_key: str) -> dict:
    assert label_tier in TIER_VOCAB, label_tier
    # Record-level provenance: 'measured' iff ALL reward inputs are measured.
    all_measured = all(provenance_fields[k] == "measured" for k in ("latency_ms", "tokens_est", "status"))
    bucket = split_bucket(split_key)
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "source": source,
        "provenance": "measured" if all_measured else "simulated",
        "provenance_fields": provenance_fields,
        "features": features,
        "label_tier": label_tier,
        "label_agents_n": int(label_agents_n),
        "reward": round(float(reward), 6),
        "latency_ms": latency_ms,
        "tokens_est": tokens_est,
        "status": status,
        "errorClass": error_class,
        "split_key": split_key,
        "split_bucket": bucket,
    }


# ---------------------------------------------------------------- source 1: ultra runs

def mine_ultra(ultra_dir: Path) -> tuple[list[dict], dict]:
    """Mine bundles/ultra/runs timelines. One record per timeline row."""
    if not ultra_dir.is_dir():
        return [], {"included": False, "reason": "ultra dir not found", "n_runs": 0, "n_records": 0}
    records: list[dict] = []
    n_runs = 0
    for run_dir in sorted(p for p in ultra_dir.iterdir() if p.is_dir()):
        timeline = run_dir / "timeline.jsonl"
        if not timeline.exists():
            continue
        n_runs += 1
        run_id = run_dir.name
        checkpoint: dict = {}
        cp_path = run_dir / "checkpoint.json"
        if cp_path.exists():
            try:
                checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                checkpoint = {}
        # langchain-run checkpoints carry goal_preview; list runs don't.
        goal_text = checkpoint.get("goal_preview") or ""
        intent = checkpoint.get("intent")
        if "-list-" in run_id or "-health-" in run_id:
            tier = "deterministic"
        else:
            tier = INTENT_TO_TIER.get(intent, "llm")
        agents_n = len(_routed_agents(intent, _complexity(goal_text or ""))) if intent else 1
        # Group near-duplicate re-runs (same run family, different timestamp
        # suffix) into one split group so no train/test leakage occurs.
        split_key = re.sub(r"-(\d{8}T\d{6}Z|\d{6})$", "", run_id)
        for idx, line in enumerate(timeline.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            # Rows carry BOTH spellings; mirror harness timeline.py:71-77.
            latency_ms = float(row.get("latency_ms", row.get("latency", 0)) or 0)
            tokens_est = int(row.get("tokens_est", row.get("tokens", 0)) or 0)
            status = str(row.get("status", ""))
            error_class = row.get("errorClass")
            attempt = row.get("attempt")
            node_id = row.get("nodeId")
            # Only the decide_act row's latency is wall-clock measured
            # (agents/cli.py:160-161,175); all other latencies and ALL token
            # counts are scripted constants -> simulated.
            lat_prov = "measured" if node_id == MEASURED_ULTRA_NODE else "simulated"
            provenance_fields = {
                "latency_ms": lat_prov,
                "tokens_est": "simulated",
                "status": "measured",
                "label_tier": "simulated",
            }
            features = base_features(goal_text)
            features.update({
                "latency_ms": latency_ms,
                "tokens_est": tokens_est,
                "attempt": attempt,
                "layer": row.get("layer"),
            })
            records.append(make_record(
                record_id=f"ultra_timeline-{run_id}-{idx:02d}",
                source="ultra_timeline",
                provenance_fields=provenance_fields,
                features=features,
                label_tier=tier,
                label_agents_n=agents_n,
                reward=node_reward(status, attempt, latency_ms, tokens_est),
                latency_ms=latency_ms,
                tokens_est=tokens_est,
                status=status,
                error_class=error_class,
                split_key=split_key,
            ))
    meta = {"included": True, "dir": _relpath(ultra_dir), "n_runs": n_runs, "n_records": len(records)}
    return records, meta


def _relpath(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(_REPO))
    except ValueError:
        return p.name


# ---------------------------------------------------------------- source 2: workflow journal

# Timestamp / usage extraction only. The tool-name histogram against the closed
# vocab is deliberately not stored (schema keys are pinned; n_tool_calls is the
# required aggregate).

def _parse_ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _phase_from_keys(keys: set) -> str:
    if {"conventions", "key_files"} <= keys:
        return "recon"
    if "proposals" in keys:
        return "proposals"
    if "build_now" in keys:
        return "spec"
    if "files_changed" in keys:
        return "build"
    if "all_green" in keys:
        return "validate"
    return "other"


def _transcript_aggregates(path: Path) -> dict:
    """Numeric-only aggregates from one agent transcript (defensive parse)."""
    timestamps: list[float] = []
    tool_calls = 0
    out_tokens = 0
    if path.exists():
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue  # torn line
                ts = _parse_ts(obj.get("timestamp"))
                if ts is not None:
                    timestamps.append(ts)
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    try:
                        out_tokens += int(usage.get("output_tokens") or 0)
                    except (TypeError, ValueError):
                        pass
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_calls += 1
    duration_s = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else 0.0
    return {"duration_s": round(duration_s, 3), "n_tool_calls": tool_calls, "output_tokens": out_tokens}


def mine_journal(journal_dir: Path | None) -> tuple[list[dict], dict]:
    """One record per workflow agent. ZERO-TEXT RULE: metadata only.

    Extracted per agent: opaque agentId, result KEY-SET (for the phase
    categorical), the all_green boolean, transcript timestamps and usage
    numbers, tool_use counts. Nothing else — no summaries, notes,
    fixups_applied text, file paths, message text, or model ids.
    """
    if journal_dir is None:
        return [], {"included": False, "reason": "journal dir not provided"}
    if not journal_dir.is_dir() or not (journal_dir / "journal.jsonl").exists():
        return [], {"included": False, "reason": "journal dir not found"}

    dirname = journal_dir.name  # directory BASENAME only — never the full path
    agent_ids: list[str] = []
    result_keys: dict[str, set] = {}
    all_green: dict[str, bool] = {}
    with (journal_dir / "journal.jsonl").open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            agent_id = obj.get("agentId")
            if not isinstance(agent_id, str) or not agent_id:
                continue
            if agent_id not in agent_ids:
                agent_ids.append(agent_id)
            if obj.get("type") == "result" and isinstance(obj.get("result"), dict):
                keys = set(obj["result"].keys())
                result_keys[agent_id] = keys
                if "all_green" in keys:
                    green = obj["result"].get("all_green")
                    all_green[agent_id] = bool(green) if isinstance(green, bool) else True

    phases = {aid: _phase_from_keys(result_keys.get(aid, set())) for aid in agent_ids}
    phase_counts: dict[str, int] = {}
    for phase in phases.values():
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

    records: list[dict] = []
    for agent_id in agent_ids:
        phase = phases[agent_id]
        agg = _transcript_aggregates(journal_dir / f"agent-{agent_id}.jsonl")
        status = "ok"
        error_class = None
        if phase == "validate" and all_green.get(agent_id) is False:
            # The corpus's one genuine measured negative label.
            status = "failed"
        tier = PHASE_TO_TIER.get(phase, "llm")
        provenance_fields = {
            "latency_ms": "measured",
            "tokens_est": "measured",
            "status": "measured",
            "label_tier": "simulated",
        }
        features = base_features("")  # MANDATORY "": no safe goal text exists
        features.update({
            "attempt": 1,
            "phase": phase,
            "n_tool_calls": agg["n_tool_calls"],
            "duration_s": agg["duration_s"],
            "output_tokens": agg["output_tokens"],
        })
        records.append(make_record(
            record_id=f"workflow_journal-{dirname}-{agent_id}",
            source="workflow_journal",
            provenance_fields=provenance_fields,
            features=features,
            label_tier=tier,
            label_agents_n=phase_counts[phase],
            reward=agent_reward(status, 1, agg["duration_s"], agg["output_tokens"]),
            latency_ms=None,
            tokens_est=None,
            status=status,
            error_class=error_class,
            split_key=f"{dirname}:{agent_id}",
        ))
    meta = {
        "included": True,
        "dirname": dirname,
        "n_records": len(records),
        "note": "metadata-only extraction; no prompt/result text",
    }
    return records, meta


# ---------------------------------------------------------------- source 3: synthetic battery

# Every template embeds at least one literal INTENT_KEYWORDS hit (harness
# cli.py:37-42) — zero-keyword goals would be unlabelable and crash the real
# route CLI. All 4 intent families and all 3 complexity bands are covered
# (simple <=18 words, medium >18, epic >60 words or >=3 chain signals).
SLOTS = {
    "artifact": ["dashboard", "ingest pipeline", "eval harness", "report generator",
                 "data refinery", "routing table", "corpus builder", "training loop"],
    "topic": ["quarterly revenue", "churn cohorts", "embedding quality", "release cadence",
              "vendor onboarding", "latency budgets", "billing anomalies", "signup funnels",
              "index freshness", "capacity planning"],
    "service": ["postgres", "redis", "the queue broker", "the object store", "the metrics stack"],
    "service2": ["sqlite", "memcached", "the log shipper", "the blob cache", "the tracing stack"],
    "team": ["the platform team", "the research pod", "the operations crew", "the data guild"],
    "system": ["staging", "production", "the canary fleet", "the batch cluster"],
}

TEMPLATES = [
    # -------- agentic_loop family (launch/ship/build/loop/factory/end-to-end)
    "launch the {artifact} for {topic}",
    "ship the {artifact} to {system} for {team}",
    "build a {artifact} that tracks {topic}",
    "close the loop on {topic} for {team}",
    "build and launch a {artifact} for {topic} in {system}",
    "keep the factory loop running for {topic}",
    "ship an end-to-end {artifact} for {topic}, wire it into {system}, and make sure {team} can rerun it on demand without manual steps every week",
    "build the {artifact} factory for {topic} so {team} can loop on results daily, then publish the numbers to {system} for review by everyone involved",
    "launch the full {artifact} program for {topic}: first collect requirements from {team}, then draft the plan, then implement it against {system}, then verify the results and close the loop with a retrospective",
    "ship it end-to-end: observe {topic} -> orient with {team} -> decide on the {artifact} -> act in {system}",
    "launch the complete {artifact} program for {topic} covering intake, triage, planning, implementation, verification, and rollout, keep {team} informed at every stage of the effort, track the budget against the agreed plan, document every decision in the shared log, rehearse the rollback path in {system} twice before the cutover date, confirm the named owners for each stage, and close the loop with a full retrospective once the final numbers for {topic} are published and reviewed by everyone",
    # -------- deep_research family (compare/vs/research/benchmark/sources)
    "compare {service} vs {service2} for {topic}",
    "research the state of {topic} for {team}",
    "benchmark the {artifact} on {topic}",
    "compare {service} vs {service2} on cost",
    "research which {artifact} benchmark best predicts {topic}",
    "benchmark {service} vs {service2} for {team}",
    "compare {service} vs {service2} for {topic} using at least five sources, grade each source for reliability, and summarize the contradictions for {team} before the end of the month",
    "research {topic} across published benchmark suites, triangulate the findings from independent sources, and write a short brief that {team} can act on next quarter",
    "run a benchmark: gather sources -> cluster the claims -> surface contradictions -> crystallize a recommendation on {topic}",
    "deep research pass on {topic}: compare the top approaches, then rank them, then check the sources, then deliver the matrix to {team}",
    "research {topic} in depth for {team}: compare every credible approach currently deployed in production anywhere, benchmark the top three candidates on identical hardware with identical workloads, collect at least seven independent sources with publication dates attached, grade each source for reliability and recency, build a contradiction matrix across the competing claims, note carefully where the evidence is thin or stale, and deliver a ranked recommendation with the raw benchmark tables attached for open review",
    # -------- complex_action family (gmail/calendar/invoice/schedule/book/pay)
    "schedule a calendar review of {topic} with {team}",
    "send the invoice for {topic}",
    "book a slot on the calendar for {team}",
    "schedule {team} standups on the calendar",
    "pay the invoice for {service} and file the receipt",
    "schedule the {artifact} maintenance window and notify {team} by gmail",
    "draft the invoice for {topic}, attach the summary, send it via gmail, and schedule a follow-up on the calendar for {team} next week",
    "schedule a quarterly calendar block for {topic}, send the agenda to {team} by gmail, collect the replies, and book the room in {system} before friday morning",
    "gmail triage: read the inbox -> label by {topic} -> schedule replies -> archive the rest",
    "handle the month-end billing run for {team}: pull every unpaid invoice from the ledger, reconcile each invoice against the original contract terms line by line, draft the reminder messages in gmail with the correct amounts, schedule the send times on the calendar across three time zones, book follow-up calls for the accounts that stay silent past the deadline, record every single action in the audit log as you go, and hand over a plain summary of {topic} when the calendar finally clears",
    # -------- deterministic family (heartbeat/monitor/cron/tick)
    "monitor the {artifact} heartbeat",
    "add a cron tick for {topic}",
    "monitor {system} for {topic}",
    "set up a heartbeat monitor on the {artifact}",
    "cron the {artifact} refresh every hour",
    "monitor {service} health with a cron tick",
    "monitor the heartbeat of {system}, log every tick, alert {team} when three ticks are missed in a row, and keep the cron cadence unchanged otherwise",
    "wire a cron heartbeat for the {artifact} in {system} so {team} sees a fresh tick every five minutes with no manual checks required at all",
    "tick check: read the cron log -> compare ticks -> flag gaps -> post the heartbeat summary for {system}",
    "keep {system} under continuous watch for {team}: run the heartbeat cron every minute without exception, record every tick with a full timestamp, monitor the gap between consecutive ticks for drift, page the on-call rotation when the monitor sees three missed ticks in a row, rotate the log files nightly to keep disk usage flat, verify the cron entries after every deploy to {system}, and post a weekly uptime summary so the whole heartbeat history stays auditable end to end",
    # -------- mixed extras
    "build the {artifact} and ship it to {system} for {team} to launch",
    "compare {service} vs {service2} and benchmark both against {topic} sources",
]

_SLOT_KEYS = sorted(SLOTS.keys())


def generate_battery(battery_n: int, seed: int) -> list[dict]:
    """Seeded synthetic goals labeled by the harness heuristic (pure functions)."""
    rng = random.Random(seed)
    seen: set[str] = set()
    records: list[dict] = []
    max_attempts = max(1000, battery_n * 50)
    attempts = 0
    while len(records) < battery_n and attempts < max_attempts:
        attempts += 1
        tpl_idx = rng.randrange(len(TEMPLATES))
        fills = {k: rng.choice(SLOTS[k]) for k in _SLOT_KEYS}
        goal = TEMPLATES[tpl_idx].format(**fills)
        if goal in seen:
            continue
        seen.add(goal)
        scores = {k: _score_intent(goal, k) for k in INTENT_KEYWORDS}
        intent = max(scores, key=lambda k: scores[k]) if max(scores.values()) > 0 else "llm"
        complexity = _complexity(goal)
        tier = _classify_moma(goal, intent, complexity)
        agents_n = len(_routed_agents(intent, complexity))
        provenance_fields = {
            "latency_ms": "simulated",
            "tokens_est": "simulated",
            "status": "simulated",
            "label_tier": "simulated",
        }
        records.append(make_record(
            record_id=f"battery-{hashlib.sha256(goal.encode()).hexdigest()[:12]}",
            source="synthetic_battery",
            provenance_fields=provenance_fields,
            features=base_features(goal),
            label_tier=tier,
            label_agents_n=agents_n,
            reward=1.0,  # label-match by construction; provenance simulated
            latency_ms=None,
            tokens_est=None,
            status="ok",
            error_class=None,
            # Group paraphrase-siblings by template so they never straddle train/test.
            split_key=f"tpl-{tpl_idx:03d}",
        ))
    return records


# ---------------------------------------------------------------- build / stats

def _count_records(records: list[dict]) -> dict:
    by_source: dict[str, int] = {}
    by_provenance: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_split = {"train": 0, "val": 0, "test": 0}
    for rec in records:
        by_source[rec["source"]] = by_source.get(rec["source"], 0) + 1
        by_provenance[rec["provenance"]] = by_provenance.get(rec["provenance"], 0) + 1
        by_tier[rec["label_tier"]] = by_tier.get(rec["label_tier"], 0) + 1
        by_split[split_name(rec["split_bucket"])] += 1
    return {
        "total": len(records),
        "by_source": by_source,
        "by_provenance": by_provenance,
        "by_tier": by_tier,
        "by_split": by_split,
    }


def build(out_dir: Path, ultra_dir: Path, journal_dir: Path | None, battery_n: int, seed: int) -> dict:
    ultra_records, ultra_meta = mine_ultra(ultra_dir)
    journal_records, journal_meta = mine_journal(journal_dir)
    battery_records = generate_battery(battery_n, seed)
    records = ultra_records + journal_records + battery_records

    record_ids = [r["record_id"] for r in records]
    assert len(record_ids) == len(set(record_ids)), "record_id collision"

    out_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = out_dir / "corpus.jsonl"
    with corpus_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=True) + "\n")

    meta = {
        "schema_version": SCHEMA_VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "generator": {
            "seed": seed,
            "battery_n": battery_n,
            "n_templates": len(TEMPLATES),
            "script": "apps/ava-factory/scripts/build_orchestration_corpus.py",
        },
        "tier_vocab": TIER_VOCAB,
        "dense_features": DENSE_FEATURES,
        "reward_config": REWARD_CONFIG,
        "counts": _count_records(records),
        "sources": {
            "ultra_timeline": ultra_meta,
            "workflow_journal": journal_meta,
            "synthetic_battery": {
                "included": True,
                "n_records": len(battery_records),
                "seed": seed,
                "n_templates": len(TEMPLATES),
                "note": "seeded template grammar; labels rule-derived from the harness heuristic; provenance simulated",
            },
        },
    }
    meta_path = out_dir / "corpus_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return meta


def stats(out_dir: Path) -> dict:
    corpus_path = out_dir / "corpus.jsonl"
    records = []
    with corpus_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    counts = _count_records(records)
    print(f"corpus: {corpus_path}")
    print(f"total: {counts['total']}")
    for section in ("by_provenance", "by_source", "by_tier", "by_split"):
        pairs = ", ".join(f"{k}={v}" for k, v in sorted(counts[section].items()))
        print(f"{section}: {pairs}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/inspect the orchestration corpus")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="mine sources + generate battery, write corpus files")
    p_build.add_argument("--out", type=Path, default=_AVA / "data" / "orchestration")
    p_build.add_argument("--ultra-dir", type=Path, default=_REPO / "bundles" / "ultra" / "runs")
    # No default: the journal lives outside the repo at a session-specific
    # path — when absent the source is skipped with an honest meta note.
    p_build.add_argument("--journal-dir", type=Path, default=None)
    p_build.add_argument("--battery-n", type=int, default=800)
    p_build.add_argument("--seed", type=int, default=20260809)

    p_stats = sub.add_parser("stats", help="print counts for an existing corpus")
    p_stats.add_argument("--out", type=Path, default=_AVA / "data" / "orchestration")

    args = parser.parse_args(argv)
    if args.cmd == "build":
        meta = build(args.out, args.ultra_dir, args.journal_dir, args.battery_n, args.seed)
        counts = meta["counts"]
        print(f"wrote {counts['total']} records to {args.out / 'corpus.jsonl'}")
        print(f"by_source: {counts['by_source']}")
        print(f"by_provenance: {counts['by_provenance']}")
        print(f"by_split: {counts['by_split']}")
    else:
        stats(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
