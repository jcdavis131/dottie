"""Skip test modules whose dependencies aren't in the current image.

The two images are deliberately disjoint: `ava/cpu` carries the data stack
(datasets, datasketch, zstandard, tokenizers) and no torch; `ava/gpu` carries
torch and no data stack. Neither is wrong -- a 2.5GB CUDA wheel has no business
in a collector container. So a module that imports what this image lacks is
skipped, not an error.

Running the full suite therefore means running it in BOTH images:
    make test        # cpu: pipeline
    make test-gpu    # gpu: model, losses, trainer
"""

from __future__ import annotations

import importlib.util
import os
import tempfile

# --- keep the suite out of the REAL telemetry ------------------------------
# Measured 2026-08-01: a full `pytest tests` run appended ~5 KB to the repo's own
# apps/ava-factory/reports/ava_telemetry.jsonl and rewrote dottie_telemetry.jsonl and
# dottie_live_status.json. Verified it was this suite and not a background writer, by
# re-checking the three files over 90 idle seconds afterwards: byte-identical, untouched.
#
# Mechanism: dottie/telemetry.py resolves TELEMETRY_DIR ONCE AT IMPORT TIME from
# DOTTIE_TELEMETRY_DIR / AVA_TELEMETRY_DIR, falling back to `<repo>/reports`. The suite
# never set either, so importing the module bound every telemetry path to the operator's
# live files and each run mixed test-generated records into real data.
#
# Same defect this repo already fixed in apps/scout-cli, where the suite wrote to the
# developer's real secrets vault and herd ledger, and the same remedy: redirect at
# conftest module scope. It MUST be here rather than in a fixture — the paths are
# module-level constants, so by the time any fixture runs the import has already happened
# and the constants are frozen. Set via os.environ, not monkeypatch, for the same reason
# scout-cli needed it that way: subprocesses inherit the environment, they cannot see
# monkeypatch.
#
# dottie/ is FROZEN (bind-mounted into the live trainer), so the fix goes in the test
# harness, not in telemetry.py. Nothing about production behaviour changes.
_TELEMETRY_TMP = tempfile.mkdtemp(prefix="ava-factory-test-telemetry-")
os.environ["DOTTIE_TELEMETRY_DIR"] = _TELEMETRY_TMP
os.environ["AVA_TELEMETRY_DIR"] = _TELEMETRY_TMP

_MODULE_REQUIREMENTS = {
    "test_model.py": ["torch"],
    "test_grow.py": ["torch"],
    "test_jlosses.py": ["torch"],
    "test_train_smoke.py": ["torch"],
    "test_eval_harness.py": ["torch"],
    "test_no_mock.py": [],
    # NOT "datasets": collector.py imports it LAZILY (inside the HF path, ~line 307), so the
    # test module imports and its 15 tests pass without it. Declaring it here silently
    # dropped all 15 from every full-suite run on any box without `datasets` -- including
    # this one -- with no skip line and no error, because pytest_ignore_collect is invisible
    # in the summary. The suite just reported a smaller number that still looked healthy
    # (470 instead of 485). Measured 2026-07-20, TODOS 5.3.R83.
    "test_collector.py": ["zstandard"],
    "test_curator.py": ["datasketch", "zstandard", "tokenizers"],
    "test_datagen.py": ["zstandard"],
    "test_tokenizer.py": ["tokenizers", "zstandard"],
    "test_data.py": ["numpy", "tokenizers", "yaml"],
    "test_manifest.py": [],
    "test_flow.py": ["yaml"],
}


def _missing(mods: list[str]) -> list[str]:
    return [m for m in mods if importlib.util.find_spec(m) is None]


def pytest_ignore_collect(collection_path, config):
    reqs = _MODULE_REQUIREMENTS.get(collection_path.name)
    if not reqs:
        return False
    return bool(_missing(reqs))


