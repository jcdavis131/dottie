"""Tests for scripts/publish-release.sh: best-value awk + missing-results guard."""

import re
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "publish-release.sh"

HEADER = "commit\tval_bpb\tmemory_gb\tstatus\tdescription"


def _extract_best_line():
    """Pull the real BEST=$(awk ...) line out of the script so the test exercises
    the exact code that ships."""
    text = SCRIPT.read_text()
    match = re.search(r"^BEST=\$\(awk .*$", text, re.M)
    assert match, "BEST awk line not found in publish-release.sh"
    return match.group(0)


def _run_best(tmp_path):
    cmd = _extract_best_line() + '\necho "$BEST"'
    proc = subprocess.run(
        ["bash", "-c", cmd], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_awk_selects_minimum_val_bpb(tmp_path):
    rows = [
        "c1\t1.0500\t10.1\tkeep\tfirst",
        "c2\t0.9812\t11.0\tkeep\tbest",
        "c3\t1.1000\t12.2\tkeep\tworst",
    ]
    (tmp_path / "results.tsv").write_text("\n".join([HEADER] + rows) + "\n")
    assert float(_run_best(tmp_path)) == 0.9812


def test_awk_min_when_best_row_is_first(tmp_path):
    rows = ["c1\t0.9000\t10\tkeep\ta", "c2\t0.9500\t10\tkeep\tb"]
    (tmp_path / "results.tsv").write_text("\n".join([HEADER] + rows) + "\n")
    assert float(_run_best(tmp_path)) == 0.9


def test_awk_missing_file_reports_unknown(tmp_path):
    assert _run_best(tmp_path) == "unknown"


def _stub_bin(tmp_path):
    """Fake gh/git so the full script can run without network or a git repo."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/usr/bin/env bash\necho \"gh-stub $*\"\nexit 0\n")
    git = bin_dir / "git"
    git.write_text("#!/usr/bin/env bash\necho abc1234\nexit 0\n")
    for f in (gh, git):
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _script_copy(tmp_path):
    """Copy the script into a temp repo layout so its `cd ROOT` lands in tmp."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    dst = scripts_dir / "publish-release.sh"
    shutil.copy(SCRIPT, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
    return dst


def _run_script(tmp_path, *args, env_path):
    import os

    env = dict(os.environ)
    env["PATH"] = f"{env_path}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(_script_copy(tmp_path)), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )


def test_script_errors_without_results_tsv(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    proc = _run_script(tmp_path, "programs/program-ava.md", "v0.6.0-test", env_path=bin_dir)
    assert proc.returncode == 1
    assert "no results.tsv" in proc.stderr
    assert not (tmp_path / "results.tsv").exists()


def test_script_demo_flag_creates_demo_tagged_row(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    proc = _run_script(tmp_path, "programs/program-ava.md", "v0.6.0-test", "--demo", env_path=bin_dir)
    assert proc.returncode == 0, proc.stderr
    tsv = (tmp_path / "results.tsv").read_text().strip().splitlines()
    assert tsv[0] == HEADER
    assert "\tdemo\t" in tsv[1]  # status column is 'demo', not 'keep'


def test_script_real_results_publishes_min(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    rows = ["c1\t1.0500\t10\tkeep\ta", "c2\t0.9812\t11\tkeep\tb"]
    (tmp_path / "results.tsv").write_text("\n".join([HEADER] + rows) + "\n")
    proc = _run_script(tmp_path, "programs/program-ava.md", "v0.6.0-test", env_path=bin_dir)
    assert proc.returncode == 0, proc.stderr
    assert "Best: 0.9812" in proc.stdout
