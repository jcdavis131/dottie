"""`factory check`: the three registries must agree with each other and with the DAG."""

from __future__ import annotations

from pathlib import PurePosixPath

from factory.config import (
    GATE_OPS,
    PROVENANCE,
    ROLES,
    Factory,
    FactoryError,
    dag_module,
)


def _relative(p: object) -> bool:
    return (
        isinstance(p, str)
        and bool(p)
        and not PurePosixPath(p).is_absolute()
        and ".." not in PurePosixPath(p).parts
        and "\\" not in p
    )


def _check_env(entry: dict, where: str, errors: list[str]) -> None:
    env = entry.get("env")
    if env is None:
        return
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in env.items()
    ):
        errors.append(f"{where}: env must map variable names to strings")


def check(f: Factory) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors fail CI; warnings are printed."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        dag = f.dag()
        repos = f.repos()
        jobs = f.jobs()
        datasets = f.datasets()
    except FactoryError as e:
        return [str(e)], []

    dag_errors = dag_module().validate(dag)
    errors += [f"dag: {e}" for e in dag_errors]
    node_ids = {n.get("id") for n in dag.get("nodes", [])}
    dag_repos = {n.get("repo") for n in dag.get("nodes", [])}

    # repos.json
    if not isinstance(repos, dict) or not repos:
        errors.append("repos.json: `repos` must be a non-empty object")
        repos = {}
    for name, entry in repos.items():
        where = f"repos.json[{name}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        if entry.get("role") not in ROLES:
            errors.append(f"{where}: role must be one of {sorted(ROLES)}")
        if entry.get("virtual"):
            continue
        if (
            not isinstance(entry.get("default_branch"), str)
            or not entry["default_branch"]
        ):
            errors.append(f"{where}: default_branch required")
        cmds = entry.get("validate", [])
        if not isinstance(cmds, list) or not all(
            isinstance(c, str) and c.strip() for c in cmds
        ):
            errors.append(
                f"{where}: validate must be a list of non-empty command strings"
            )
        elif not cmds and entry.get("role") not in {"archived"}:
            warnings.append(
                f"{where}: no validate commands ({entry.get('notes', 'no note')})"
            )
        ci = entry.get("ci")
        if ci is not None and not _relative(ci):
            errors.append(f"{where}: ci must be a relative path or null")
    for r in sorted(dag_repos):
        if r not in repos:
            errors.append(
                f"dag: repo {r!r} has no row in repos.json (add it, virtual if it is not a checkout)"
            )

    # train_queue.json
    seen: set[str] = set()
    for j in jobs:
        jid = j.get("id")
        where = f"train_queue.json[{jid}]"
        if not isinstance(jid, str) or not jid:
            errors.append("train_queue.json: every job needs a string id")
            continue
        if jid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(jid)
        if j.get("repo") not in repos:
            errors.append(f"{where}: repo {j.get('repo')!r} not in repos.json")
        if j.get("dag_node") not in node_ids:
            errors.append(f"{where}: dag_node {j.get('dag_node')!r} not in the DAG")
        if not isinstance(j.get("priority"), int) or not 1 <= j["priority"] <= 5:
            errors.append(f"{where}: priority must be an int 1..5")
        for key in ("smoke", "run"):
            if not isinstance(j.get(key), str) or not j[key].strip():
                errors.append(f"{where}: {key} command required")
        if j.get("eval") is not None and not isinstance(j["eval"], str):
            errors.append(f"{where}: eval must be a command string or null")
        needs = j.get("needs", [])
        if not isinstance(needs, list) or not all(_relative(p) for p in needs):
            errors.append(f"{where}: needs must be relative paths inside the repo")
        gate = j.get("gate")
        if not isinstance(gate, dict):
            errors.append(f"{where}: gate object required")
        else:
            if not _relative(gate.get("report")):
                errors.append(f"{where}: gate.report must be a relative path")
            if not isinstance(gate.get("metric"), str) or not gate["metric"]:
                errors.append(
                    f"{where}: gate.metric required (dotted path into the report)"
                )
            if gate.get("op") not in GATE_OPS:
                errors.append(f"{where}: gate.op must be one of {sorted(GATE_OPS)}")
            if not isinstance(gate.get("threshold"), int | float):
                errors.append(f"{where}: gate.threshold must be a number")
        _check_env(j, where, errors)
        if not isinstance(j.get("promote"), list) or not j["promote"]:
            errors.append(f"{where}: promote must list the manual promotion steps")

    # datasets.json
    seen = set()
    for d in datasets:
        did = d.get("id")
        where = f"datasets.json[{did}]"
        if not isinstance(did, str) or not did:
            errors.append("datasets.json: every dataset needs a string id")
            continue
        if did in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(did)
        if d.get("repo") not in repos:
            errors.append(f"{where}: repo {d.get('repo')!r} not in repos.json")
        if not _relative(d.get("path")):
            errors.append(f"{where}: path must be a relative path inside the repo")
        if d.get("provenance") not in PROVENANCE:
            errors.append(f"{where}: provenance must be one of {sorted(PROVENANCE)}")
        cad = d.get("cadence_days")
        if cad is not None and (not isinstance(cad, int) or cad <= 0):
            errors.append(f"{where}: cadence_days must be a positive int or null")
        if cad is not None and not d.get("refresh"):
            warnings.append(
                f"{where}: has a cadence but no refresh command (will go stale by design)"
            )
        fk = d.get("fresh_key", "mtime")
        if fk != "mtime" and not (isinstance(fk, str) and fk.startswith("json:")):
            errors.append(f"{where}: fresh_key must be 'mtime' or 'json:<dotted.key>'")
        rf = d.get("restore_from", [])
        if not isinstance(rf, list) or not all(_relative(p) for p in rf):
            errors.append(
                f"{where}: restore_from must be workspace-relative paths (repo/…)"
            )
        _check_env(d, where, errors)
        for c in d.get("consumers", []):
            if c not in node_ids:
                errors.append(f"{where}: consumer {c!r} not in the DAG")
    return errors, warnings


def render(errors: list[str], warnings: list[str]) -> str:
    lines = [f"warning: {w}" for w in warnings] + [f"error: {e}" for e in errors]
    lines.append(
        f"factory check: {len(errors)} error{'s' if len(errors) != 1 else ''}, "
        f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}"
    )
    return "\n".join(lines)
