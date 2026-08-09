#!/usr/bin/env python3
"""Self-test for the playbook engine (scripts/business/playbook.py).

The engine's whole value is its refusal behaviors: skip when an input or a
generator is absent (never invent), stay byte-stable when nothing changed
(never churn diffs), reject output paths the repo's .gitignore would silently
eat. Each of those refusals is pinned here against a throwaway DOTTIE_ROOT so
the test never reads real bundles/, TODO.md, or any file a concurrent lane is
writing. The four REAL playbooks are additionally validated statically —
schema only, no generator dispatch — so this test stays independent of the
generator lanes landing later.

    uv run python scripts/business/tests/test_playbook_engine.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
ENGINE = REPO / "scripts" / "business" / "playbook.py"

_TMP = tempfile.TemporaryDirectory(prefix="playbook-selftest-")
TMP_ROOT = Path(_TMP.name).resolve()
# Must be set BEFORE the engine module executes: it computes ROOT at import.
os.environ["DOTTIE_ROOT"] = str(TMP_ROOT)

_SPEC = importlib.util.spec_from_file_location("playbook_engine", ENGINE)
pb = importlib.util.module_from_spec(_SPEC)
sys.modules["playbook_engine"] = pb
_SPEC.loader.exec_module(pb)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tail = f"  — {detail}" if detail and not cond else ""
    print(f"{'PASS' if cond else 'FAIL'}  {name}{tail}")


def run_cli(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pb.main(list(args))
    return rc, buf.getvalue()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Fixture root: playbooks/demo.yaml + quiet.yaml, stub generators, seed input.
# ---------------------------------------------------------------------------
(TMP_ROOT / "playbooks").mkdir()
GEN_DIR = TMP_ROOT / "scripts" / "business" / "generators"
GEN_DIR.mkdir(parents=True)
SEED = TMP_ROOT / "seed"
SEED.mkdir()
NOTES = SEED / "notes.txt"
NOTES.write_text("alpha\n", encoding="utf-8")

STUB_COMMON = """\
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def _count(name):
    calls = _ROOT / name
    calls.write_text((calls.read_text() if calls.exists() else "") + "x")
"""

(GEN_DIR / "stub_gen.py").write_text(
    STUB_COMMON
    + """

def generate(inputs, params, generated_at):
    _count("calls_stub_gen.txt")
    if (_ROOT / "raise_fnf.flag").exists():
        raise FileNotFoundError("stub: declared input unusable")
    if (_ROOT / "raise_err.flag").exists():
        raise RuntimeError("stub blew up")
    if (_ROOT / "wrong_keys.flag").exists():
        return {"wrong.md": "nope\\n"}
    body = "".join(p.read_text() for ps in inputs.values() for p in ps)
    return {"out.md": "---\\nfixture: true\\n---\\n" + body}
""",
    encoding="utf-8",
)

(GEN_DIR / "stub_const.py").write_text(
    STUB_COMMON
    + """

def generate(inputs, params, generated_at):
    _count("calls_stub_const.txt")
    return {"const.md": "constant body\\n"}
""",
    encoding="utf-8",
)

(GEN_DIR / "stub_json.py").write_text(
    STUB_COMMON
    + """
import json


def generate(inputs, params, generated_at):
    _count("calls_stub_json.txt")
    doc = {
        "generated_by": "stub_json",
        "provenance": {
            "classification": "HONEST-SYNTHETIC",
            "method": "fixture emission",
            "sources": [],
        },
    }
    return {"card.json": json.dumps(doc, indent=2, sort_keys=True) + "\\n"}
