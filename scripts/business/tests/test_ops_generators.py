#!/usr/bin/env python3
"""Self-test for the ops and monitor playbook generators.

These generators exist to state only what the inputs state — copied numbers,
mechanical counts, skipped-never-guessed malformed lines. The tests pin
exactly that: scoreboard aggregates are recomputed from fixture event logs
(odd-count median pinned, malformed line counted as skipped), the changelog
lists commit subjects from a throwaway git repository built here (SHAs cited,
branch names never printed), and the ops digest copies figures or states the
exact absence sentence. Hermetic: every fixture is written into a
TemporaryDirectory by this script; no bundles/ultra/runs, TODO.md,
workspace/artifacts, or any other real repo file is read — other lanes write
those concurrently.

    uv run python scripts/business/tests/test_ops_generators.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_GEN_DIR = Path(__file__).resolve().parent.parent / "generators"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _GEN_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sb = _load("run_scoreboard")
cl = _load("changelog")
od = _load("ops_digest")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  — {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


def frontmatter(text: str):
    """Parse the YAML block between the leading --- fences; None on failure."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    try:
        return yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None


STAMP = "2026-08-09T00:00:00Z"


def _event(**kw) -> str:
    base = {
        "ts": "2026-08-09T01:00:00.000000Z",
        "nodeId": "fixture.node",
        "attempt": 1,
        "tokens": 2,
        "errorClass": None,
        "layer": 1,
        "status": "ok",
    }
    base.update(kw)
    return json.dumps(base)


RUN_A_LINES = [
    _event(runId="run-a", agentId="researcher", latency_ms=10),
    _event(runId="run-a", agentId="researcher", latency_ms=30),
    _event(runId="run-a", agentId="researcher", latency_ms=50),
    _event(runId="run-a", agentId="strategist", latency_ms=20),
    _event(runId="run-a", agentId="strategist", latency_ms=40),
    _event(
        runId="run-a", agentId="strategist", latency_ms=60,
        status="error", errorClass="Timeout",
    ),
    _event(
        runId="run-a", agentId="strategist", latency_ms=80,
        status="error", errorClass="Timeout",
    ),
]
RUN_B_LINES = [
    "not json",
    # counted event with NO latency_ms: excluded from the median, not the count
    json.dumps({"runId": "run-b", "agentId": "researcher", "status": "ok"}),
]


def _git(cwd: Path, *args: str, env=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True,
        capture_output=True, text=True,
    )


def _git_env() -> dict:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Fixture Author",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-02T03:04:05 +0000",
            "GIT_COMMITTER_NAME": "Fixture Author",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_DATE": "2026-01-02T03:04:05 +0000",
        }
    )
    return env


def _commit(cwd: Path, env: dict, filename: str, subject: str) -> None:
    (cwd / filename).write_text(subject + "\n", encoding="utf-8")
    _git(cwd, "add", filename, env=env)
    _git(cwd, "commit", "-m", subject, env=env)


SCOREBOARD_FIXTURE = {
    "generated_by": "scripts/business/generators/run_scoreboard.py",
    "generated_at": STAMP,
    "provenance": {
        "classification": "REAL",
        "method": "fixture",
        "sources": [],
    },
    "agents": {
        "researcher": {"runs": 2, "events": 4, "ok_rate": 0.9, "p50_latency_ms": 30},
        "strategist": {"runs": 1, "events": 4, "ok_rate": 0.5, "p50_latency_ms": 50},
    },
    "totals": {"files": 2, "events": 8, "skipped_lines": 1},
}

