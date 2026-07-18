# Solo personal project, no connection to employer, built with public/free-tier only
"""code-bench: exec_verify covers ok / timeout / nonzero-exit; real mode refuses honestly."""

from conftest import load_skill_module

cb = load_skill_module("code-bench")


class TestExecVerify:
    def test_ok_path(self):
        r = cb.exec_verify("print('hello-exec')")
        assert r["ok"] is True
        assert r["returncode"] == 0
        assert "hello-exec" in r["stdout"]

    def test_nonzero_exit(self):
        r = cb.exec_verify("import sys; sys.exit(3)")
        assert r["ok"] is False
        assert r["returncode"] == 3

    def test_exception_is_nonzero_exit_with_stderr(self):
        r = cb.exec_verify("raise RuntimeError('boom-marker')")
        assert r["ok"] is False
        assert r["returncode"] != 0
        assert "boom-marker" in r["stderr"]

    def test_timeout(self):
        r = cb.exec_verify("while True:\n    pass", timeout=1)
        assert r["ok"] is False
        assert "error" in r and "1" in r["error"]  # subprocess TimeoutExpired message


class TestRunModes:
    def test_mock_pass_rate_is_measured(self):
        r = cb.run(mode="mock")
        assert r["measured"]["pass_rate"] == 1.0  # both built-in tasks really execute
        assert all(t["ok"] for t in r["measured"]["results"])

    def test_real_mode_refuses_honestly(self):
        r = cb.run(mode="real")
        assert r["pass"] is False
        assert r["measured"] is None
        assert "not implemented" in r["error"]