""",
    encoding="utf-8",
)

DEMO_YAML = """\
schema_version: 1
venture: demo
description: Fixture playbook for the engine self-test.
cadence: on-demand
artifacts:
  - id: demo-card
    generator: stub_gen
    inputs:
      - name: notes
        path: seed/notes.txt
    output: workspace/artifacts/demo/out.md
    publish_hint: fixture only.
  - id: demo-const
    generator: stub_const
    inputs: []
    output: workspace/artifacts/demo/const.md
    publish_hint: fixture only.
  - id: demo-json
    generator: stub_json
    inputs: []
    output: workspace/artifacts/demo/card.json
    publish_hint: fixture only.
  - id: demo-missing
    generator: stub_gen
    inputs:
      - name: absent
        path: seed/absent.txt
    output: workspace/artifacts/demo/missing.md
    publish_hint: fixture only.
  - id: demo-nogen
    generator: ghost_gen
    inputs:
      - name: notes
        path: seed/notes.txt
    output: workspace/artifacts/demo/nogen.md
    publish_hint: fixture only.
"""
(TMP_ROOT / "playbooks" / "demo.yaml").write_text(DEMO_YAML, encoding="utf-8")

(TMP_ROOT / "playbooks" / "quiet.yaml").write_text(
    """\
schema_version: 1
venture: quiet
description: Fixture venture that is never run.
cadence: on-demand
artifacts:
  - id: note
    generator: ghost_gen
    inputs: []
    output: workspace/artifacts/quiet/note.md
    publish_hint: fixture only.
