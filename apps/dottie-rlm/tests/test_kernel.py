"""PersistentKernel: the namespace must persist, and a timeout must not lie."""

from __future__ import annotations

import pytest
from dottie_rlm.kernel import ExecResult, KernelError, PersistentKernel


def test_namespace_persists_across_run_calls() -> None:
    """The whole point of the design: state built in step 1 is live in step 9."""
    k = PersistentKernel()
    assert k.run("x = 41").error is None
    r = k.run("x + 1")
    assert r.error is None
    assert r.result_repr == "42"
    assert k.run("print('x is', x)").stdout.strip() == "x is 41"


def test_two_kernels_do_not_share_state() -> None:
    """InteractiveShell is a singleton; sharing user_ns would let one session
    wipe another's namespace. Each kernel keeps its own dict."""
    a, b = PersistentKernel(), PersistentKernel()
    a.run("marker_from_a = 1")
    assert b.run("'marker_from_a' in dir()").result_repr == "False"


def test_exception_is_captured_not_raised() -> None:
    k = PersistentKernel()
    r = k.run("1 / 0")
    assert r.error is not None
    assert "ZeroDivisionError" in r.error


def test_syntax_error_reports_actionably() -> None:
    k = PersistentKernel()
    r = k.run("def broken(:\n    pass")
    assert r.error is not None
    assert "SyntaxError" in r.error or "invalid syntax" in r.error.lower()


def test_stdout_and_stderr_are_both_captured() -> None:
    k = PersistentKernel()
    r = k.run("import sys\nprint('to out')\nprint('to err', file=sys.stderr)")
    assert "to out" in r.stdout
    assert "to err" in r.stderr


def test_output_is_truncated_with_an_explicit_marker() -> None:
    k = PersistentKernel(max_capture_chars=500)
    r = k.run("print('z' * 5000)")
    assert len(r.stdout) < 5000
    assert "truncated" in r.stdout
    assert "chars" in r.stdout


def test_timeout_interrupts_a_pure_python_loop() -> None:
    k = PersistentKernel()
    r = k.run("while True:\n    pass", timeout_s=1.0)
    assert r.timed_out is True
    assert r.error is not None and "TimeoutError" in r.error
    # A pure-Python loop yields to the async exception, so the kernel survives.
    assert k.wedged is False
    assert k.run("2 + 2").result_repr == "4"


def test_inject_installs_callables_and_validates_the_name() -> None:
    k = PersistentKernel()
    k.inject("answer", lambda: 42)
    assert k.run("answer()").result_repr == "42"
    with pytest.raises(KernelError):
        k.inject("not an identifier", lambda: None)


def test_non_string_code_is_refused_as_a_result_not_a_raise() -> None:
    k = PersistentKernel()
    r = k.run(None)  # type: ignore[arg-type]
    assert r.error is not None and "must be a string" in r.error


def test_exec_count_and_as_dict_shape() -> None:
    k = PersistentKernel()
    k.run("1")
    k.run("2")
    assert k.exec_count == 2
    d = ExecResult(stdout="a", error=None).as_dict()
    assert set(d) == {"stdout", "stderr", "result_repr", "error", "duration_s", "timed_out"}


def test_a_wedged_kernel_refuses_further_work_instead_of_pretending() -> None:
    k = PersistentKernel()
    k.wedged = True
    r = k.run("1 + 1")
    assert r.error is not None and "KernelWedged" in r.error
