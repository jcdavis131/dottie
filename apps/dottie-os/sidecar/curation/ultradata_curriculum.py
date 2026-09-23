"""UltraData L0→L3 curriculum mappers for dottie-os System One factory.

HELPER only: consent.champion=false, public_hf=true.
Emits Choice/Score/Noul (+ L3 action/safe/severity), never chat SFT.
Gold heuristics documented in pack_v2 report.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

SCHEMA = "dottie-os-decision-schema-1.0.0"

CONSENT_HF = {"capture_training": True, "public_hf": True, "champion": False}

ACTION_CRITERIA = {
    "execute": "safe to run now",
    "escalate": "needs human confirm",
    "halt": "must not run",
    "other": "not a tool decision",
}

# HALT if shell/cmd matches destructive patterns
_HALT_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"rm\s+-rf",
        r"mkfs",
        r"dd\s+if=",
        r"curl\s+.*\|\s*.*bash",
        r"wget\s+.*\|\s*.*sh",
        r"DROP\s+TABLE",
        r"format\s+",
        r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",  # fork bomb
        r"sudo\s+rm",
    ]
]

_ESCALATE_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"\bsudo\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bkill\s+",
        r"git\s+push\s+--force",
        r"npm\s+publish",
        r"pip\s+install",
    ]
]

_ESCALATE_TOOL_PREFIXES = (
    "cancel_",
    "exchange_",
    "delete_",
    "update_",
    "book_",
    "create_",
    "send_",
    "transfer_",
    "refund_",
    "pay_",
    "write_",
    "remove_",
)

_EXECUTE_TOOLS = {
    "read_file",
    "find",
    "ls",
    "cat",
    "rg",
    "head",
    "calculate",
    "list",
    "get_file",
    "search",
}

_DECONTAM = re.compile(
    r"(arxiviq|openjev|jevbench|nanojev|typesafe\s+teacher|jev-v0\s+champion)",
    re.I,
)

_CODE_DOMAIN_MAP = {
    "tool": "tool",
    "tools": "tool",
    "web": "web",
    "algo": "algo",
    "algorithm": "algo",
    "math": "math",
    "data": "data",
    "ml": "ml",
    "system": "system",
    "cli": "tool",
    "script": "tool",
    "other": "other",
}

_CODE_DOMAIN_CRITERIA = {
    "tool": "CLI / scripting / automation helpers",
    "web": "HTTP, HTML, browsers, frontend",
    "algo": "Algorithms and data structures",
    "math": "Numeric / scientific code",
    "data": "ETL, SQL, data pipelines",
    "ml": "ML / model training code",
    "system": "OS, processes, infra",
    "other": "Uncategorized code domain",
}

_DESTRUCTIVE_CODE = re.compile(
    r"(rm\s+-rf|mkfs|DROP\s+TABLE|os\.system\(|subprocess\.|eval\(|exec\(|pickle\.loads)",
    re.I,
)


def leaks_decontam(text: str) -> bool:
    return bool(_DECONTAM.search(text or ""))


def _trunc(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _args_summary(arguments: Any, limit: int = 240) -> str:
    if arguments is None:
        return ""
    if isinstance(arguments, (dict, list)):
        try:
            return _trunc(json.dumps(arguments, ensure_ascii=False, sort_keys=True), limit)
        except Exception:
            return _trunc(str(arguments), limit)
    if isinstance(arguments, str):
        # may be JSON string
        try:
            parsed = json.loads(arguments)
            return _args_summary(parsed, limit)
        except Exception:
            return _trunc(arguments, limit)
    return _trunc(str(arguments), limit)


def first_tool_call(messages: Any) -> Optional[tuple[str, Any]]:
    """Return (name, arguments) from first assistant tool_call in messages."""
    if not isinstance(messages, list):
        return None
    for m in messages:
        if not isinstance(m, dict):
            continue
        tcs = m.get("tool_calls")
        if not tcs:
            continue
        tc = tcs[0] if isinstance(tcs, list) else tcs
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
        name = (fn or {}).get("name")
        if not name:
            continue
        return str(name), (fn or {}).get("arguments")
    return None


def classify_tool_action(name: str, arguments: Any) -> str:
    """L3 gold heuristic: halt | escalate | execute (never other here — caller skips)."""
    name_l = (name or "").strip().lower()
    detail = _args_summary(arguments, 800)
    blob = f"{name_l} {detail}"

    for pat in _HALT_PATTERNS:
        if pat.search(blob):
            return "halt"

    if any(name_l.startswith(p) for p in _ESCALATE_TOOL_PREFIXES):
        return "escalate"
    for pat in _ESCALATE_PATTERNS:
        if pat.search(blob):
            return "escalate"

    # read-ish
    if (
        name_l in _EXECUTE_TOOLS
        or name_l.startswith("get_")
        or name_l.startswith("find_")
        or name_l.startswith("list_")
        or name_l.startswith("search_")
        or name_l.startswith("read_")
        or name_l in {"sg", "grep", "rg", "glob", "semantic_search"}
    ):
        return "execute"
    if name_l in {"shell", "bash", "cmd", "run_terminal_cmd", "run"}:
        # non-destructive shell → execute; unclear → escalate
        if any(tok in detail.lower() for tok in ("rm ", "del ", "format", "mkfs", "dd ", "chmod", "chown", "kill ", "sudo")):
            return "escalate"
        return "execute"

    # write-ish unknown → escalate
    if any(x in name_l for x in ("write", "delete", "remove", "update", "create", "send", "post", "put")):
        return "escalate"

    # risk unclear
    return "escalate"


def l3_multihead_labels(action: str) -> dict[str, Any]:
    """safe noul + severity score (0–1) from action band."""
    if action == "halt":
        safe, sev = 0.05, 0.90
    elif action == "escalate":
        safe, sev = 0.35, 0.55
    elif action == "execute":
        safe, sev = 0.85, 0.20
    else:
        safe, sev = 0.50, 0.50
    return {
        "action": {"type": "choice", "choice": action},
        "safe": {"type": "noul", "noul": float(safe)},
        "severity": {"type": "score", "score": float(sev)},
    }


def l3_questions() -> dict[str, Any]:
    return {
        "action": {
            "type": "choice",
            "instructions": "What should the pair-programmer do?",
            "criteria": dict(ACTION_CRITERIA),
        },
        "safe": {
            "type": "noul",
            "instructions": "P(safe to execute)",
        },
        "severity": {
            "type": "score",
            "instructions": "Risk severity 0-1",
            "criteria": ["negligible", "critical"],
        },
    }


def make_row(
    *,
    rid: str,
    tier: str,
    source: dict[str, Any],
    state: dict[str, Any],
    questions: dict[str, Any],
    labels: dict[str, Any],
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "id": rid,
        "tier": tier,
        "source": source,
        "state": state,
        "questions": questions,
        "labels": labels,
        "consent": dict(CONSENT_HF),
    }
    if extra:
        row.update(extra)
    return row


def _stream_take(ds: Iterable[Any], n: int) -> Iterator[Any]:
    for i, row in enumerate(ds):
        if i >= n:
            break
        yield row


def curate_ultradata_agent(
    n: int = 400,
    *,
    configs: tuple[str, ...] = ("Code-Agent", "Tool-Use"),
    seed: int = 20260921,
) -> list[dict[str, Any]]:
    """P1: UltraData-SFT-Agent-2609 → L3 multi-head tool-gate rows.

    Soft action mix target (~40% execute / ~40% escalate / ~20% halt) by
    continuing to stream until quotas fill or scan budget exhausted.
    Never invents tool rows — only real mined tool_calls.
    """
    from datasets import load_dataset

    rng = random.Random(seed)
    scan_budget = max(n * 20, 4000)
    quotas = {
        "execute": max(1, int(n * 0.40)),
        "escalate": max(1, int(n * 0.40)),
        "halt": max(1, n - int(n * 0.40) - int(n * 0.40)),
    }
    buckets: dict[str, list[dict[str, Any]]] = {"execute": [], "escalate": [], "halt": []}
    seen: set[str] = set()

    for cfg in configs:
        ds = load_dataset(
            "openbmb/UltraData-SFT-Agent-2609",
            cfg,
            split="train",
            streaming=True,
        )
        for idx, raw in enumerate(_stream_take(ds, scan_budget)):
            if all(len(buckets[a]) >= quotas[a] for a in quotas):
                break
            uuid = str(raw.get("uuid") or f"{cfg}-{idx}")
            if uuid in seen:
                continue
            tc = first_tool_call(raw.get("messages"))
            if not tc:
                continue
            name, arguments = tc
            action = classify_tool_action(name, arguments)
            if action not in buckets:
                continue
            if len(buckets[action]) >= quotas[action]:
                continue
            detail = _args_summary(arguments)
            message = f"tool={name}; detail={detail}"
            blob = message + json.dumps(raw.get("domain") or "") + str(raw.get("source") or "")
            if leaks_decontam(blob):
                continue
            rid = f"ultradata-agent-{hashlib.sha1(uuid.encode()).hexdigest()[:10]}"
            if rid in seen:
                continue
            seen.add(uuid)
            seen.add(rid)
            buckets[action].append(
                make_row(
                    rid=rid,
                    tier="L3",
                    source={
                        "hf": "openbmb/UltraData-SFT-Agent-2609",
                        "config": cfg,
                        "split": "train",
                        "uuid": uuid,
                        "domain": raw.get("domain"),
                        "row": idx,
                    },
                    state={
                        "message": message,
                        "meta": {
                            "tool": name,
                            "risk_hint": action,
                            "agent_config": cfg,
                        },
                    },
                    questions=l3_questions(),
                    labels=l3_multihead_labels(action),
                )
            )

    out: list[dict[str, Any]] = []
    for a in ("execute", "escalate", "halt"):
        out.extend(buckets[a])
    # If quotas underfilled (rare halt in stream), top up from surplus execute/escalate
    if len(out) < n:
        surplus: list[dict[str, Any]] = []
        # second pass fill any remaining slots without inventing
        for cfg in configs:
            if len(out) + len(surplus) >= n:
                break
            ds = load_dataset(
                "openbmb/UltraData-SFT-Agent-2609",
                cfg,
                split="train",
                streaming=True,
            )
            for idx, raw in enumerate(_stream_take(ds, scan_budget)):
                if len(out) + len(surplus) >= n:
                    break
                uuid = str(raw.get("uuid") or f"{cfg}-fill-{idx}")
                if uuid in seen:
                    continue
                tc = first_tool_call(raw.get("messages"))
                if not tc:
                    continue
                name, arguments = tc
                action = classify_tool_action(name, arguments)
                detail = _args_summary(arguments)
                message = f"tool={name}; detail={detail}"
                if leaks_decontam(message):
                    continue
                rid = f"ultradata-agent-{hashlib.sha1(uuid.encode()).hexdigest()[:10]}"
                if rid in seen:
                    continue
                seen.add(uuid)
                seen.add(rid)
                surplus.append(
                    make_row(
                        rid=rid,
                        tier="L3",
                        source={
                            "hf": "openbmb/UltraData-SFT-Agent-2609",
                            "config": cfg,
                            "split": "train",
                            "uuid": uuid,
                            "domain": raw.get("domain"),
                            "row": idx,
                        },
                        state={
                            "message": message,
                            "meta": {"tool": name, "risk_hint": action, "agent_config": cfg},
                        },
                        questions=l3_questions(),
                        labels=l3_multihead_labels(action),
                    )
                )
        out.extend(surplus[: max(0, n - len(out))])

    rng.shuffle(out)
    return out[:n]


def _map_code_domain(category: Any) -> str:
    c = str(category or "other").strip().lower()
    for key, val in _CODE_DOMAIN_MAP.items():
        if key in c:
            return val
    return "other"


def _code_risk_noul(content: str) -> float:
    if _DESTRUCTIVE_CODE.search(content or ""):
        return 0.15
    if re.search(r"(password|secret|api[_-]?key|token\s*=)", content or "", re.I):
        return 0.30
    return 0.75


def curate_ultradata_code(
    n: int = 300,
    *,
    splits: tuple[str, ...] = ("py", "js", "sh"),
    seed: int = 20260921,
) -> list[dict[str, Any]]:
    """P2: UltraData-Code L2 → Choice(domain)+Score(quality)+Noul(risk)."""
    from datasets import load_dataset

    rng = random.Random(seed + 1)
    per = max(1, n // len(splits))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    questions = {
        "domain": {
            "type": "choice",
            "instructions": "Which code domain is this snippet?",
            "criteria": dict(_CODE_DOMAIN_CRITERIA),
        },
        "quality": {
            "type": "score",
            "instructions": "Snippet quality 0-1 (normalized)",
            "criteria": ["low", "high"],
        },
        "safe": {
            "type": "noul",
            "instructions": "P(safe / non-destructive snippet)",
        },
    }

    for sp in splits:
        need = per if sp != splits[-1] else (n - len(out))
        if need <= 0:
            break
        try:
            ds = load_dataset(
                "openbmb/UltraData-Code",
                "UltraData-Code-L2",
                split=sp,
                streaming=True,
            )
        except Exception:
            continue
        got = 0
        for idx, raw in enumerate(_stream_take(ds, max(need * 3, 500))):
            if got >= need:
                break
            uuid = str(raw.get("uuid") or f"{sp}-{idx}")
            if uuid in seen:
                continue
            content = str(raw.get("content") or "")
            if not content.strip():
                continue
            path = str(raw.get("relative_path") or "")
            msg = _trunc(content, 1200)
            if path:
                msg = f"path={path}\n{msg}"
            if leaks_decontam(msg):
                continue
            q = raw.get("quality_score")
            try:
                qf = float(q)
            except (TypeError, ValueError):
                qf = 0.5
            # quality often ~1–5; normalize roughly to 0–1
            if qf > 1.5:
                qf = max(0.0, min(1.0, qf / 5.0))
            else:
                qf = max(0.0, min(1.0, qf))
            domain = _map_code_domain(raw.get("category"))
            rid = f"ultradata-code-{hashlib.sha1(uuid.encode()).hexdigest()[:10]}"
            seen.add(uuid)
            row = make_row(
                rid=rid,
                tier="L2",
                source={
                    "hf": "openbmb/UltraData-Code",
                    "config": "UltraData-Code-L2",
                    "split": sp,
                    "uuid": uuid,
                    "repo_name": raw.get("repo_name"),
                    "row": idx,
                },
                state={
                    "message": msg,
                    "meta": {
                        "category": raw.get("category"),
                        "algo_rel_score": raw.get("algo_rel_score"),
                        "lang": sp,
                    },
                },
                questions=questions,
                labels={
                    "domain": {"type": "choice", "choice": domain},
                    "quality": {"type": "score", "score": float(qf)},
                    "safe": {"type": "noul", "noul": float(_code_risk_noul(content))},
                },
            )
            out.append(row)
            got += 1

    rng.shuffle(out)
    return out[:n]


def _math_difficulty(content: str) -> float:
    text = content or ""
    length = len(text)
    symbols = len(re.findall(r"[\\^_{}=∫∑√∞≤≥≠±×÷]|\\\\frac|\\\\sum|\\\\int", text))
    dens = symbols / max(1, length / 40.0)
    # length component
    len_s = min(1.0, length / 2500.0)
    return max(0.05, min(0.98, 0.35 * len_s + 0.65 * min(1.0, dens / 8.0)))


def _math_solvability(content: str) -> float:
    t = (content or "").lower()
    if "?" in t or re.search(r"\b(prove|find|compute|solve|evaluate|show that)\b", t):
        return 0.72
    if re.search(r"\b(theorem|lemma|corollary)\b", t):
        return 0.55
    return 0.45


def curate_ultradata_math(
    n: int = 200,
    *,
    seed: int = 20260921,
) -> list[dict[str, Any]]:
    """P3: UltraData-Math-L1 problem text → Score(difficulty)+Noul(solvability). No solution SFT."""
    from datasets import load_dataset

    rng = random.Random(seed + 2)
    ds = load_dataset(
        "openbmb/UltraData-Math",
        "UltraData-Math-L1",
        split="train",
        streaming=True,
    )
    questions = {
        "difficulty": {
            "type": "score",
            "instructions": "Problem difficulty 0-1 (length/symbol heuristic)",
            "criteria": ["easy", "hard"],
        },
        "solvable": {
            "type": "noul",
            "instructions": "P(looks like a solvable question)",
        },
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(_stream_take(ds, max(n * 4, 800))):
        if len(out) >= n:
            break
        content = str(raw.get("content") or "").strip()
        if len(content) < 40:
            continue
        # drop huge dumps
        content = _trunc(content, 1600)
        if leaks_decontam(content):
            continue
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        rid_src = str(meta.get("record_id") or meta.get("url") or idx)
        if rid_src in seen:
            continue
        seen.add(rid_src)
        rid = f"ultradata-math-{hashlib.sha1(rid_src.encode()).hexdigest()[:10]}"
        out.append(
            make_row(
                rid=rid,
                tier="L2",
                source={
                    "hf": "openbmb/UltraData-Math",
                    "config": "UltraData-Math-L1",
                    "split": "train",
                    "row": idx,
                    "record_id": meta.get("record_id"),
                },
                state={"message": content, "meta": {"kind": "math_problem"}},
                questions=questions,
                labels={
                    "difficulty": {"type": "score", "score": float(_math_difficulty(content))},
                    "solvable": {"type": "noul", "noul": float(_math_solvability(content))},
                },
            )
        )
    rng.shuffle(out)
    return out[:n]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_tier_consent(row: dict[str, Any], default_tier: str = "L0") -> dict[str, Any]:
    out = dict(row)
    out.setdefault("tier", default_tier)
    consent = dict(out.get("consent") or {})
    consent.setdefault("capture_training", True)
    consent.setdefault("public_hf", True)
    # existing v1 public HF must stay champion false
    if consent.get("champion") is None:
        consent["champion"] = False
    # UltraData / public always false
    src = str((out.get("source") or {}).get("hf") or out.get("source") or "")
    if "ultradata" in src.lower() or "openbmb" in src.lower() or consent.get("public_hf"):
        consent["champion"] = False
    out["consent"] = consent
    if out.get("schema") in (None, "", "jev-decision-schema-1.0.0"):
        # do not rewrite jev nickname into bare form; keep dottie-os id
        out["schema"] = SCHEMA
    # normalize gold→labels if any legacy
    if "labels" not in out and "gold" in out and isinstance(out["gold"], dict):
        labels = {}
        qs = out.get("questions") or {}
        for k, v in out["gold"].items():
            if not isinstance(v, dict):
                continue
            qtype = (qs.get(k) or {}).get("type")
            lab = {"type": qtype} if qtype else {}
            lab.update(v)
            if "type" not in lab:
                if "choice" in v:
                    lab["type"] = "choice"
                elif "score" in v:
                    lab["type"] = "score"
                elif "noul" in v:
                    lab["type"] = "noul"
            labels[k] = lab
        out["labels"] = labels
    return out


def holdout_split(
    rows: list[dict[str, Any]],
    *,
    seed: int = 20260921,
    frac: float = 0.20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Hold ≥frac forever; keep nimble pairs intact via pair_id fields."""
    rng = random.Random(seed)

    def gkey(obj: dict[str, Any], idx: int) -> str:
        for k in ("pair_id", "nimble_pair_id", "pairId", "contrastive_pair_id"):
            v = obj.get(k)
            if v is not None and str(v) != "":
                return f"pair:{v}"
        meta = obj.get("meta") or obj.get("metadata") or {}
        if isinstance(meta, dict):
            for k in ("pair_id", "nimble_pair_id", "pairId"):
                v = meta.get(k)
                if v is not None and str(v) != "":
                    return f"pair:{v}"
        rid = obj.get("id")
        if rid is not None:
            return f"id:{rid}"
        return f"row:{idx}"

    groups: dict[str, list[int]] = {}
    for i, obj in enumerate(rows):
        groups.setdefault(gkey(obj, i), []).append(i)
    keys = list(groups.keys())
    rng.shuffle(keys)
    n = len(rows)
    target = max(1, int(math.ceil(n * frac)))
    hold_keys: list[str] = []
    hold_n = 0
    for k in keys:
        if hold_n >= target:
            break
        hold_keys.append(k)
        hold_n += len(groups[k])
    i = 0
    while n and hold_n / n < frac and i < len(keys):
        k = keys[i]
        i += 1
        if k in hold_keys:
            continue
        hold_keys.append(k)
        hold_n += len(groups[k])
    hold_set = set(hold_keys)
    train, hold = [], []
    for idx, obj in enumerate(rows):
        (hold if gkey(obj, idx) in hold_set else train).append(obj)
    return train, hold


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tiers = Counter(str(r.get("tier") or "?") for r in rows)
    sources = Counter()
    for r in rows:
        src = r.get("source")
        if isinstance(src, dict):
            sources[str(src.get("hf") or src.get("name") or "unknown")] += 1
        else:
            sources[str(src or "unknown")] += 1
    multi = 0
    action_labels = Counter()
    nimble_pairs = 0
    pair_ids = set()
    for r in rows:
        qs = r.get("questions") or {}
        if len(qs) >= 3:
            multi += 1
        labs = r.get("labels") or {}
        if "action" in labs and isinstance(labs["action"], dict):
            action_labels[str(labs["action"].get("choice"))] += 1
        for k in ("pair_id", "nimble_pair_id"):
            if r.get(k):
                pair_ids.add(str(r.get(k)))
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        if meta.get("pair_id") or meta.get("nimble_pair_id"):
            pair_ids.add(str(meta.get("pair_id") or meta.get("nimble_pair_id")))
    nimble_pairs = len(pair_ids)
    champ = sum(1 for r in rows if (r.get("consent") or {}).get("champion") is True)
    return {
        "total": len(rows),
        "by_tier": dict(tiers),
        "by_source": dict(sources),
        "multi_head_ge3_questions": multi,
        "multi_head_pct": (multi / len(rows)) if rows else 0.0,
        "l3_action_labels": dict(action_labels),
        "nimble_pair_ids": nimble_pairs,
        "champion_true_count": champ,
        "schema": SCHEMA,
    }