""",
    encoding="utf-8",
)

(TMP_ROOT / "playbooks" / "bad.yaml").write_text(
    DEMO_YAML.replace("venture: demo", "venture: mismatched"), encoding="utf-8"
)


def gen_calls(name):
    p = TMP_ROOT / name
    return len(p.read_text()) if p.exists() else 0


def manifest():
    p = TMP_ROOT / "workspace" / "artifacts" / "demo" / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (a)/(b) Schema validation, pure function level.
# ---------------------------------------------------------------------------
def base_doc(**over):
    doc = {
        "schema_version": 1,
        "venture": "demo",
        "description": "d",
        "cadence": "on-demand",
        "artifacts": [
            {
                "id": "a",
                "generator": "g",
                "inputs": [],
                "output": "workspace/artifacts/demo/a.md",
                "publish_hint": "h",
            }
        ],
    }
    doc.update(over)
    return doc


check("valid minimal playbook passes validation",
      pb.validate_playbook(base_doc(), "demo") == [],
      str(pb.validate_playbook(base_doc(), "demo")))
check("venture/filename mismatch is rejected",
      pb.validate_playbook(base_doc(venture="other"), "demo") != [])
check("schema_version 2 is rejected",
      pb.validate_playbook(base_doc(schema_version=2), "demo") != [])
check("unknown cadence is rejected",
      pb.validate_playbook(base_doc(cadence="hourly"), "demo") != [])


def with_output(path):
    doc = base_doc()
    doc["artifacts"][0]["output"] = path
    return pb.validate_playbook(doc, "demo")


check("reserved segment `data` in an output path is rejected",
      with_output("workspace/artifacts/demo/data/x.json") != [])
check("gitignored basename candidate.json is rejected",
      with_output("workspace/artifacts/demo/candidate.json") != [])
check("output outside workspace/artifacts/<venture>/ is rejected",
      with_output("tasks/artifacts/x.md") != [])
check("another venture's namespace is rejected",
      with_output("workspace/artifacts/other/x.md") != [])
check("gitignored suffix *.log is rejected",
      with_output("workspace/artifacts/demo/a.log") != [])

_dup = base_doc()
_dup["artifacts"] = [_dup["artifacts"][0], dict(_dup["artifacts"][0])]
check("duplicate artifact ids are rejected", pb.validate_playbook(_dup, "demo") != [])
_badid = base_doc()
_badid["artifacts"][0]["id"] = "Bad_Id"
check("artifact id must match ^[a-z][a-z0-9-]*$",
      pb.validate_playbook(_badid, "demo") != [])

# ---------------------------------------------------------------------------
# (h) --dry-run first, before anything exists: writes NOTHING.
# ---------------------------------------------------------------------------
rc, out = run_cli("run", "demo", "--dry-run")
check("dry-run exits 0", rc == 0, f"rc={rc}\n{out}")
check("dry-run reports would-write for runnable artifacts",
      out.count("[would-write]") == 3, out)
check("dry-run reports would-skip for missing input and missing generator",
      out.count("[would-skip]") == 2, out)
check("dry-run writes nothing — no workspace/ created",
      not (TMP_ROOT / "workspace").exists())
check("dry-run never calls a generator",
      gen_calls("calls_stub_gen.txt") == 0
      and gen_calls("calls_stub_const.txt") == 0)

# ---------------------------------------------------------------------------
# (c)/(f)/(g) First real run: writes, skips, manifest.
# ---------------------------------------------------------------------------
rc, out = run_cli("run", "demo")
check("run exits 0 when skips but no errors occur", rc == 0, f"rc={rc}\n{out}")
OUT_MD = TMP_ROOT / "workspace" / "artifacts" / "demo" / "out.md"
check("demo-card output written with generator content",
      OUT_MD.is_file() and OUT_MD.read_text().endswith("alpha\n"),
      OUT_MD.read_text() if OUT_MD.is_file() else "absent")
check("required-missing input -> skipped-missing-input, no output written",
      "[skipped-missing-input]" in out
      and not (TMP_ROOT / "workspace/artifacts/demo/missing.md").exists(), out)
check("absent generator module -> skipped-missing-generator, no output written",
      "[skipped-missing-generator]" in out
      and not (TMP_ROOT / "workspace/artifacts/demo/nogen.md").exists(), out)

m = manifest()
check("manifest carries the engine identity fields",
      m.get("generated_by") == "scripts/business/playbook.py"
      and m.get("schema_version") == 1 and m.get("venture") == "demo", str(m)[:200])
_card = m["artifacts"]["demo-card"]
check("manifest records the real input sha256",
      _card["sources"] == [{"path": "seed/notes.txt", "sha256": sha(NOTES),
                            "required": True}], str(_card["sources"]))
check("manifest records the real output sha256",
      _card["outputs"] == [{"path": "workspace/artifacts/demo/out.md",
                            "sha256": sha(OUT_MD)}], str(_card["outputs"]))
check("statuses recorded per artifact",
      _card["status"] == "written"
      and m["artifacts"]["demo-missing"]["status"] == "skipped-missing-input"
      and m["artifacts"]["demo-nogen"]["status"] == "skipped-missing-generator")
check("markdown generator without PROVENANCE falls back to the documented default",
      _card["provenance"] == {"classification": "REAL",
                              "method": "deterministic recomputation from "
                                        "committed inputs"},
      str(_card["provenance"]))
check("JSON output's provenance block is read back into the manifest",
      m["artifacts"]["demo-json"]["provenance"]["classification"]
      == "HONEST-SYNTHETIC", str(m["artifacts"]["demo-json"]["provenance"]))
check("skipped artifacts record PLACEHOLDER provenance, never a generation claim",
      m["artifacts"]["demo-missing"]["provenance"]["classification"]
      == "PLACEHOLDER")
CALLS_AFTER_FIRST = gen_calls("calls_stub_gen.txt")
check("stub_gen invoked exactly once on first run (skips never dispatch)",
      CALLS_AFTER_FIRST == 1, str(CALLS_AFTER_FIRST))

# ---------------------------------------------------------------------------
# (d)/(j) Idempotency: fast path and content path.
# ---------------------------------------------------------------------------
rc, out = run_cli("run", "demo")
check("second run exits 0", rc == 0)
check("unchanged inputs -> fast path, generator NOT invoked again",
      "[unchanged]" in out and gen_calls("calls_stub_gen.txt") == 1,
      f"calls={gen_calls('calls_stub_gen.txt')}\n{out}")
check("zero-input artifact regenerates byte-identical -> unchanged (content path)",
      manifest()["artifacts"]["demo-const"]["status"] == "unchanged"
      and gen_calls("calls_stub_const.txt") == 2,
      f"calls={gen_calls('calls_stub_const.txt')}")

# ---------------------------------------------------------------------------
# (e) Edited input -> written again with the new hash.
# ---------------------------------------------------------------------------
NOTES.write_text("alpha\nbeta\n", encoding="utf-8")
rc, out = run_cli("run", "demo", "--artifact", "demo-card")
check("edited input -> status written again", rc == 0 and "[written]" in out, out)
check("manifest sha256 tracks the edited input",
      manifest()["artifacts"]["demo-card"]["sources"][0]["sha256"] == sha(NOTES))
check("--artifact leaves the other manifest entries in place",
      manifest()["artifacts"]["demo-const"]["status"] == "unchanged")

# ---------------------------------------------------------------------------
# Generator-raised FileNotFoundError / errors / basename contract.
# ---------------------------------------------------------------------------
(TMP_ROOT / "raise_fnf.flag").touch()
NOTES.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
rc, out = run_cli("run", "demo", "--artifact", "demo-card")
check("generator FileNotFoundError -> skipped-missing-input, exit 0",
      rc == 0 and "[skipped-missing-input]" in out, f"rc={rc}\n{out}")
(TMP_ROOT / "raise_fnf.flag").unlink()

(TMP_ROOT / "raise_err.flag").touch()
NOTES.write_text("delta\n", encoding="utf-8")
rc, out = run_cli("run", "demo", "--artifact", "demo-card")
check("generator exception -> status error and nonzero exit",
      rc == 1 and "[error]" in out, f"rc={rc}\n{out}")
(TMP_ROOT / "raise_err.flag").unlink()

(TMP_ROOT / "wrong_keys.flag").touch()
NOTES.write_text("epsilon\n", encoding="utf-8")
rc, out = run_cli("run", "demo", "--artifact", "demo-card")
check("returned basenames not covering declared outputs -> error",
      rc == 1 and "[error]" in out and "declares" in out, f"rc={rc}\n{out}")
(TMP_ROOT / "wrong_keys.flag").unlink()

rc, out = run_cli("run", "demo", "--artifact", "demo-card")
check("recovery run after errors writes again", rc == 0 and "[written]" in out, out)

# ---------------------------------------------------------------------------
# (i) status, table and --json.
# ---------------------------------------------------------------------------
rc, out = run_cli("status", "--json")
payload = json.loads(out)
check("status --json exits 0 and is parseable", rc == 0)
check("status --json reflects the manifest statuses",
      payload["ventures"]["demo"]["artifacts"]["demo-card"]["status"] == "written"
      and payload["ventures"]["demo"]["artifacts"]["demo-const"]["status"]
      == "unchanged", str(payload)[:300])
check("a never-run venture reports no runs recorded, never invented",
      payload["ventures"]["quiet"] == {"note": "no runs recorded"})
rc, out = run_cli("status")
check("status table lists demo rows and the no-runs venture",
      rc == 0 and "demo-card" in out and "no runs recorded" in out, out)

# ---------------------------------------------------------------------------
# CLI-level validation failure and bad addressing.
# ---------------------------------------------------------------------------
rc, out = run_cli("run", "bad")
check("venture/filename mismatch fails the run with a FAIL line",
      rc == 1 and "FAIL" in out, f"rc={rc}\n{out}")
rc, out = run_cli("run", "demo", "--artifact", "nope")
check("unknown --artifact id fails", rc == 1 and "FAIL" in out)
rc, out = run_cli("run", "ghost-venture")
check("missing playbook file fails with a FAIL line", rc == 1 and "FAIL" in out)
rc, out = run_cli("list")
check("list names every playbook", rc == 0 and "demo" in out and "quiet" in out, out)

# ---------------------------------------------------------------------------
# The four REAL playbooks, schema-validated statically (read-only, no
# generator dispatch — independent of the generator lanes landing).
# ---------------------------------------------------------------------------
real = sorted((REPO / "playbooks").glob("*.yaml"))
check("exactly the four shipped ventures exist",
      [p.stem for p in real] == ["monitor", "ops", "research", "validation"],
      str([p.stem for p in real]))
for path in real:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    errs = pb.validate_playbook(doc, path.stem)
    check(f"real playbook {path.stem}.yaml passes schema validation",
          errs == [], str(errs))

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
