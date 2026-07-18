# Solo personal project, no connection to employer, built with public/free-tier only
"""CodeActSandbox (spec 13 T13C.1) acceptance tests.

Covers the spec's five accept criteria:
  (a) persistent namespace across turns
  (b) infinite loop / fork bomb killed at the wall cap; episode continues with an error obs
  (c) socket open / write-outside-scratch fail and are reported, not silently allowed
  (d) same (seed, tools, program) replays byte-identical Observations
  (e) no fabricated Observations — every field comes from real execution
"""
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ava.rl.codeact_sandbox import Observation, Sandbox  # noqa: E402

POSIX = os.name == "posix"


class TestNamespacePersistence:
    def test_value_set_then_read_across_steps(self):
        with Sandbox() as vm:
            assert vm.step("x = 40").ok
            assert vm.step("y = 2").ok
            obs = vm.step("x + y")            # last expression → value captured
            assert obs.ok and obs.value == "42"

    def test_stdout_captured(self):
        with Sandbox() as vm:
            obs = vm.step("print('hello'); 1 + 1")
            assert obs.stdout.strip() == "hello" and obs.value == "2"

    def test_error_reported_not_raised_and_vm_survives(self):
        with Sandbox() as vm:
            obs = vm.step("1/0")
            assert not obs.ok and "ZeroDivisionError" in obs.error
            assert vm.alive
            assert vm.step("7 * 6").value == "42"   # namespace intact after a caught error


class TestTools:
    def test_source_tool_bound_and_call_recorded(self):
        vm = Sandbox(tool_sources={"add": "def add(a, b):\n    return a + b"})
        try:
            obs = vm.step("add(2, 3)")
            assert obs.value == "5"
            assert obs.tool_calls and obs.tool_calls[0]["tool"] == "add"
            assert obs.tool_calls[0]["args"] == ["2", "3"]
        finally:
            vm.close()

    def test_frozen_clock_tool(self):
        with Sandbox(freeze_epoch=1234.0) as vm:
            assert vm.step("get_clock()").value == "1234.0"

    def test_non_importable_callable_rejected(self):
        with pytest.raises(ValueError, match="not importable"):
            Sandbox(tools={"f": lambda x: x})


@pytest.mark.skipif(not POSIX, reason="hard wall/resource caps require POSIX")
class TestIsolation:
    def test_infinite_loop_killed_and_episode_continues(self):
        vm = Sandbox(timeout_s=1.0)
        try:
            t0 = time.monotonic()
            obs = vm.step("while True:\n    pass")
            elapsed = time.monotonic() - t0
            assert not obs.ok and "timed out" in obs.error
            assert elapsed < 5.0            # actually killed, did not hang
            assert not vm.alive
            follow = vm.step("1 + 1")       # episode continues with an error obs, no hang
            assert not follow.ok and "not alive" in follow.error
        finally:
            vm.close()

    def test_fork_bomb_contained(self):
        vm = Sandbox(timeout_s=2.0)
        try:
            obs = vm.step("import os\nwhile True:\n    os.fork()")
            # os.fork is blocked (PermissionError) or the wall cap kills the group — either way
            # the call must return, not take down the host.
            assert not obs.ok
        finally:
            vm.close()

    def test_socket_open_blocked_and_reported(self):
        with Sandbox() as vm:
            obs = vm.step("import socket\nsocket.socket()")
            assert not obs.ok and ("blocked" in obs.error or "PermissionError" in obs.error)

    def test_write_outside_scratch_blocked(self):
        with Sandbox() as vm:
            obs = vm.step("open('/tmp/codeact_escape_probe.txt', 'w').write('x')")
            assert not obs.ok and ("blocked" in obs.error or "PermissionError" in obs.error)
            assert not os.path.exists("/tmp/codeact_escape_probe.txt")

    def test_write_inside_scratch_allowed(self):
        with Sandbox() as vm:
            obs = vm.step("open('note.txt', 'w').write('ok')")   # cwd is the scratch dir
            assert obs.ok
            assert (Path(vm.scratch_dir) / "note.txt").read_text() == "ok"

    def test_write_outside_scratch_blocked_via_all_open_paths(self):
        # builtins.open, io.open, os.open, and pathlib must ALL be guarded (not just builtins.open).
        probes = {
            "builtins": "open('/tmp/codeact_escape_b.txt','w').write('x')",
            "io": "import io\nio.open('/tmp/codeact_escape_io.txt','w').write('x')",
            "os": "import os\nfd=os.open('/tmp/codeact_escape_os.txt', os.O_WRONLY|os.O_CREAT, 0o644)",
            "pathlib": "import pathlib\npathlib.Path('/tmp/codeact_escape_pl.txt').write_text('x')",
        }
        with Sandbox() as vm:
            for name, code in probes.items():
                obs = vm.step(code)
                assert not obs.ok and ("blocked" in obs.error or "PermissionError" in obs.error), \
                    f"{name} path not blocked: {obs.error}"
        for suffix in ("b", "io", "os", "pl"):
            assert not os.path.exists(f"/tmp/codeact_escape_{suffix}.txt")

    def test_raw_fd1_write_cannot_corrupt_protocol(self):
        # A step that writes a huge newline-less chunk to raw fd 1 must NOT desync the protocol or
        # hang the wall cap: fd 1 is repointed at /dev/null, so the VM stays usable.
        with Sandbox(timeout_s=2.0) as vm:
            obs = vm.step("import os\nos.write(1, b'x' * 200000)\n123")
            assert obs.ok and obs.value == "123"   # protocol intact, value still returned
            assert vm.step("7 * 6").value == "42"

    def test_wall_cap_enforced_on_slow_line(self):
        # Regression for the select()+readline() bug: a busy-loop after a big fd-1 write must still
        # be killed at the wall cap (previously readline() could block unbounded).
        import time as _t
        with Sandbox(timeout_s=1.0) as vm:
            t0 = _t.monotonic()
            obs = vm.step("import os\nos.write(1, b'y'*100000)\nwhile True:\n    pass")
            assert not obs.ok and "timed out" in obs.error
            assert _t.monotonic() - t0 < 5.0


class TestDeterminism:
    def _run(self):
        with Sandbox(seed=7) as vm:
            obs = []
            obs.append(vm.step("import random\nrandom.seed(get_clock())\n[random.random() for _ in range(3)]"))
            obs.append(vm.step("sorted({'b','a','c','z','m'})"))
            obs.append(vm.step("d = {i: i*i for i in range(5)}\nrepr(d)"))
            return [(o.value, o.stdout, o.error) for o in obs]

    def test_byte_identical_replay(self):
        assert self._run() == self._run()   # same seed+program → identical observations


class TestStepCap:
    def test_max_steps_enforced(self):
        with Sandbox(max_steps=2) as vm:
            assert vm.step("1").ok
            assert vm.step("2").ok
            capped = vm.step("3")
            assert not capped.ok and "max_steps" in capped.error


class TestNoFabrication:
    def test_observation_fields_are_real(self):
        # A no-op statement yields empty stdout, no value, no error, and a measured wall time.
        with Sandbox() as vm:
            obs = vm.step("pass")
            assert obs.stdout == "" and obs.value is None and obs.error is None
            assert isinstance(obs.wall_ms, float) and obs.wall_ms >= 0.0
            assert obs.tool_calls == []