TODO_FIXTURE = """\
# TODO fixture

Header paragraph; the next-section pointer lives in the real file, this one
only exercises the mechanical checkbox count.

- [ ] first open item
- [ ] second open item
- [x] a completed item that must not be counted
- [ ] third open item
"""


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    # -----------------------------------------------------------------------
    # run_scoreboard — two fake run dirs in the verified event shape.
    # -----------------------------------------------------------------------
    run_a = root / "run-a-dir"
    run_b = root / "run-b-dir"
    run_a.mkdir()
    run_b.mkdir()
    (run_a / "timeline.jsonl").write_text(
        "\n".join(RUN_A_LINES) + "\n", encoding="utf-8"
    )
    (run_b / "timeline.jsonl").write_text(
        "\n".join(RUN_B_LINES) + "\n", encoding="utf-8"
    )
    timelines = [run_a / "timeline.jsonl", run_b / "timeline.jsonl"]

    out = sb.generate({"timelines": timelines}, {}, STAMP)
    check(
        "scoreboard returns both outputs",
        set(out) == {"scoreboard.json", "scoreboard.md"},
        str(set(out)),
    )
    board = json.loads(out["scoreboard.json"])
    agents = board.get("agents", {})
    researcher = agents.get("researcher", {})
    strategist = agents.get("strategist", {})
    check("researcher runs == 2 (distinct runIds)", researcher.get("runs") == 2,
          str(researcher))
    check(
        "researcher events == 4 (missing-latency event still counted)",
        researcher.get("events") == 4,
        str(researcher),
    )
    check(
        "researcher p50 == 30 (odd count pins the median; no-latency excluded)",
        researcher.get("p50_latency_ms") == 30,
        str(researcher),
    )
    check("researcher ok_rate == 1.0", researcher.get("ok_rate") == 1.0)
    check("strategist ok_rate == 0.5", strategist.get("ok_rate") == 0.5,
          str(strategist))
    check(
        "totals: 2 files, 8 events, 1 skipped line",
        board.get("totals") == {"files": 2, "events": 8, "skipped_lines": 1},
        str(board.get("totals")),
    )
    check(
        "scoreboard.json carries generated_by",
        board.get("generated_by") == "scripts/business/generators/run_scoreboard.py",
    )
    check(
        "scoreboard.json provenance classification is REAL",
        board.get("provenance", {}).get("classification") == "REAL",
    )
    check(
        "provenance sources record the per-file skipped_lines tally",
        [s.get("skipped_lines") for s in board["provenance"]["sources"]] == [0, 1],
        str(board["provenance"]["sources"]),
    )
    md = out["scoreboard.md"]
    fm = frontmatter(md) or {}
    check("scoreboard.md frontmatter parses as YAML", isinstance(frontmatter(md), dict))
    check("scoreboard.md classification is REAL", fm.get("classification") == "REAL")
    check("scoreboard.md generated_at equals the stamp", fm.get("generated_at") == STAMP)
    check(
        "scoreboard.md carries the history-not-telemetry sentence",
        "This scoreboard is history recomputed from committed event logs, "
        "not live telemetry." in md,
    )
    check(
        "scoreboard.md renders the researcher row",
        "| researcher | 2 | 4 | 1.0 | 30 |" in md,
        md,
    )
    again = sb.generate({"timelines": timelines}, {}, STAMP)
    check(
        "scoreboard is byte-deterministic (both outputs)",
        again == out,
    )
    try:
        sb.generate({"timelines": []}, {}, STAMP)
        check("empty timelines raises FileNotFoundError", False, "no exception")
    except FileNotFoundError:
        check("empty timelines raises FileNotFoundError", True)

    # -----------------------------------------------------------------------
    # changelog — throwaway git repo; 2 base commits on main, 2 on a branch.
    # -----------------------------------------------------------------------
    repo = root / "gitfixture"
    repo.mkdir()
    env = _git_env()
    _git(repo, "init", "-b", "main", env=env)
    _commit(repo, env, "a.txt", "Add scoreboard input notes")
    _commit(repo, env, "b.txt", "Record baseline event counts")
    _git(repo, "checkout", "-b", "topic-xyzzy", env=env)
    _commit(repo, env, "c.txt", "Refine digest section ordering")
    _commit(repo, env, "d.txt", "State absence facts in artifact copy")
    base_sha = _git(repo, "merge-base", "HEAD", "main", env=env).stdout.strip()
    head_sha = _git(repo, "rev-parse", "HEAD", env=env).stdout.strip()

    entry = cl.generate(
        {}, {"base_ref": "main", "repo_root": str(repo)}, STAMP
    )["changelog_entry.md"]
    bullets = [line for line in entry.splitlines() if line.startswith("- ")]
    check(
        "changelog lists exactly the 2 branch commits",
        len(bullets) == 2,
        str(bullets),
    )
    check(
        "changelog bullets carry short sha, date, and subject",
        f"- {head_sha[:7]} (2026-01-02) State absence facts in artifact copy"
        in bullets,
        str(bullets),
    )
    check(
        "both fixture subjects render verbatim",
        any("Refine digest section ordering" in b for b in bullets)
        and any("State absence facts in artifact copy" in b for b in bullets),
    )
    check(
        "base commits are not listed",
        "Add scoreboard input notes" not in entry
        and "Record baseline event counts" not in entry,
    )
    cfm = frontmatter(entry) or {}
    fm_shas = [s.get("sha") for s in cfm.get("sources", [])]
    check(
        "frontmatter cites the merge-base and HEAD shas",
        fm_shas == [base_sha, head_sha],
        str(cfm.get("sources")),
    )
    check(
        "the branch name is not printed anywhere",
        "topic-xyzzy" not in entry,
    )
    check("changelog classification is REAL", cfm.get("classification") == "REAL")
    check("changelog generated_at equals the stamp", cfm.get("generated_at") == STAMP)
    again = cl.generate(
        {}, {"base_ref": "main", "repo_root": str(repo)}, STAMP
    )["changelog_entry.md"]
    check("changelog regeneration is byte-identical", again == entry)

    missing = cl.generate(
        {}, {"base_ref": "nonexistent", "repo_root": str(repo)}, STAMP
    )["changelog_entry.md"]
    check(
        "missing base ref degrades with the measured fallback sentence",
        "base ref nonexistent not found; showing the 20 most recent commits"
        in missing,
        missing,
    )
    check(
        "fallback still lists commits (all 4 fixture commits fit in 20)",
        sum(1 for line in missing.splitlines() if line.startswith("- ")) == 4,
    )
    try:
        cl.generate({}, {"base_ref": "main", "repo_root": str(root / "notarepo")},
                    STAMP)
        check("no git history raises FileNotFoundError", False, "no exception")
    except FileNotFoundError:
        check("no git history raises FileNotFoundError", True)

    # -----------------------------------------------------------------------
    # ops_digest — fixture scoreboard + fixture todo + counted test files.
    # -----------------------------------------------------------------------
    board_p = root / "scoreboard.json"
    board_p.write_text(
        json.dumps(SCOREBOARD_FIXTURE, sort_keys=True, indent=2), encoding="utf-8"
    )
    todo_p = root / "todo_sample.md"
    todo_p.write_text(TODO_FIXTURE, encoding="utf-8")
    test_a = root / "test_alpha.py"
    test_b = root / "test_beta.py"
    test_a.write_text("", encoding="utf-8")
    test_b.write_text("", encoding="utf-8")

    digest = od.generate(
        {"scoreboard": [board_p], "todo": [todo_p], "test_files": [test_a, test_b]},
        {},
        STAMP,
    )["ops_digest.md"]
    check("digest states the fixture agent count", "Agents recorded: 2." in digest,
          digest)
    check("digest states the fixture event total", "Total events: 8." in digest)
    check(
        "digest states min/max ok_rate copied from the fixture",
        "OK-rate range: 0.5 (minimum) to 0.9 (maximum)." in digest,
        digest,
    )
    check(
        "open checkbox count is 3 (the checked box is excluded)",
        "Open checkbox lines (`- [ ]`) in TODO.md: 3." in digest,
        digest,
    )
    check(
        "digest repeats the canonical HANDOFF.md pointer verbatim",
        'TODO.md directs open-work triage to HANDOFF.md '
        '("Open, needing an operator decision").' in digest,
    )
    check(
        "test-file count is stated as a labeled file count",
        "repo-root self-test files: 2 "
        "(scripts/test_*.py, counted at generation time)" in digest,
    )
    dfm = frontmatter(digest) or {}
    check("digest frontmatter parses as YAML", isinstance(frontmatter(digest), dict))
    check("digest classification is REAL", dfm.get("classification") == "REAL")
    check(
        "digest cites both read files as sources",
        len(dfm.get("sources", [])) == 2,
        str(dfm.get("sources")),
    )
    check(
        "digest is byte-deterministic",
        od.generate(
            {"scoreboard": [board_p], "todo": [todo_p],
             "test_files": [test_a, test_b]},
            {},
            STAMP,
        )["ops_digest.md"] == digest,
    )

    absent = od.generate(
        {"scoreboard": [], "todo": [todo_p], "test_files": []}, {}, STAMP
    )["ops_digest.md"]
    check(
        "absent scoreboard states the exact absence sentence",
        "No monitor scoreboard was present at generation time." in absent,
        absent,
    )
    check(
        "absent test-file list is a measured zero, not an omission",
        "repo-root self-test files: 0 "
        "(scripts/test_*.py, counted at generation time)" in absent,
    )

    broken_p = root / "scoreboard_broken.json"
    broken_p.write_text("not json {", encoding="utf-8")
    malformed = od.generate(
        {"scoreboard": [broken_p], "todo": [todo_p], "test_files": []}, {}, STAMP
    )["ops_digest.md"]
    check(
        "malformed scoreboard is treated as absent and said so",
        "No monitor scoreboard was present at generation time." in malformed
        and "did not parse as JSON" in malformed,
        malformed,
    )
    check(
        "malformed scoreboard is not cited as a source",
        "scoreboard_broken.json" not in "".join(
            s.get("path", "")
            for s in (frontmatter(malformed) or {}).get("sources", [])
        ),
    )

    try:
        od.generate({"scoreboard": [], "todo": [], "test_files": []}, {}, STAMP)
        check("missing todo raises FileNotFoundError", False, "no exception")
    except FileNotFoundError:
        check("missing todo raises FileNotFoundError", True)


print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
