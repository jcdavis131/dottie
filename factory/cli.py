"""`python -m factory`: one CLI over the three lines (docs/FACTORY.md)."""

from __future__ import annotations

import argparse
import sys

from factory.config import Factory, FactoryError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="factory",
        description="software, MLOps and data lines over the project DAG",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="registries agree with each other and with the DAG")
    nx = sub.add_parser("next", help="the ready frontier of the DAG")
    nx.add_argument("--repo")
    st = sub.add_parser(
        "start", help="DAG node -> in_progress (claims on jarvisd when reachable)"
    )
    st.add_argument("node")
    st.add_argument("--agent", default="factory")
    dn = sub.add_parser("done", help="DAG node -> done, with evidence")
    dn.add_argument("node")
    dn.add_argument("--evidence", required=True)
    va = sub.add_parser("validate", help="run a repo's registered validate gate")
    va.add_argument("repo")
    sub.add_parser("status", help="per-repo checkout state and DAG tally")

    tr = sub.add_parser("train", help="MLOps line: the box training queue")
    tsub = tr.add_subparsers(dest="tcmd", required=True)
    tsub.add_parser("list")
    tsub.add_parser("preflight").add_argument("job")
    run = tsub.add_parser("run")
    g = run.add_mutually_exclusive_group(required=True)
    g.add_argument("job", nargs="?")
    g.add_argument(
        "--next", action="store_true", help="the first job whose preflight passes"
    )
    run.add_argument("--smoke", action="store_true")
    tsub.add_parser("gate").add_argument("job")
    tsub.add_parser("next")
    tsub.add_parser("promote").add_argument("job")

    da = sub.add_parser("data", help="data line: the dataset registry")
    dsub = da.add_subparsers(dest="dcmd", required=True)
    dsub.add_parser("list")
    ck = dsub.add_parser("check")
    ck.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when a required dataset is missing or stale",
    )
    dsub.add_parser("refresh").add_argument("dataset")
    rs = dsub.add_parser("restore")
    rs.add_argument("dataset")
    rs.add_argument("--force", action="store_true")
    return p


def dispatch(f: Factory, a: argparse.Namespace) -> int:
    if a.cmd == "check":
        from factory.check import check, render

        errors, warnings = check(f)
        print(render(errors, warnings))
        return 1 if errors else 0
    if a.cmd in {"next", "start", "done", "validate", "status"}:
        from factory import software

        if a.cmd == "next":
            print(software.next_nodes(f, a.repo))
        elif a.cmd == "start":
            print(software.start(f, a.node, a.agent))
        elif a.cmd == "done":
            print(software.done(f, a.node, a.evidence))
        elif a.cmd == "validate":
            return software.validate(f, a.repo)
        else:
            print(software.status(f))
        return 0
    if a.cmd == "train":
        from factory import mlops

        if a.tcmd == "list":
            print(mlops.list_jobs(f))
        elif a.tcmd == "preflight":
            problems = mlops.preflight(f, f.job(a.job))
            print(mlops.render_preflight(a.job, problems))
            return 1 if problems else 0
        elif a.tcmd == "run":
            job = mlops.next_job(f) if a.next else f.job(a.job)
            if job is None:
                print("no queued job passes preflight; `factory train list`")
                return 1
            result = mlops.run(f, job, smoke=a.smoke)
            print(mlops.render_result(result))
            return (
                0 if result["gate"] == "pass" or (a.smoke and result["rc"] == 0) else 1
            )
        elif a.tcmd == "gate":
            print(mlops.render_gate(mlops.gate(f, f.job(a.job))))
        elif a.tcmd == "next":
            job = mlops.next_job(f)
            if job is None:
                print("no queued job passes preflight; `factory train list`")
                return 1
            print(job["id"])
        else:
            print(mlops.promote(f, f.job(a.job)))
        return 0
    if a.cmd == "data":
        from factory import data

        if a.dcmd == "list":
            print(data.list_datasets(f))
        elif a.dcmd == "check":
            rows = data.check(f)
            print(data.render_check(rows))
            return (
                1 if a.check and any(r["problem"] for r in rows if r["required"]) else 0
            )
        elif a.dcmd == "refresh":
            return data.refresh(f, a.dataset)
        else:
            print(data.restore(f, a.dataset, force=a.force))
        return 0
    return 2


def main(argv: list[str] | None = None, factory: Factory | None = None) -> int:
    a = build_parser().parse_args(argv)
    f = factory or Factory.from_env()
    try:
        return dispatch(f, a)
    except FactoryError as e:
        print(f"factory: {e}", file=sys.stderr)
        return 1