GOLD_HEURISTICS_DOC = {
    "L3_agent": {
        "state": "tool=<name>; detail=<args summary truncated>",
        "halt": "rm -rf, mkfs, dd if=, curl|bash, wget|sh, DROP TABLE, format, fork bomb, sudo rm",
        "escalate": "sudo/chmod/chown/kill, git push --force, npm publish, pip install, cancel_/exchange_/delete_/update_ (+ write APIs), unclear risk",
        "execute": "read_file, find, ls, cat, rg, head, get_*, find_*, calculate, list_*, non-destructive shell",
        "skip": "rows with no tool_call in scanned messages",
        "safe_noul": {"halt": 0.05, "escalate": 0.35, "execute": 0.85},
        "severity_0_1": {"halt": 0.90, "escalate": 0.55, "execute": 0.20},
        "consent": "champion=false, public_hf=true",
    },
    "L2_code": {
        "state": "truncated content ≤1200 + path hint",
        "choice": "domain from category mapped to tool/web/algo/math/data/ml/system/other",
        "score": "quality_score normalized to 0-1",
        "noul": "destructive tokens → low safe",
    },
    "L2_math": {
        "state": "cleaned problem text only (no solution SFT)",
        "score": "difficulty from length/symbol density 0-1",
        "noul": "mid-high if ?/prove/find else mid",
    },
}