def pytest_report_header(config):  # noqa: ARG001
    """Say OUT LOUD which modules this image is skipping, and why.

    ``pytest_ignore_collect`` is invisible: an ignored module produces no skip line, no
    error, and no mention in the summary -- the collected count simply shrinks. A stale
    entry in the table above therefore reads exactly like a healthy run.

    That is not hypothetical. ``test_collector.py`` declared ``datasets``, which
    collector.py only imports lazily, so 15 real tests were dropped from every full-suite
    run on this box while it still reported a confident "470 passed" (TODOS 5.3.R83). It
    was found by diffing per-file collection against whole-suite collection -- not by
    anything the suite itself said.

    Computed from the table rather than recorded during collection, so it is independent of
    hook ordering and prints even when nothing is ignored.
    """
    lines = []
    for mod, reqs in sorted(_MODULE_REQUIREMENTS.items()):
        gone = _missing(reqs) if reqs else []
        if gone:
            lines.append(f"  {mod} - missing {', '.join(gone)}")
    if not lines:
        return "image deps: complete (no test modules ignored)"
    return "\n".join(
        [f"image deps: IGNORING {len(lines)} test module(s) - these tests DO NOT RUN here:"]
        + lines
        + ["  (run the other image too; see the module docstring)"]
    )


# ---------------------------------------------------------------------------
# httpx >= 0.28 compatibility for starlette 0.27's TestClient.
#
# All 21 tests in test_server_endpoints.py ERRORED at setup with
#     TypeError: Client.__init__() got an unexpected keyword argument 'app'
# since 2026-07-25. httpx 0.28 removed the `app=` shortcut; starlette 0.27's
# TestClient.__init__ still passes it:
#
#     super().__init__(app=self.app, base_url=..., headers=..., transport=transport,
#                      follow_redirects=True, cookies=cookies)
#
# WHY DROPPING `app` IS LOSSLESS, not a workaround that hides a problem. That call
# passes BOTH `app=` and `transport=_TestClientTransport(...)`. In httpx < 0.28,
# `app=` was only a shortcut for "build an ASGI transport for me"; when an explicit
# `transport=` was supplied it took precedence and `app` was never used for routing.
# starlette builds the real transport itself (verified in
# starlette.testclient.TestClient.__init__ at 0.27.0), so the transport does all the
# work and `app` was already dead weight before 0.28 removed it.
#
# WHY NOT THE TWO FIXES THE BOARD PROPOSED:
#   * `pip install 'httpx<0.28'` -- httpx is Required-by 17 packages here, including
#     anthropic, openai, mcp, litellm, chromadb, qdrant-client and scout-cli. This
#     box runs the live trainer. Downgrading a shared transport library to fix a test
#     harness is the most dangerous option on the list, not the cheapest.
#   * upgrade fastapi/starlette -- fastapi 0.104.1 pins starlette ~0.27, so starlette
#     cannot move alone, and moving both changes the library the live server runs on.
# Measured 2026-07-28: httpx 0.28.1, starlette 0.27.0, fastapi 0.104.1.
#
# Scope: applied at conftest import, so it affects the test session only. It is a
# no-op on httpx < 0.28 (the parameter is accepted there) and a no-op once
# starlette/fastapi are upgraded (they stop passing it).
try:  # pragma: no cover - import guard, httpx is optional in the cpu image
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None

if _httpx is not None and not getattr(_httpx.Client.__init__, "_ava_drops_app", False):
    import inspect as _inspect

    if "app" not in _inspect.signature(_httpx.Client.__init__).parameters:
        import functools as _functools

        _orig_client_init = _httpx.Client.__init__

        # functools.wraps sets __wrapped__, so inspect.signature() keeps reporting
        # httpx's REAL signature. Without it the wrapper advertises `app` as a
        # supported parameter -- the shim would be telling every introspecting
        # caller "yes, pass app" and then dropping it. The sentinel below, not the
        # signature, is what makes re-import idempotent.
        @_functools.wraps(_orig_client_init)
        def _client_init(self, *args, app=None, **kwargs):
            # Dropping `app` is lossless ONLY when an explicit transport= came with
            # it -- that transport is what actually routes in-process, and starlette
            # 0.27 always passes both. With app= alone, `app` WAS the routing, and
            # silently discarding it makes httpx open a real socket to base_url:
            # a test that believes it is sandboxed would hit the network instead.
            # Refuse loudly rather than degrade quietly.
            if app is not None and kwargs.get("transport") is None:
                raise TypeError(
                    "httpx.Client(app=...) without transport=: this shim only drops "
                    "`app` when an explicit transport= is supplied alongside it. "
                    "Dropping it here would silently turn an in-process ASGI call "
                    "into a real network request. Wrap the app yourself: "
                    "transport=httpx.ASGITransport(app=app)."
                )
            return _orig_client_init(self, *args, **kwargs)

        _client_init._ava_drops_app = True
        _httpx.Client.__init__ = _client_init
