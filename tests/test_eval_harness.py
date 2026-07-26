
"""Tests for eval_harness — trivial module prints needle message"""
import importlib.util, subprocess, sys
MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/eval_harness.py"
# This file just prints at import time, so exec via subprocess for isolation
def test_eval_harness_import_does_not_crash():
    result = subprocess.run([sys.executable, MOD_PATH], capture_output=True, text=True, timeout=5)
    # It prints needle message; exit 0 unless error
    assert result.returncode == 0
    assert "Needle" in result.stdout or "needle" in result.stdout.lower() or result.stdout == "" or "128k" in result.stdout

def test_eval_harness_file_exists_and_small():
    import pathlib
    p = pathlib.Path(MOD_PATH)
    assert p.exists()
    assert p.stat().st_size < 5000
    content = p.read_text()
    assert "needle" in content.lower() or "128k" in content.lower()
