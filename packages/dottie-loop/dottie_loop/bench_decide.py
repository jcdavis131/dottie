"""Decision-latency bench: how long does Dottie take to decide a tier?

``dottie-loop bench decide`` (and ``scout router bench``) run this. Every number
it prints is measured on the box it runs on; nothing is estimated. Scenarios:

``scout_cold_route``
    ``python -m bigbang.cli --json route <goal>`` as a fresh subprocess, forced
    in-process (``SCOUT_DECIDE_REMOTE=0``): interpreter start + scout import +
    one route. This is what a shell user pays without jarvisd.
``inprocess_route``
    :func:`dottie_loop.router.route_goal` with no advisory backends, no trace.
``inprocess_decide_context``
    :func:`dottie_loop.decide.decide` with the run-history provider over a
    seeded timeline store (context build + route).
``jarvisd_warm_route`` / ``jarvisd_warm_decide`` / ``jarvisd_warm_decide_context``
    A jarvisd app served by uvicorn on a free loopback port with a throwaway
    SQLite DB seeded with memories and goals, hit over one keep-alive
    connection: ``POST /api/route`` (the alias), ``POST /api/decide`` with
    ``context: false`` and with the default context. A server without
    ``/api/decide`` reports those rows as unavailable.
``jarvisd_warm_decide_system_one``
    The same ``/api/decide`` (with context) while ``DOTTIE_OS_URL`` points at a
    local untrained ``serve_decide``: the full decision path including the
    System One round trip (HTTP only; an untrained server runs no model).
``run_history_stats``
    scout's ``g_history_stats`` (what every ``runner.build_plan`` calls) over a
    seeded store of 400 runs, warm process.
``system_one_untrained``
    The System One backend against a local ``apps/jev-v0/serve_decide.py``
    server with no checkpoint (``mode=untrained``): the HTTP path only, not a
    model's forward pass.

Nothing here writes real state: traces are off, jarvisd uses a temp DB, the
run-history store is a temp directory. Stdlib only; jarvisd/uvicorn and scout
scenarios are skipped (with a reason) when they are not importable.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

GOALS = (
    "compare Stripe vs Lemon Squeezy Aug 2026 with 5-7 sources",
    "heartbeat check on the tailnet",
    "ship the daemon end-to-end then write the release notes",
    "summarise my open goals",
)
SCENARIOS = (
    "scout_cold_route",
    "inprocess_route",
    "inprocess_decide_context",
    "jarvisd_warm_route",
    "jarvisd_warm_decide",
    "jarvisd_warm_decide_context",
    "jarvisd_warm_decide_system_one",
    "system_one_untrained",
    "run_history_stats",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def percentile(samples: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty sample."""
    s = sorted(samples)
    k = max(0, min(len(s) - 1, math.ceil(q / 100.0 * len(s)) - 1))
    return s[k]


def summarize(name: str, samples: list[float], note: str = "") -> dict[str, Any]:
    if not samples:
        return {"scenario": name, "available": False, "n": 0, "note": note}
    return {
        "scenario": name,
        "available": True,
        "n": len(samples),
        "p50_ms": round(percentile(samples, 50), 3),
        "p95_ms": round(percentile(samples, 95), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
        "note": note,
    }


def _time(fn: Callable[[], Any], n: int, warmup: int = 3) -> list[float]:
    for _ in range(warmup):
        fn()
    out: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return out


@contextlib.contextmanager
def _env(**kv: str | None) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _seed_history(base: Path, runs: int = 40) -> None:
    """A realistic run-history store: ``runs`` runs x 5 nodes, some failures."""
    roles = ("strategist", "planner", "executor", "builder", "critic")
    for r in range(runs):
        d = base / f"run-{r:04d}"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "timeline.jsonl").open("w", encoding="utf-8") as f:
            for i, role in enumerate(roles):
                failed = (r + i) % 7 == 0
                f.write(json.dumps({
                    "nodeId": f"n{i}", "agentId": role, "attempt": 1, "latency": 3.0 + i,
                    "tier": ("llm", "deep_research", "agentic_epic")[r % 3], "executor": "stub",
                    "tokens": 0, "status": "fail" if failed else "ok",
                    "errorClass": "TOOL_FAILURE" if failed else "none",
                }) + "\n")


# --- scenarios -------------------------------------------------------------


def bench_scout_cold(n: int) -> dict[str, Any]:
    name = "scout_cold_route"
    try:
        import bigbang  # noqa: F401  availability probe only
    except ImportError as exc:
        return summarize(name, [], f"scout not importable: {exc}")
    env = {**os.environ, "DOTTIE_TRACES": "0", "SCOUT_DECIDE_REMOTE": "0"}
    env.pop("DOTTIE_OS_URL", None)
    samples: list[float] = []
    for i in range(n):
        t0 = time.perf_counter()
        r = subprocess.run(
            [sys.executable, "-m", "bigbang.cli", "--json", "route", GOALS[i % len(GOALS)]],
            capture_output=True, text=True, env=env, timeout=60, check=False,
        )
        dt = (time.perf_counter() - t0) * 1000.0
        if r.returncode != 0:
            return summarize(name, [], f"exit {r.returncode}: {r.stderr.strip()[-200:]}")
        samples.append(dt)
    return summarize(name, samples, "fresh interpreter per sample; SCOUT_DECIDE_REMOTE=0")


