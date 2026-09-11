"""Skill lifecycle (spec §13): package contract, lifecycle gates, benchmark
dimensions and progressive disclosure.

A skill moves ``draft → validated → benchmarked → shadow → canary → active →
deprecated`` only on the evidence each stage requires, and every stage names its
rollback. Fixtures may test mechanics but cannot establish production
usefulness: benchmark evidence marked ``mock``/``synthetic`` does not count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dottie_loop.errors import InvalidInputError, PolicyDeniedError, UnexecutableError
from dottie_loop.hashing import now_iso

STAGES = ("draft", "validated", "benchmarked", "shadow", "canary", "active", "deprecated")
ROLLBACK: dict[str, str] = {
    "draft": "delete draft",
    "validated": "revert package change",
    "benchmarked": "disable candidate version",
    "shadow": "stop shadow",
    "canary": "pin incumbent",
    "active": "registry version rollback",
    "deprecated": "temporary re-enable with approval",
}
#: evidence keys each stage requires (all must be truthy)
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "draft": ("unique_id", "clear_triggers", "output_schema", "declared_dependencies_and_scopes"),
    "validated": ("frontmatter_schema", "import_ok", "deterministic_fixtures", "negative_cases"),
    "benchmarked": ("real_input_task_slice", "latency", "failures", "resource_cost", "no_mock_claim"),
    "shadow": ("runs_without_effects", "route_and_output_compared_to_incumbent"),
    "canary": ("limited_approved_traffic", "live_monitor", "rollback_threshold"),
    "active": ("versioned_release", "owner", "runbook", "slo", "provenance"),
    "deprecated": ("replacement_or_rationale", "migration_window", "no_new_routes"),
}
BENCHMARK_DIMENSIONS = ("task_success", "verifier_score", "unsupported_claim_rate", "tool_call_precision", "permission_denial_correctness", "latency", "token_consumption", "recovery_success", "regression_count", "user_correction_rate")
REQUIRED_FRONTMATTER = ("name", "description", "triggers", "dependencies", "connectors", "provider")


# --- SKILL.md frontmatter (a small YAML subset: scalars, flow lists, block lists) -------------


def parse_frontmatter(text: str) -> dict[str, Any]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        raise InvalidInputError("SKILL.md has no frontmatter block", field="frontmatter")
    out: dict[str, Any] = {}
    current: str | None = None
    for raw in m.group(1).splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(("- ", "-\t")) or line.lstrip().startswith("- "):
            if current is None or not isinstance(out.get(current), list):
                raise InvalidInputError("block list item without a list key", field="frontmatter")
            out[current].append(_scalar(line.strip()[2:]))
            continue
        if ":" not in line:
            raise InvalidInputError(f"unparseable frontmatter line {line!r}", field="frontmatter")
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "":
            out[key] = []
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            out[key] = [_scalar(x.strip()) for x in inner.split(",")] if inner else []
        else:
            out[key] = _scalar(val)
        current = key
    return out


def _scalar(v: str) -> Any:
    v = v.split(" #", 1)[0].strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v) if re.fullmatch(r"-?\d+\.\d+", v) else v
    except ValueError:
        return v


def validate_package(frontmatter: dict[str, Any], *, has_describe: bool, has_run: bool) -> dict[str, Any]:
    missing = [k for k in REQUIRED_FRONTMATTER if k not in frontmatter]
    if missing:
        raise InvalidInputError(f"frontmatter missing {missing}", field="frontmatter")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(frontmatter["name"])):
        raise InvalidInputError("skill name must be a kebab-case id", field="name")
    if not isinstance(frontmatter["triggers"], list) or not frontmatter["triggers"]:
        raise InvalidInputError("triggers must be a non-empty list", field="triggers")
    if not has_describe or not has_run:
        raise InvalidInputError("implementation must expose describe() and run()", field="module")
    return {"name": frontmatter["name"], "description": frontmatter["description"], "triggers": list(frontmatter["triggers"]), "dependencies": list(frontmatter.get("dependencies") or []), "connectors": list(frontmatter.get("connectors") or []), "provider": frontmatter.get("provider", "none"), "target": frontmatter.get("j_space_target"), "capabilities": frontmatter.get("capabilities") or {}, "version": str(frontmatter.get("version", "0.0.0"))}


# --- lifecycle --------------------------------------------------------------------------------------


@dataclass
class SkillRecord:
    package: dict[str, Any]
    stage: str = "draft"
    history: list[dict[str, Any]] = field(default_factory=list)
    instructions: str = ""
    references: dict[str, str] = field(default_factory=dict)

    def advance(self, to: str, evidence: dict[str, Any]) -> dict[str, Any]:
        if to not in STAGES:
            raise InvalidInputError(f"unknown stage {to!r}", field="stage")
        cur = STAGES.index(self.stage)
        if STAGES.index(to) != cur + 1:
            raise UnexecutableError(f"skill lifecycle moves one stage at a time ({self.stage} -> {to} refused)", "stage")
        missing = [k for k in REQUIRED_EVIDENCE[to] if not evidence.get(k)]
        if missing:
            raise UnexecutableError(f"stage {to} requires evidence {missing}", field="evidence")
        if to == "benchmarked" and (evidence.get("mock") or evidence.get("synthetic")):
            raise PolicyDeniedError("fixtures cannot establish production usefulness; benchmark on consented or public real data", "evidence")
        if to == "canary" and not evidence.get("approval_id"):
            raise PolicyDeniedError("canary traffic requires an approval id", field="approval_id")
        entry = {"from": self.stage, "to": to, "evidence": sorted(evidence), "rollback": ROLLBACK[to], "at": now_iso()}
        self.history.append(entry)
        self.stage = to
        return entry

    def rollback(self, reason: str) -> dict[str, Any]:
        action = ROLLBACK[self.stage]
        prev = self.history[-1]["from"] if self.history else "draft"
        entry = {"from": self.stage, "to": prev, "rollback": action, "reason": reason, "at": now_iso()}
        self.history.append(entry)
        self.stage = prev
        return entry

    # progressive disclosure (§13)
    def disclose(self, level: str) -> dict[str, Any]:
        """router sees name+description; instructions only after selection; references on demand."""
        if level == "router":
            return {"name": self.package["name"], "description": self.package["description"]}
        if level == "selected":
            return {"name": self.package["name"], "description": self.package["description"], "instructions": self.instructions, "triggers": self.package["triggers"]}
        if level == "workflow":
            return {"name": self.package["name"], "instructions": self.instructions, "references": dict(self.references)}
        raise InvalidInputError("level must be router|selected|workflow", field="level")


def benchmark_report(measurements: dict[str, float], *, real_data: bool, source: str) -> dict[str, Any]:
    missing = [d for d in BENCHMARK_DIMENSIONS if d not in measurements]
    return {"dimensions": dict(measurements), "missing": missing, "complete": not missing, "real_data": real_data, "source": source, "no_mock_claim": real_data, "capability_claim": "measured" if real_data and not missing else "none", "at": now_iso()}
