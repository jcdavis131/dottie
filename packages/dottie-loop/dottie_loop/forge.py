"""Forge: GPU jobs cross machines through a verifiable conveyor (spec §27).

The queue is a directory tree that a private Git repository transports::

    forge/
      runners/<host>.json          capability + heartbeat records
      jobs/pending/<job_id>.json   validated JobSpecs
      jobs/claimed/<job_id>.json   claimed atomically (rename) with runner identity
      jobs/done/<job_id>.json      terminal state
      results/<job_id>/result.json + log.txt

Nothing here opens a port or runs a shell: ``argv`` executes as an argument array
against an immutable ref; inputs are hash-verified before execution; outputs are
hashed after. The runner refuses a job it cannot satisfy BEFORE clone/execute and
writes a mismatch result (§29 "Runner claims incompatible GPU job").
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dottie_loop.errors import BlockedError, InvalidInputError, PolicyDeniedError
from dottie_loop.execution import canonical_in_root, run_argv
from dottie_loop.hashing import file_sha256, new_id, now_iso, parse_iso
from dottie_loop.schema import active

_METRIC_RE = re.compile(r"^FORGE_METRIC\s+([A-Za-z0-9_.:-]+)\s*=\s*([-+0-9.eE]+)\s*$")
_REF_RE = re.compile(r"^[0-9a-f]{7,40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
HEARTBEAT_ORPHAN_S = 600


@dataclass
class JobSpec:
    repo: str
    ref: str
    argv: list[str]
    cwd: str
    requirements: dict[str, Any]
    inputs: list[dict[str, str]]
    outputs: list[dict[str, Any]]
    timeout_seconds: int
    submitted_by: str
    job_id: str = field(default_factory=lambda: new_id("job_"))
    submitted_at: str = field(default_factory=now_iso)
    schema: str = field(default_factory=lambda: active("forge-job"))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def validate_job(spec: JobSpec, repo_allowlist: list[str]) -> None:
    if not _REPO_RE.match(spec.repo):
        raise InvalidInputError("repo must be owner/name", field="repo")
    if spec.repo not in repo_allowlist:
        raise PolicyDeniedError(f"repo {spec.repo} not in allowlist", field="repo")
    if not _REF_RE.match(spec.ref):
        raise InvalidInputError("ref must be an immutable commit sha", field="ref")
    if not spec.argv or not all(isinstance(a, str) and a for a in spec.argv):
        raise InvalidInputError("argv must be a non-empty list of strings", field="argv")
    if Path(spec.cwd).is_absolute() or ".." in Path(spec.cwd).parts:
        raise InvalidInputError("cwd must be a relative path without traversal", field="cwd")
    if spec.timeout_seconds <= 0:
        raise InvalidInputError("timeout_seconds must be positive", field="timeout_seconds")
    for inp in spec.inputs:
        if not inp.get("path") or not inp.get("sha256"):
            raise InvalidInputError("each input needs path and sha256", field="inputs")
    for out in spec.outputs:
        if not out.get("path"):
            raise InvalidInputError("each output needs a path", field="outputs")
    for k in ("cuda", "vram_gb", "torch"):
        if k not in spec.requirements:
            raise InvalidInputError(f"requirements.{k} is required", field="requirements")


@dataclass
class RunnerRecord:
    hostname: str
    gpu: str
    vram_gb: float
    cuda: str | None
    torch: str | None
    platform: str
    heartbeat_at: str = field(default_factory=now_iso)
    schema: str = field(default_factory=lambda: active("forge-runner"))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def satisfies(self, req: dict[str, Any]) -> tuple[bool, list[str]]:
        why: list[str] = []
        if req.get("cuda") and not self.cuda:
            why.append("cuda required, runner has none")
        if req.get("torch") and not self.torch:
            why.append("torch required, runner has none")
        if float(req.get("vram_gb", 0)) > self.vram_gb:
            why.append(f"vram {req.get('vram_gb')}GB > runner {self.vram_gb}GB")
        return not why, why


class ForgeQueue:
    def __init__(self, root: Path, repo_allowlist: list[str]) -> None:
        self.root = Path(root)
        self.repo_allowlist = list(repo_allowlist)
        for d in ("runners", "jobs/pending", "jobs/claimed", "jobs/done", "results"):
            (self.root / d).mkdir(parents=True, exist_ok=True)

    # -- runner protocol step 1 --
    def advertise(self, runner: RunnerRecord) -> Path:
        p = self.root / "runners" / f"{runner.hostname}.json"
        p.write_text(json.dumps(runner.to_dict(), indent=1, sort_keys=True), encoding="utf-8")
        return p

    def runners(self) -> list[RunnerRecord]:
        out = []
        for p in sorted((self.root / "runners").glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            d.pop("schema", None)
            out.append(RunnerRecord(**d))
        return out

    def registered_runner(self) -> RunnerRecord | None:
        """The blocker named by the spec: no runner registered == no GPU loop."""
        rs = self.runners()
        return rs[0] if rs else None

    # -- hatch submits --
    def submit(self, spec: JobSpec) -> Path:
        validate_job(spec, self.repo_allowlist)
        p = self.root / "jobs" / "pending" / f"{spec.job_id}.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(spec.to_dict(), indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
        return p

    def pending(self) -> list[JobSpec]:
        out = []
        for p in sorted((self.root / "jobs" / "pending").glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            d.pop("schema", None)
            out.append(JobSpec(**d))
        return out

    # -- runner protocol steps 2-3: filter + atomic claim --
    def claim(self, runner: RunnerRecord, now: str | None = None) -> JobSpec | None:
        for spec in self.pending():
            ok, why = runner.satisfies(spec.requirements)
            src = self.root / "jobs" / "pending" / f"{spec.job_id}.json"
            if not ok:
                # reject before clone/execute; write mismatch result; move to done
                self._write_result(spec, status="mismatch", reason="; ".join(why), runner=runner.hostname)
                src.replace(self.root / "jobs" / "done" / src.name)
                continue
            dst = self.root / "jobs" / "claimed" / src.name
            try:
                src.rename(dst)  # atomic on the same filesystem; second claimer fails
            except FileNotFoundError:
                continue
            claim = {**spec.to_dict(), "claimed_by": runner.hostname, "claimed_at": now or now_iso()}
            dst.write_text(json.dumps(claim, indent=1, sort_keys=True), encoding="utf-8")
            return spec
        return None

    # -- runner protocol steps 4-7 --
    def execute(self, spec: JobSpec, checkout: Path, runner: RunnerRecord) -> dict[str, Any]:
        """Verify inputs, run argv without a shell, parse metrics, hash outputs, write result."""
        checkout = Path(checkout)
        for inp in spec.inputs:
            p = canonical_in_root(inp["path"], checkout)
            if not p.exists() or file_sha256(p) != inp["sha256"]:
                res = self._write_result(spec, status="input_mismatch", reason=f"input {inp['path']} hash mismatch", runner=runner.hostname)
                self._finish(spec)
                return res
        cwd = canonical_in_root(spec.cwd, checkout)
        t0 = time.monotonic()
        try:
            proc = run_argv(spec.argv, cwd=cwd, timeout_s=float(spec.timeout_seconds), max_output_bytes=MAX_OUTPUT_BYTES)
        except Exception as e:  # timeout or policy: honest failure result
            res = self._write_result(spec, status="failed", reason=f"{e.__class__.__name__}", runner=runner.hostname)
            self._finish(spec)
            return res
        metrics = parse_metrics(proc["stdout"])
        outputs: list[dict[str, Any]] = []
        missing_required: list[str] = []
        for out in spec.outputs:
            p = canonical_in_root(out["path"], checkout)
            if p.exists():
                outputs.append({"path": out["path"], "sha256": file_sha256(p), "bytes": p.stat().st_size})
            elif out.get("required"):
                missing_required.append(out["path"])
        status = "ok" if proc["exit_code"] == 0 and not missing_required else "failed"
        res = self._write_result(
            spec,
            status=status,
            reason="" if status == "ok" else f"exit {proc['exit_code']}; missing {missing_required}",
            runner=runner.hostname,
            extra={"exit_code": proc["exit_code"], "metrics": metrics, "outputs": outputs, "wall_seconds": round(time.monotonic() - t0, 3), "truncated": proc["truncated"]},
            log=proc["stdout"][-65536:] + ("\n--- stderr ---\n" + proc["stderr"][-65536:] if proc["stderr"] else ""),
        )
        self._finish(spec)
        return res

    def _write_result(self, spec: JobSpec, *, status: str, reason: str, runner: str, extra: dict[str, Any] | None = None, log: str = "") -> dict[str, Any]:
        d = self.root / "results" / spec.job_id
        d.mkdir(parents=True, exist_ok=True)
        res = {"schema": active("forge-result"), "job_id": spec.job_id, "status": status, "reason": reason, "runner": runner, "finished_at": now_iso(), **(extra or {})}
        (d / "result.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
        (d / "log.txt").write_text(log, encoding="utf-8")
        return res

    def _finish(self, spec: JobSpec) -> None:
        src = self.root / "jobs" / "claimed" / f"{spec.job_id}.json"
        if src.exists():
            src.replace(self.root / "jobs" / "done" / src.name)

    def result(self, job_id: str) -> dict[str, Any] | None:
        p = self.root / "results" / job_id / "result.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def orphans(self, now_iso_value: str | None = None) -> list[str]:
        """Claimed jobs whose runner heartbeat is older than the orphan window."""
        now = parse_iso(now_iso_value or now_iso())
        beats = {r.hostname: parse_iso(r.heartbeat_at) for r in self.runners()}
        out = []
        for p in (self.root / "jobs" / "claimed").glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            hb = beats.get(d.get("claimed_by"))
            if hb is None or (now - hb).total_seconds() > HEARTBEAT_ORPHAN_S:
                out.append(d["job_id"])
        return out

    def require_runner(self) -> RunnerRecord:
        r = self.registered_runner()
        if r is None:
            raise BlockedError("no Forge runner is registered; install runner and advertise hardware", "forge_runner")
        return r


def parse_metrics(stdout: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in stdout.splitlines():
        m = _METRIC_RE.match(line.strip())
        if m:
            try:
                out[m.group(1)] = float(m.group(2))
            except ValueError:
                continue
    return out