def bench_inprocess_route(n: int) -> dict[str, Any]:
    from dottie_loop.router import route_goal

    i = iter(range(10**9))
    samples = _time(lambda: route_goal(GOALS[next(i) % len(GOALS)], backends=[], trace=False), n)
    return summarize("inprocess_route", samples, "heuristic only, no trace")


def bench_inprocess_decide_context(n: int, history_dir: Path) -> dict[str, Any]:
    name = "inprocess_decide_context"
    try:
        from dottie_loop.context import RunHistoryProvider
        from dottie_loop.decide import decide
    except ImportError as exc:
        return summarize(name, [], f"decision plane not present: {exc}")
    providers = [RunHistoryProvider(base=history_dir)]
    i = iter(range(10**9))
    samples = _time(
        lambda: decide(GOALS[next(i) % len(GOALS)], providers=providers, backends=[], trace=False, cache=None), n
    )
    return summarize(name, samples, "run-history provider over 40 seeded runs; no cache")


class _Server:
    """Run an ASGI app under uvicorn on a thread; stop on exit."""

    def __init__(self, app: Any, port: int) -> None:
        import uvicorn

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        deadline = time.time() + 15
        while not self.server.started and time.time() < deadline:
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _post(conn: http.client.HTTPConnection, path: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    raw = json.dumps(body).encode("utf-8")
    conn.request("POST", path, body=raw, headers={**headers, "Content-Type": "application/json", "Content-Length": str(len(raw))})
    resp = conn.getresponse()
    data = resp.read()
    try:
        doc = json.loads(data.decode("utf-8")) if data else {}
    except ValueError:
        doc = {}
    return resp.status, doc


def _start_untrained_sidecar() -> tuple[Any, str] | None:
    """A local jev-v0 serve_decide in mode=untrained, or None when it is not in this checkout."""
    jev = _repo_root() / "apps" / "jev-v0"
    if not (jev / "serve_decide.py").is_file():
        return None
    if str(jev) not in sys.path:
        sys.path.insert(0, str(jev))
    try:
        import serve_decide  # type: ignore[import-not-found]
    except Exception:
        return None
    server = serve_decide.DecideServer("127.0.0.1", _free_port(), model="bench-untrained", mode="untrained")
    server.RequestHandlerClass.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def bench_jarvisd(n: int, tmp: Path, history_dir: Path) -> list[dict[str, Any]]:
    names = ("jarvisd_warm_route", "jarvisd_warm_decide", "jarvisd_warm_decide_context", "jarvisd_warm_decide_system_one")
    try:
        import uvicorn  # noqa: F401  availability probe only

        from jarvisd.app import build_app
        from jarvisd.config import Config
        from jarvisd.state import State
    except ImportError as exc:
        return [summarize(x, [], f"jarvisd not importable: {exc}") for x in names]
    db = tmp / "jarvis.db"
    state = State(db)
    for k in range(300):
        state.remember("bench", "global", f"note {k}: stripe invoices and heartbeat checks for run {k % 17}", ["bench"])
    for k in range(20):
        state.add_goal("bench", "dottie", f"open goal {k}: ship the daemon part {k}")
    bearer = "bench-" + os.urandom(8).hex()
    port = _free_port()
    config = Config(host="127.0.0.1", port=port, db_path=db, bearer=bearer, workspace=tmp / "ws",
                    rate_ip=10**6, rate_key=10**6, rate_agent=10**6)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    out: list[dict[str, Any]] = []
    headers = {"Authorization": f"Bearer {bearer}", "X-Agent-Id": "bench"}
    with _env(SCOUT_CHECKPOINT_BASE=str(history_dir)), _Server(build_app(config, state=state), port):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        i = iter(range(10**9))

        def call(path: str, extra: dict[str, Any]) -> Callable[[], None]:
            def _do() -> None:
                status, doc = _post(conn, path, {"goal": GOALS[next(i) % len(GOALS)], **extra}, headers)
                if status == 404:
                    raise LookupError(path)
                if status != 200 or not doc.get("ok", False):
                    raise RuntimeError(f"{path} -> {status} {str(doc)[:200]}")
            return _do

        for name, path, extra in (
            (names[0], "/api/route", {}),
            (names[1], "/api/decide", {"context": False, "cache": False}),
            (names[2], "/api/decide", {"cache": False}),
        ):
            try:
                out.append(summarize(name, _time(call(path, extra), n), "one keep-alive connection; 300 memories, 20 goals seeded"))
            except LookupError:
                out.append(summarize(name, [], f"{path} not served by this jarvisd"))
            except Exception as exc:
                out.append(summarize(name, [], f"error: {type(exc).__name__}: {exc}"))
        sidecar = _start_untrained_sidecar()
        if sidecar is None:
            out.append(summarize(names[3], [], "apps/jev-v0/serve_decide.py not available"))
        else:
            server, url = sidecar
            try:
                with _env(DOTTIE_OS_URL=url):
                    out.append(summarize(names[3], _time(call("/api/decide", {"cache": False}), n),
                                         "decide + context + System One /decide on a local untrained serve_decide"))
            except Exception as exc:
                out.append(summarize(names[3], [], f"error: {type(exc).__name__}: {exc}"))
            finally:
                server.shutdown()
                server.server_close()
        conn.close()
    state.close()
    return out


def bench_system_one(n: int) -> dict[str, Any]:
    name = "system_one_untrained"
    jev = _repo_root() / "apps" / "jev-v0"
    if not (jev / "serve_decide.py").is_file():
        return summarize(name, [], "apps/jev-v0/serve_decide.py not found")
    if str(jev) not in sys.path:
        sys.path.insert(0, str(jev))
    try:
        import serve_decide  # type: ignore[import-not-found]
    except Exception as exc:
        return summarize(name, [], f"serve_decide not importable: {exc}")
    from dottie_loop.backends import SystemOneBackend

    port = _free_port()
    server = serve_decide.DecideServer("127.0.0.1", port, model="bench-untrained", mode="untrained")
    server.RequestHandlerClass.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        backend = SystemOneBackend(url=f"http://127.0.0.1:{port}")
        i = iter(range(10**9))

        def _do() -> None:
            ans = backend.answer(GOALS[next(i) % len(GOALS)])
            if not ans.get("available"):
                raise RuntimeError(ans.get("reason"))

        samples = _time(_do, n)
    except Exception as exc:
        return summarize(name, [], f"error: {type(exc).__name__}: {exc}")
    finally:
        server.shutdown()
        server.server_close()
    return summarize(name, samples, "local serve_decide, mode=untrained (HTTP path, no forward pass)")


def bench_history_stats(n: int, tmp: Path) -> dict[str, Any]:
    name = "run_history_stats"
    try:
        from bigbang.plugins.harness.timeline import g_history_stats
    except ImportError as exc:
        return summarize(name, [], f"scout not importable: {exc}")
    base = tmp / "history-400"
    _seed_history(base, runs=400)
    return summarize(name, _time(lambda: g_history_stats(base), n), "400 runs x 5 events, warm process")


def run(n: int = 50, cold_n: int = 10, scenarios: tuple[str, ...] = SCENARIOS) -> dict[str, Any]:
    """Run the selected scenarios; returns ``{"results": [...], "env": {...}}``."""
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="dottie-bench-") as td:
        tmp = Path(td)
        history = tmp / "checkpoints"
        _seed_history(history)
        with _env(DOTTIE_TRACES="0", DOTTIE_OS_URL=None, DOTTIE_TRACE_TEXT=None):
            if "scout_cold_route" in scenarios:
                results.append(bench_scout_cold(cold_n))
            if "inprocess_route" in scenarios:
                results.append(bench_inprocess_route(n))
            if "inprocess_decide_context" in scenarios:
                results.append(bench_inprocess_decide_context(n, history))
            if any(s.startswith("jarvisd_") for s in scenarios):
                results.extend(r for r in bench_jarvisd(n, tmp, history) if r["scenario"] in scenarios)
            if "run_history_stats" in scenarios:
                results.append(bench_history_stats(n, tmp))
            if "system_one_untrained" in scenarios:
                results.append(bench_system_one(n))
    return {
        "results": results,
        "env": {"python": sys.version.split()[0], "platform": sys.platform, "cpus": os.cpu_count(), "n": n, "cold_n": cold_n},
    }


def format_table(report: dict[str, Any]) -> str:
    lines = [f"{'scenario':32} {'n':>4} {'p50 ms':>10} {'p95 ms':>10}  note"]
    for r in report["results"]:
        if r["available"]:
            lines.append(f"{r['scenario']:32} {r['n']:>4} {r['p50_ms']:>10.3f} {r['p95_ms']:>10.3f}  {r['note']}")
        else:
            lines.append(f"{r['scenario']:32} {'-':>4} {'-':>10} {'-':>10}  unavailable: {r['note']}")
    e = report["env"]
    lines.append(f"python {e['python']} on {e['platform']}, {e['cpus']} cpus")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="dottie-loop bench decide", description=__doc__.split("\n\n")[0])
    p.add_argument("--n", type=int, default=50, help="samples per warm scenario")
    p.add_argument("--cold-n", type=int, default=10, help="samples for the subprocess scenario")
    p.add_argument("--only", action="append", choices=SCENARIOS, help="run only these scenarios")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    report = run(args.n, args.cold_n, tuple(args.only) if args.only else SCENARIOS)
    print(json.dumps(report, indent=2) if args.json else format_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
