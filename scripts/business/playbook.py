#!/usr/bin/env python3
"""Generate venture business artifacts from playbook policy files.

WHY. Every venture surface in this repo (validation, research, monitor, ops)
needs recurring paper artifacts — dataset cards, briefs, scoreboards, digests —
and the failure mode this engine exists to prevent is the artifact that was
hand-edited once and silently went stale. A playbook at playbooks/<venture>.yaml
is policy-as-config: it declares WHAT is produced, FROM WHICH committed inputs,
and WHERE (only ever under workspace/artifacts/<venture>/). This engine is the
only thing that acts on a playbook; nothing here schedules — `cadence` is
documentation for the operator, and runs happen only when someone invokes `run`.

Decisions worth knowing before editing:

  * Skip, never invent. A required input with zero resolved files means the
    artifact is NOT generated (status skipped-missing-input) — the exporter
    precedent (build_runs_readout.mjs) is that absent data is reported absent,
    not simulated. A generator module that has not landed yet is likewise a
    skip (skipped-missing-generator), never a crash: playbooks may reference
    generators another lane ships later.
  * Idempotency has two layers. Fast path: if every resolved input hash and
    every recorded output hash match the venture manifest, the generator is not
    even called. Content path: if the generator runs and produces byte-identical
    output, the file is not rewritten (this is what makes zero-input artifacts
    like the ops changelog idempotent). Either way the status is "unchanged".
  * Output paths are validated BEFORE generation against the repo's gitignore
    traps (.gitignore:33-35,110,126,134-135): reserved segments (data, runs,
    export, pipeline, checkpoints, ckpt, wandb, mlruns, hf_model), trap
    basenames (candidate.json, secrets.json, credentials.json, .env.local) and
    trap suffixes (*.parquet *.arrow *.pt *.bin *.log *.tmp). A violating
    output would silently never commit, which is worse than failing loudly.
  * Manifest provenance fallback order: a JSON output's top-level "provenance"
    block wins; else a module-level PROVENANCE dict on the generator; else
    {"classification": "REAL", "method": "deterministic recomputation from
    committed inputs"}. Artifacts the engine skipped record PLACEHOLDER with
    the skip reason, so the manifest never claims generation that did not run.
  * --dry-run resolves inputs and reports would-write / would-skip but writes
    NOTHING — not even the manifest — and never calls a generator.

Repo root is DOTTIE_ROOT when set (the build_hub_registry.mjs precedent, and
what makes the self-test hermetic), else two directories up from this file.

Usage:
    uv run python scripts/business/playbook.py list
    uv run python scripts/business/playbook.py run <venture> [--artifact <id>] [--dry-run]
    uv run python scripts/business/playbook.py status [--json]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("DOTTIE_ROOT", Path(__file__).resolve().parents[2]))

GENERATED_BY = "scripts/business/playbook.py"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CADENCES = ("on-demand", "daily", "weekly")

# Gitignore traps, verified at .gitignore:33-35,110,126,134-135. An output that
# matches any of these would land on disk and silently never commit.
RESERVED_SEGMENTS = frozenset(
    {"data", "runs", "export", "pipeline", "checkpoints", "ckpt", "wandb",
     "mlruns", "hf_model"}
)
TRAP_BASENAMES = frozenset(
    {"candidate.json", "secrets.json", "credentials.json", ".env.local"}
)
TRAP_BASENAME_GLOBS = ("*.parquet", "*.arrow", "*.pt", "*.bin", "*.log", "*.tmp")

DEFAULT_PROVENANCE = {
    "classification": "REAL",
    "method": "deterministic recomputation from committed inputs",
}

LABELS = {
    "written": "WRITE",
    "unchanged": "UNCHANGED",
    "skipped-missing-input": "SKIP",
    "skipped-missing-generator": "SKIP",
    "error": "ERROR",
    "would-write": "WOULD-WRITE",
    "would-skip": "WOULD-SKIP",
}

_GLOB_CHARS = ("*", "?", "[")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Schema validation (pure over the parsed document — no filesystem access, so
# the self-test can validate the real playbooks under a hermetic DOTTIE_ROOT).
# ---------------------------------------------------------------------------


def _output_path_errors(raw: str, venture: str) -> list[str]:
    errs: list[str] = []
    parts = raw.split("/")
    if raw.startswith("/") or ".." in parts:
        errs.append(f"output {raw!r} must be repo-root-relative without '..'")
    prefix = f"workspace/artifacts/{venture}/"
    if not raw.startswith(prefix) or len(parts) < 4:
        errs.append(f"output {raw!r} must live under {prefix}")
    for seg in parts:
        if seg in RESERVED_SEGMENTS:
            errs.append(
                f"output {raw!r}: segment {seg!r} is a gitignored trap "
                "(.gitignore:33-35,110) and would silently not commit"
            )
    base = parts[-1]
    if base in TRAP_BASENAMES:
        errs.append(f"output {raw!r}: basename {base!r} is gitignored (.gitignore:134)")
    for pat in TRAP_BASENAME_GLOBS:
        if fnmatch.fnmatch(base, pat):
            errs.append(f"output {raw!r}: basename matches gitignored pattern {pat!r}")
    return errs


def output_list(artifact: dict) -> list[str]:
    out = artifact.get("output")
    return [out] if isinstance(out, str) else list(out or [])


def validate_playbook(doc: object, stem: str) -> list[str]:
    """Return every schema-v1 violation in `doc`; empty list means valid."""
    if not isinstance(doc, dict):
        return [f"{stem}: playbook must be a YAML mapping"]
    errs: list[str] = []
    if doc.get("schema_version") != 1:
        errs.append(
            f"{stem}: schema_version must be 1, got {doc.get('schema_version')!r}"
        )
    venture = doc.get("venture")
    if not isinstance(venture, str) or not NAME_RE.match(venture):
        errs.append(f"{stem}: venture must match ^[a-z][a-z0-9-]*$")
    elif venture != stem:
        errs.append(f"{stem}: venture {venture!r} must equal the filename stem")
    desc = doc.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errs.append(f"{stem}: description is required")
    if doc.get("cadence") not in CADENCES:
        errs.append(f"{stem}: cadence must be one of {', '.join(CADENCES)}")
    arts = doc.get("artifacts")
    if not isinstance(arts, list) or not arts:
        errs.append(f"{stem}: artifacts must be a non-empty list")
        return errs
    vname = venture if isinstance(venture, str) else stem
    seen_ids: set[str] = set()
    for i, art in enumerate(arts):
        where = f"{stem}: artifacts[{i}]"
        if not isinstance(art, dict):
            errs.append(f"{where} must be a mapping")
            continue
        aid = art.get("id")
        if not isinstance(aid, str) or not NAME_RE.match(aid):
            errs.append(f"{where}.id must match ^[a-z][a-z0-9-]*$")
        elif aid in seen_ids:
            errs.append(f"{where}.id {aid!r} duplicates an earlier artifact")
        else:
            seen_ids.add(aid)
        gen = art.get("generator")
        if not isinstance(gen, str) or not NAME_RE.match(gen.replace("_", "-")):
            errs.append(f"{where}.generator must be a module basename (no .py)")
        inputs = art.get("inputs")
        if not isinstance(inputs, list):
            errs.append(f"{where}.inputs must be a list (may be empty)")
        else:
            for j, entry in enumerate(inputs):
                ok = (
                    isinstance(entry, dict)
                    and isinstance(entry.get("name"), str)
                    and entry.get("name")
                    and isinstance(entry.get("path"), str)
                    and entry.get("path")
                    and isinstance(entry.get("required", True), bool)
                )
                if not ok:
                    errs.append(
                        f"{where}.inputs[{j}] needs str name, str path, bool required"
                    )
        outs = output_list(art)
        if not outs or not all(isinstance(o, str) for o in outs):
            errs.append(f"{where}.output must be a string or non-empty list of strings")
        else:
            for o in outs:
                errs.extend(f"{where}: {e}" for e in _output_path_errors(o, vname))
            basenames = [o.split("/")[-1] for o in outs]
            if len(set(basenames)) != len(basenames):
                errs.append(f"{where}.output basenames must be unique")
        hint = art.get("publish_hint")
        if not isinstance(hint, str) or not hint.strip():
            errs.append(f"{where}.publish_hint is required")
        params = art.get("params", {})
        scalar = (str, int, float, bool, type(None))
        if not isinstance(params, dict) or not all(
            isinstance(k, str) and isinstance(v, scalar) for k, v in params.items()
        ):
            errs.append(f"{where}.params must map str keys to plain scalars")
    return errs


# ---------------------------------------------------------------------------
# Input resolution and generator dispatch.
# ---------------------------------------------------------------------------


def resolve_inputs(
    artifact: dict,
) -> tuple[dict[str, list[Path]], list[dict], list[str]]:
    """Expand each input to existing files; return (resolved, sources, missing)."""
    resolved: dict[str, list[Path]] = {}
    sources: list[dict] = []
    missing: list[str] = []
    for entry in artifact.get("inputs", []):
        pattern = entry["path"]
        required = bool(entry.get("required", True))
        if any(ch in pattern for ch in _GLOB_CHARS):
            paths = sorted(p for p in ROOT.glob(pattern) if p.is_file())
        else:
            candidate = ROOT / pattern
            paths = [candidate] if candidate.is_file() else []
        resolved[entry["name"]] = paths
        for p in paths:
            sources.append(
                {
                    "path": p.relative_to(ROOT).as_posix(),
                    "sha256": sha256_file(p),
                    "required": required,
                }
            )
        if required and not paths:
            missing.append(pattern)
    return resolved, sources, missing


_LOAD_GENERATOR = None


def _load_generator(name: str):
    """Load a generator through the shared loader in generators/__init__.py."""
    global _LOAD_GENERATOR  # memoised loader, set once
    if _LOAD_GENERATOR is None:
        init_path = Path(__file__).resolve().parent / "generators" / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "dottie_business_generators", init_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOAD_GENERATOR = module.load_generator
    return _LOAD_GENERATOR(name, ROOT)


def _fast_path_unchanged(
    sources: list[dict], out_paths: list[str], prev: dict | None
) -> bool:
    """True when inputs AND outputs all match the manifest's recorded hashes.

    Requires at least one resolved source: zero-input artifacts (changelog)
    always fall through to the content path, because their content can change
    with no file input changing.
    """
    if not sources or not isinstance(prev, dict):
        return False
    prev_sources = {
        (s.get("path"), s.get("sha256")) for s in prev.get("sources", [])
    }
    if {(s["path"], s["sha256"]) for s in sources} != prev_sources:
        return False
    prev_outputs = prev.get("outputs", [])
    if {o.get("path") for o in prev_outputs} != set(out_paths):
        return False
    for rec in prev_outputs:
        target = ROOT / rec["path"]
        if not target.is_file() or sha256_file(target) != rec.get("sha256"):
            return False
    return True


def _skip_provenance(detail: str) -> dict[str, str]:
    return {"classification": "PLACEHOLDER", "method": f"not generated: {detail}"}


def _provenance(rendered: dict[str, str], module) -> dict[str, str]:
    """Provenance for the manifest: JSON output block > module PROVENANCE > default."""
    for basename in sorted(rendered):
        if not basename.endswith(".json"):
            continue
        try:
            obj = json.loads(rendered[basename])
        except ValueError:
            continue
        prov = obj.get("provenance") if isinstance(obj, dict) else None
        if isinstance(prov, dict) and "classification" in prov and "method" in prov:
            return {
                "classification": str(prov["classification"]),
                "method": str(prov["method"]),
            }
    prov = getattr(module, "PROVENANCE", None)
    if isinstance(prov, dict) and "classification" in prov and "method" in prov:
        return {
            "classification": str(prov["classification"]),
            "method": str(prov["method"]),
        }
    return dict(DEFAULT_PROVENANCE)


def run_artifact(
    venture: str, artifact: dict, prev_entry: dict | None, dry_run: bool
) -> tuple[str, str, dict | None]:
    """Run one artifact; return (status, detail, manifest entry or None)."""
    generated_at = now_iso()
    outs = output_list(artifact)
    resolved, sources, missing = resolve_inputs(artifact)

    def entry(status: str, outputs: list | None = None, prov: dict | None = None):
        return {
            "status": status,
            "generated_at": generated_at,
            "outputs": outputs or [],
            "sources": sources,
            "provenance": prov or dict(DEFAULT_PROVENANCE),
        }

    if missing:
        detail = "missing required input: " + ", ".join(missing)
        if dry_run:
            return "would-skip", detail, None
        status = "skipped-missing-input"
        return status, detail, entry(status, prov=_skip_provenance(detail))

    if _fast_path_unchanged(sources, outs, prev_entry):
        detail = "inputs and outputs match recorded hashes"
        if dry_run:
            return "would-skip", detail, None
        prov = (prev_entry or {}).get("provenance") or dict(DEFAULT_PROVENANCE)
        return "unchanged", detail, entry(
            "unchanged", outputs=(prev_entry or {}).get("outputs", []), prov=prov
        )

    gen_name = artifact["generator"]
    gen_rel = f"scripts/business/generators/{gen_name}.py"
    if not (ROOT / gen_rel).is_file():
        detail = f"no generator module at {gen_rel}"
        if dry_run:
            return "would-skip", detail, None
        status = "skipped-missing-generator"
        return status, detail, entry(status, prov=_skip_provenance(detail))

    if dry_run:
        return "would-write", ", ".join(outs), None

    try:
        module = _load_generator(gen_name)
    except FileNotFoundError:
        status = "skipped-missing-generator"
        detail = f"no generator module at {gen_rel}"
        return status, detail, entry(status, prov=_skip_provenance(detail))
    except Exception as exc:  # exec_module failed — a real defect, not a skip
        detail = f"generator import failed: {type(exc).__name__}: {exc}"
        return "error", detail, entry("error", prov=_skip_provenance(detail))

    try:
        rendered = module.generate(resolved, dict(artifact.get("params") or {}),
                                   generated_at)
    except FileNotFoundError as exc:
        detail = f"generator reported missing input: {exc}"
        status = "skipped-missing-input"
        return status, detail, entry(status, prov=_skip_provenance(detail))
    except Exception as exc:
        detail = f"generator raised {type(exc).__name__}: {exc}"
        return "error", detail, entry("error", prov=_skip_provenance(detail))

    declared = {o.split("/")[-1]: o for o in outs}
    bad_shape = (
        not isinstance(rendered, dict)
        or set(rendered) != set(declared)
        or not all(isinstance(v, str) for v in rendered.values())
    )
    if bad_shape:
        got = sorted(rendered) if isinstance(rendered, dict) else type(rendered).__name__
        detail = (
            f"generator returned basenames {got}; playbook declares "
            f"{sorted(declared)} (must match exactly, all values str)"
        )
        return "error", detail, entry("error", prov=_skip_provenance(detail))

    wrote_any = False
    out_records = []
    for basename in sorted(declared):
        rel = declared[basename]
        data = rendered[basename].encode("utf-8")
        target = ROOT / rel
        if not (target.is_file() and target.read_bytes() == data):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            wrote_any = True
        out_records.append(
            {"path": rel, "sha256": hashlib.sha256(data).hexdigest()}
        )
    status = "written" if wrote_any else "unchanged"
    return status, ", ".join(outs), entry(
        status, outputs=out_records, prov=_provenance(rendered, module)
    )


# ---------------------------------------------------------------------------
# CLI commands.
# ---------------------------------------------------------------------------


def cmd_run(venture: str, artifact_id: str | None, dry_run: bool) -> int:
    pb_path = ROOT / "playbooks" / f"{venture}.yaml"
    if not pb_path.is_file():
        print(f"FAIL  no playbook at playbooks/{venture}.yaml")
        return 1
    try:
        doc = yaml.safe_load(pb_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"FAIL  playbooks/{venture}.yaml is not parseable YAML: {exc}")
        return 1
    errors = validate_playbook(doc, venture)
    if errors:
        for err in errors:
            print(f"FAIL  {err}")
        return 1
    artifacts = doc["artifacts"]
    if artifact_id is not None:
        artifacts = [a for a in artifacts if a["id"] == artifact_id]
        if not artifacts:
            print(f"FAIL  {venture}: no artifact with id {artifact_id!r}")
            return 1

    manifest_path = ROOT / "workspace" / "artifacts" / venture / "manifest.json"
    recorded: dict = {}
    if manifest_path.is_file():
        try:
            recorded = json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "artifacts", {}
            )
        except ValueError:
            recorded = {}

    had_error = False
    for art in artifacts:
        status, detail, new_entry = run_artifact(
            venture, art, recorded.get(art["id"]), dry_run
        )
        print(f"{LABELS[status]:<11} {venture}/{art['id']}  [{status}] {detail}")
        if status == "error":
            had_error = True
        if new_entry is not None and not dry_run:
            recorded[art["id"]] = new_entry

    if not dry_run:
        payload = {
            "generated_by": GENERATED_BY,
            "schema_version": 1,
            "venture": venture,
            "updated_at": now_iso(),
            "artifacts": recorded,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"manifest: workspace/artifacts/{venture}/manifest.json")
    return 1 if had_error else 0


def cmd_list() -> int:
    pb_dir = ROOT / "playbooks"
    files = sorted(pb_dir.glob("*.yaml")) if pb_dir.is_dir() else []
    if not files:
        print("no playbooks found under playbooks/")
        return 0
    for path in files:
        stem = path.stem
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            print(f"{stem}  INVALID (unparseable YAML)")
            continue
        errors = validate_playbook(doc, stem)
        if errors:
            print(f"{stem}  INVALID ({len(errors)} schema errors; `run {stem}` lists them)")
            continue
        ids = ", ".join(a["id"] for a in doc["artifacts"])
        print(f"{stem}  cadence={doc['cadence']}  artifacts: {ids}")
    return 0


def cmd_status(as_json: bool) -> int:
    ventures: dict[str, dict | None] = {}
    pb_dir = ROOT / "playbooks"
    if pb_dir.is_dir():
        for path in sorted(pb_dir.glob("*.yaml")):
            ventures.setdefault(path.stem, None)
    art_root = ROOT / "workspace" / "artifacts"
    if art_root.is_dir():
        for mpath in sorted(art_root.glob("*/manifest.json")):
            try:
                ventures[mpath.parent.name] = json.loads(
                    mpath.read_text(encoding="utf-8")
                )
            except ValueError:
                ventures[mpath.parent.name] = {"error": "manifest unreadable"}

    if as_json:
        payload = {
            "generated_by": GENERATED_BY,
            "ventures": {
                v: (m if m is not None else {"note": "no runs recorded"})
                for v, m in sorted(ventures.items())
            },
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    rows = [("venture", "artifact", "status", "generated_at")]
    for v, manifest in sorted(ventures.items()):
        arts = (manifest or {}).get("artifacts", {})
        if not arts:
            rows.append((v, "-", "no runs recorded", "-"))
            continue
        for aid, e in sorted(arts.items()):
            rows.append(
                (v, aid, str(e.get("status", "?")), str(e.get("generated_at", "?")))
            )
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for row in rows:
        print("  ".join(col.ljust(widths[i]) for i, col in enumerate(row)).rstrip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="playbook.py",
        description="Generate venture artifacts from playbooks/<venture>.yaml.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list playbooks and their artifacts")
    run_p = sub.add_parser("run", help="run one venture's playbook")
    run_p.add_argument("venture", help="playbook filename stem")
    run_p.add_argument("--artifact", help="run only this artifact id")
    run_p.add_argument("--dry-run", action="store_true",
                       help="report would-write/would-skip; write nothing")
    status_p = sub.add_parser("status", help="report recorded manifest statuses")
    status_p.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "run":
        return cmd_run(args.venture, args.artifact, args.dry_run)
    return cmd_status(args.as_json)


if __name__ == "__main__":
    sys.exit(main())