def curate_pack_v2(
    staging_dir: Path,
    *,
    agent_n: int = 400,
    code_n: int = 300,
    math_n: int = 200,
    seed: int = 20260921,
    rebuild_v1_components: bool = False,
    curate_all_fn=None,
) -> dict[str, Any]:
    """Assemble curated_pack_v2 + holdout + train under staging_dir."""
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # P0: existing v1
    v1_path = staging_dir / "curated_pack_v1.jsonl"
    v1_rows = load_jsonl(v1_path)
    if not v1_rows and rebuild_v1_components and callable(curate_all_fn):
        curate_all_fn()
        v1_rows = load_jsonl(v1_path)
    # also try component files
    if not v1_rows:
        for name in (
            "curated_ag_news.jsonl",
            "curated_emotion.jsonl",
            "curated_sst2.jsonl",
            "curated_imdb.jsonl",
            "curated_nimble.jsonl",
        ):
            v1_rows.extend(load_jsonl(staging_dir / name))

    v1_rows = [ensure_tier_consent(r, "L0" if "ag_news" in str(r.get("source")) or "emotion" in str(r.get("source")) else "L1") for r in v1_rows]
    # refine L0/L1 from source names
    refined = []
    for r in v1_rows:
        src = str((r.get("source") or {}).get("hf") or r.get("source") or "").lower()
        if any(x in src for x in ("ag_news", "ag-news", "emotion")):
            r["tier"] = "L0"
        elif any(x in src for x in ("sst", "imdb", "toxicity")):
            r["tier"] = "L1"
        elif r.get("pair_id") or r.get("nimble_pair_id"):
            r.setdefault("tier", "L1")
        refined.append(r)
    v1_rows = refined

    agent_rows = curate_ultradata_agent(agent_n, seed=seed)
    code_rows = curate_ultradata_code(code_n, seed=seed)
    math_rows = curate_ultradata_math(math_n, seed=seed)

    pack = []
    pack.extend(v1_rows)
    pack.extend(agent_rows)
    pack.extend(code_rows)
    pack.extend(math_rows)

    # final decontam pass
    clean = []
    dropped = 0
    for r in pack:
        blob = json.dumps(r, ensure_ascii=False)
        if leaks_decontam(blob):
            dropped += 1
            continue
        # force UltraData champion false
        src = str((r.get("source") or {}).get("hf") or "")
        if "UltraData" in src or "openbmb" in src:
            cons = dict(r.get("consent") or {})
            cons["champion"] = False
            cons["public_hf"] = True
            cons.setdefault("capture_training", True)
            r["consent"] = cons
            r["schema"] = SCHEMA
        clean.append(ensure_tier_consent(r))
    pack = clean

    # Optional existing nimble flips only — never invent new synthetic generators
    # (caller may have already included nimble pairs in v1)

    full_path = staging_dir / "curated_pack_v2.jsonl"
    train_path = staging_dir / "curated_pack_v2_train.jsonl"
    hold_path = staging_dir / "curated_pack_v2_holdout.jsonl"
    report_path = staging_dir / "curated_pack_v2_summary.json"

    write_jsonl(full_path, pack)
    train, hold = holdout_split(pack, seed=seed, frac=0.20)
    write_jsonl(train_path, train)
    write_jsonl(hold_path, hold)

    summary = {
        "paths": {
            "pack": str(full_path),
            "train": str(train_path),
            "holdout": str(hold_path),
            "report": str(report_path),
        },
        "counts": summarize(pack),
        "train_counts": summarize(train),
        "holdout_counts": summarize(hold),
        "holdout_frac": (len(hold) / len(pack)) if pack else 0.0,
        "caps": {"agent": agent_n, "code": code_n, "math": math_n, "v1_carried": len(v1_rows)},
        "decontam_dropped": dropped,
        "gold_heuristics": GOLD_HEURISTICS_DOC,
        "notes": [
            "HELPER UltraData only; champion/LIVE untouched; no FT",
            "Nimble: only existing mined flips from v1; no new synthetic twin generators",
            "SCHEMA=dottie-os-decision-schema-1.0.0",
        ],
        "seed": seed,
    }
    report_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
