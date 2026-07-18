#!/usr/bin/env python3
"""HTTP assertions for scripts/smoke_live.sh (live URL or TestClient dry-run).

Live mode hits AVA_BASE_URL / --base-url with urllib (no extra deps).
Dry-run (--dry / AVA_SMOKE_DRY_RUN=1) uses FastAPI TestClient + a fake engine
so the same step checks run without a checkpoint, GPU, or long-lived uvicorn.

Full live pass against a real nano ckpt is deferred to T9.1 when
runs/chat/ava_nano_chat.pt is absent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_REPO = Path(__file__).resolve().parent.parent


class SmokeFail(Exception):
    def __init__(self, step: str, detail: str) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"{step}: {detail}")


def _fail(step: str, detail: str) -> None:
    raise SmokeFail(step, detail)


def _ok(step: str, msg: str = "") -> None:
    suffix = f" - {msg}" if msg else ""
    print(f"  OK  {step}{suffix}", flush=True)


class _HttpClient:
    """Minimal JSON client against a live base URL."""

    def __init__(self, base: str, timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self.base}{path}"
        data = None
        hdrs = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                code = int(resp.getcode())
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "json" in ctype or (raw[:1] in "{["):
                    try:
                        return code, json.loads(raw) if raw else None
                    except json.JSONDecodeError:
                        return code, raw
                return code, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(raw) if raw else {"detail": str(e)}
            except json.JSONDecodeError:
                payload = raw
            return int(e.code), payload
        except urllib.error.URLError as e:
            _fail("connect", f"cannot reach {url}: {e.reason}")
            raise  # pragma: no cover


def _check_health(get: Callable[[str], tuple[int, Any]]) -> None:
    code, body = get("/health")
    if code != 200:
        _fail("health", f"expected 200, got {code}: {body}")
    if not isinstance(body, dict):
        _fail("health", f"expected JSON object, got {type(body)}")
    if body.get("status") != "ok":
        _fail("health", f"status != ok: {body}")
    params = body.get("params")
    vocab = body.get("vocab")
    if not isinstance(params, int) or params <= 10_000_000:
        _fail("health", f"params must be int > 10_000_000, got {params!r}")
    if vocab != 8192:
        _fail("health", f"vocab must be 8192, got {vocab!r}")
    _ok("health", f"params={params} vocab={vocab}")


def _check_generate(post: Callable[[str, dict[str, Any]], tuple[int, Any]]) -> None:
    code1, g1 = post("/generate", {"text": "Hello from smoke A", "max_tokens": 16})
    code2, g2 = post(
        "/generate", {"text": "Completely different prompt B xyz", "max_tokens": 16}
    )
    if code1 != 200 or code2 != 200:
        _fail("generate", f"expected 200/200, got {code1}/{code2}: {g1!r} / {g2!r}")
    if not isinstance(g1, dict) or not isinstance(g2, dict):
        _fail("generate", "responses must be JSON objects")
    t1, t2 = g1.get("text"), g2.get("text")
    if not (isinstance(t1, str) and t1.strip()):
        _fail("generate", f"prompt A text empty: {g1!r}")
    if not (isinstance(t2, str) and t2.strip()):
        _fail("generate", f"prompt B text empty: {g2!r}")
    if t1 == t2:
        _fail("generate", "two different prompts returned identical text")
    _ok("generate", "two prompts -> non-empty differing text")


def _check_inspect(
    post: Callable[[str, dict[str, Any]], tuple[int, Any]],
    *,
    expect_input_dependent: bool,
) -> None:
    code_a, i1 = post("/jspace/inspect", {"text": "The spider has eight legs."})
    code_b, i2 = post("/jspace/inspect", {"text": "France is a country in Europe."})
    if code_a != 200 or code_b != 200:
        _fail("inspect", f"expected 200/200, got {code_a}/{code_b}")
    if not isinstance(i1, dict) or not isinstance(i2, dict):
        _fail("inspect", "responses must be JSON objects")
    m1, m2 = i1.get("verbalizable_mass"), i2.get("verbalizable_mass")
    for label, m in (("A", m1), ("B", m2)):
        if not isinstance(m, (int, float)) or not (0.0 < float(m) < 1.0):
            _fail("inspect", f"verbalizable_mass {label} not in (0,1): {m!r}")
    if expect_input_dependent:
        if abs(float(m1) - float(m2)) < 1e-9 and i1.get("top_concepts") == i2.get(
            "top_concepts"
        ):
            _fail(
                "inspect",
                "verbalizable_mass + top_concepts identical across inputs "
                f"(mass={m1})",
            )
        _ok("inspect", f"mass_A={m1} mass_B={m2} (input-dependent)")
    else:
        _ok("inspect", f"mass_A={m1} mass_B={m2}")


def _check_intervene_403(
    post: Callable[[str, dict[str, Any]], tuple[int, Any]],
) -> None:
    code403, body403 = post(
        "/jspace/intervene?mode=research",
        {
            "from": "spider",
            "to": "ant",
            "text": "The number of legs on the animal that spins webs is",
        },
    )
    if code403 != 403:
        _fail("intervene-403", f"expected 403, got {code403}: {body403}")
    detail = ""
    if isinstance(body403, dict):
        detail = str(body403.get("detail", ""))
    if "ENABLE_JSPACE_WRITE" not in detail:
        _fail("intervene-403", f"detail missing ENABLE_JSPACE_WRITE: {body403}")
    _ok("intervene-403", "research without ENABLE_JSPACE_WRITE -> 403")


def _check_intervene_write(
    post: Callable[[str, dict[str, Any]], tuple[int, Any]],
    audit_path: Path | None,
) -> None:
    before = 0
    if audit_path is not None and audit_path.is_file():
        before = sum(1 for line in audit_path.open(encoding="utf-8") if line.strip())
    code200, iv = post(
        "/jspace/intervene?mode=research",
        {
            "from": "spider",
            "to": "ant",
            "text": "The number of legs on the animal that spins webs is",
        },
    )
    if code200 != 200:
        _fail("intervene-write", f"expected 200, got {code200}: {iv}")
    if not isinstance(iv, dict):
        _fail("intervene-write", f"expected JSON object, got {iv!r}")
    if iv.get("baseline_text") == iv.get("intervened_text"):
        _fail("intervene-write", f"baseline_text == intervened_text: {iv}")
    if audit_path is not None:
        if not audit_path.is_file():
            _fail("intervene-write", f"audit file missing: {audit_path}")
        after = sum(1 for line in audit_path.open(encoding="utf-8") if line.strip())
        if after < before + 1:
            _fail(
                "intervene-write",
                f"serve_audit.jsonl did not grow ({before} -> {after})",
            )
    _ok("intervene-write", "spider->ant changed + audit grew")


def _check_eval_branch(get: Callable[[str], tuple[int, Any]]) -> None:
    code_e, ev = get("/jspace/eval_branch")
    if code_e != 200:
        _fail("eval_branch", f"expected 200, got {code_e}: {ev}")
    if not isinstance(ev, dict):
        _fail("eval_branch", f"expected JSON object, got {type(ev)}")
    eval_path = _REPO / "reports" / "branch_eval_results_real.json"
    if eval_path.is_file():
        with eval_path.open(encoding="utf-8") as f:
            on_disk = json.load(f)
        key = next((k for k in ("base", "meta", "chat") if k in on_disk), None)
        if key is None:
            key = next(iter(on_disk), None)
        if key is not None and key not in ev:
            _fail("eval_branch", f"missing key {key!r} from on-disk eval JSON")
        _ok("eval_branch", f"has key {key!r}")
    else:
        if not ev:
            _fail("eval_branch", "empty response and no on-disk eval JSON")
        _ok("eval_branch", "JSON returned (on-disk file absent)")


def _check_report(get: Callable[[str], tuple[int, Any]]) -> None:
    report_html = _REPO / "reports" / "index.html"
    code_r, rep = get("/report")
    disk_ok = report_html.is_file() and report_html.stat().st_size > 10240
    if code_r == 200:
        if isinstance(rep, str) and len(rep) > 10240:
            _ok("report", f"/report 200 ({len(rep)} bytes)")
            return
        if disk_ok:
            _ok(
                "report",
                f"/report 200; reports/index.html={report_html.stat().st_size} bytes",
            )
            return
        _fail(
            "report",
            f"/report 200 but body/file <=10240 bytes (body_type={type(rep).__name__})",
        )
    if disk_ok:
        _ok(
            "report",
            f"/report {code_r} but reports/index.html exists "
            f"({report_html.stat().st_size} bytes)",
        )
        return
    _fail(
        "report",
        f"/report -> {code_r} and reports/index.html missing/small; "
        "run: python scripts/make_report.py",
    )


def _run_core(
    get: Callable[[str], tuple[int, Any]],
    post: Callable[[str, dict[str, Any]], tuple[int, Any]],
    *,
    expect_input_dependent_inspect: bool,
) -> None:
    _check_health(get)
    _check_generate(post)
    _check_inspect(post, expect_input_dependent=expect_input_dependent_inspect)
    _check_intervene_403(post)
    _check_eval_branch(get)
    _check_report(get)


def _make_http_pair(
    base_url: str,
) -> tuple[
    Callable[[str], tuple[int, Any]],
    Callable[[str, dict[str, Any]], tuple[int, Any]],
]:
    client = _HttpClient(base_url)

    def get(path: str) -> tuple[int, Any]:
        return client.request("GET", path)

    def post(path: str, body: dict[str, Any]) -> tuple[int, Any]:
        return client.request("POST", path, body=body)

    return get, post


def run_live(base_url: str, *, intervene_base_url: str | None) -> None:
    get, post = _make_http_pair(base_url)
    _run_core(get, post, expect_input_dependent_inspect=True)
    if intervene_base_url:
        print(f"  ... intervene-write against {intervene_base_url}", flush=True)
        _, post_w = _make_http_pair(intervene_base_url)
        _check_intervene_write(post_w, _REPO / "runs" / "serve_audit.jsonl")
    else:
        print(
            "  SKIP intervene-write "
            "(set AVA_SMOKE_INTERVENE=1 - bash boots a write-enabled server)",
            flush=True,
        )


def run_dry() -> None:
    """Prove HTTP check logic via TestClient + fake engine (no GPU / ckpt)."""
    os.environ["AVA_SKIP_ENGINE_BOOT"] = "1"
    os.environ.pop("ENABLE_JSPACE_WRITE", None)

    try:
        import asyncio

        from httpx import ASGITransport, AsyncClient
    except ImportError as e:
        _fail("dry-run", f"httpx not installed ({e}); pip install fastapi httpx")

    # Ensure repo root is on sys.path when invoked as scripts/smoke_live_checks.py
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))

    from ava import serve_engine as se
    import server as srv

    class _FakeEngine:
        def stats(self) -> dict[str, Any]:
            return {
                "ckpt": "dry-run-fake.pt",
                "params": 14_000_001,
                "vocab": 8192,
                "d_model": 256,
            }

        def generate(
            self,
            text: str,
            max_tokens: int = 64,
            temperature: float = 0.8,
            task_type: str = "chat",
            **kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "text": f"out:{text[:24]}",
                "tokens": 3,
                "route_probs": [
                    {"S1": 0.25, "S2": 0.25, "Critic": 0.25, "Planner": 0.25}
                ],
                "latency_ms": 1.0,
            }

        def inspect(self, text: str) -> dict[str, Any]:
            spider = "spider" in text.lower()
            return {
                "top_concepts": [
                    {"concept": "spider" if spider else "france", "p": 0.2}
                ]
                * 8,
                "verbalizable_mass": 0.064 if spider else 0.071,
                "broadcast_strength": 0.22,
                "per_space": {},
                "route_probs": [0.15, 0.55, 0.10, 0.20],
                "safety_scan": {"total": 0.0},
            }

        def intervene(
            self,
            text: str,
            from_concept: str,
            to_concept: str,
            space: str = "system2",
            **kwargs: Any,
        ) -> dict[str, Any]:
            audit = _REPO / "runs" / "serve_audit.jsonl"
            audit.parent.mkdir(parents=True, exist_ok=True)
            with audit.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"from": from_concept, "to": to_concept, "dry": True})
                    + "\n"
                )
            return {
                "baseline_text": "8",
                "intervened_text": "6",
                "delta_logprob": 0.5,
                "space": space,
                "changed": True,
                "audit_logged": True,
            }

        def block_stream(self, text: str):  # noqa: ANN201
            if False:
                yield {}

    fake = _FakeEngine()
    orig_server_ge = srv.get_engine
    orig_se_ge = se.get_engine
    srv.get_engine = lambda: fake  # type: ignore[assignment]
    se.get_engine = lambda: fake  # type: ignore[assignment]

    async def _decode(r: Any) -> tuple[int, Any]:
        code = int(r.status_code)
        ctype = (r.headers.get("content-type") or "").lower()
        text = r.text
        if "json" in ctype or (text[:1] in "{["):
            try:
                return code, r.json()
            except Exception:
                return code, text
        return code, text

    async def _async_run() -> None:
        transport = ASGITransport(app=srv.app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:

            async def aget(path: str) -> tuple[int, Any]:
                return await _decode(await client.get(path))

            async def apost(path: str, body: dict[str, Any]) -> tuple[int, Any]:
                return await _decode(await client.post(path, json=body))

            code, body = await aget("/health")
            if code != 200:
                _fail("health", f"expected 200, got {code}: {body}")
            if not isinstance(body, dict) or body.get("status") != "ok":
                _fail("health", f"bad body: {body}")
            if not isinstance(body.get("params"), int) or body["params"] <= 10_000_000:
                _fail("health", f"params: {body.get('params')!r}")
            if body.get("vocab") != 8192:
                _fail("health", f"vocab: {body.get('vocab')!r}")
            _ok("health", f"params={body['params']} vocab={body['vocab']}")

            code1, g1 = await apost(
                "/generate", {"text": "Hello from smoke A", "max_tokens": 16}
            )
            code2, g2 = await apost(
                "/generate",
                {"text": "Completely different prompt B xyz", "max_tokens": 16},
            )
            if code1 != 200 or code2 != 200:
                _fail("generate", f"{code1}/{code2}: {g1!r}/{g2!r}")
            assert isinstance(g1, dict) and isinstance(g2, dict)
            if not g1.get("text") or not g2.get("text") or g1["text"] == g2["text"]:
                _fail("generate", f"bad texts: {g1.get('text')!r} / {g2.get('text')!r}")
            _ok("generate", "two prompts -> non-empty differing text")

            code_a, i1 = await apost(
                "/jspace/inspect", {"text": "The spider has eight legs."}
            )
            code_b, i2 = await apost(
                "/jspace/inspect", {"text": "France is a country in Europe."}
            )
            if code_a != 200 or code_b != 200:
                _fail("inspect", f"{code_a}/{code_b}")
            assert isinstance(i1, dict) and isinstance(i2, dict)
            m1, m2 = i1["verbalizable_mass"], i2["verbalizable_mass"]
            if not (0.0 < float(m1) < 1.0 and 0.0 < float(m2) < 1.0):
                _fail("inspect", f"mass out of range: {m1}/{m2}")
            if abs(float(m1) - float(m2)) < 1e-9 and i1.get("top_concepts") == i2.get(
                "top_concepts"
            ):
                _fail("inspect", "not input-dependent")
            _ok("inspect", f"mass_A={m1} mass_B={m2} (input-dependent)")

            code403, body403 = await apost(
                "/jspace/intervene?mode=research",
                {
                    "from": "spider",
                    "to": "ant",
                    "text": "The number of legs on the animal that spins webs is",
                },
            )
            if code403 != 403:
                _fail("intervene-403", f"expected 403, got {code403}: {body403}")
            detail = str(body403.get("detail", "")) if isinstance(body403, dict) else ""
            if "ENABLE_JSPACE_WRITE" not in detail:
                _fail("intervene-403", f"detail: {body403}")
            _ok("intervene-403", "research without ENABLE_JSPACE_WRITE -> 403")

            code_e, ev = await aget("/jspace/eval_branch")
            if code_e != 200 or not isinstance(ev, dict):
                _fail("eval_branch", f"{code_e}: {ev}")
            eval_path = _REPO / "reports" / "branch_eval_results_real.json"
            if eval_path.is_file():
                with eval_path.open(encoding="utf-8") as f:
                    on_disk = json.load(f)
                key = next((k for k in ("base", "meta", "chat") if k in on_disk), None)
                if key is not None and key not in ev:
                    _fail("eval_branch", f"missing {key!r}")
                _ok("eval_branch", f"has key {key!r}")
            else:
                _ok("eval_branch", "JSON returned")

            code_r, rep = await aget("/report")
            report_html = _REPO / "reports" / "index.html"
            disk_ok = report_html.is_file() and report_html.stat().st_size > 10240
            if code_r == 200 or disk_ok:
                size = (
                    report_html.stat().st_size
                    if report_html.is_file()
                    else (len(rep) if isinstance(rep, str) else 0)
                )
                _ok("report", f"/report {code_r} size~{size}")
            else:
                _fail("report", f"/report {code_r}; index.html missing")

            os.environ["ENABLE_JSPACE_WRITE"] = "1"
            audit_path = _REPO / "runs" / "serve_audit.jsonl"
            before = 0
            if audit_path.is_file():
                before = sum(
                    1 for line in audit_path.open(encoding="utf-8") if line.strip()
                )
            code200, iv = await apost(
                "/jspace/intervene?mode=research",
                {
                    "from": "spider",
                    "to": "ant",
                    "text": "The number of legs on the animal that spins webs is",
                },
            )
            if code200 != 200 or not isinstance(iv, dict):
                _fail("intervene-write", f"{code200}: {iv}")
            if iv.get("baseline_text") == iv.get("intervened_text"):
                _fail("intervene-write", f"unchanged: {iv}")
            after = sum(1 for line in audit_path.open(encoding="utf-8") if line.strip())
            if after < before + 1:
                _fail("intervene-write", f"audit {before}->{after}")
            _ok("intervene-write", "spider->ant changed + audit grew")

    try:
        asyncio.run(_async_run())
    finally:
        srv.get_engine = orig_server_ge  # type: ignore[assignment]
        se.get_engine = orig_se_ge  # type: ignore[assignment]
        os.environ.pop("ENABLE_JSPACE_WRITE", None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=os.environ.get("AVA_BASE_URL", ""))
    ap.add_argument(
        "--intervene-base-url",
        default=os.environ.get("AVA_SMOKE_INTERVENE_URL", ""),
        help="Write-enabled server URL (ENABLE_JSPACE_WRITE=1); optional",
    )
    ap.add_argument(
        "--dry",
        action="store_true",
        default=os.environ.get("AVA_SMOKE_DRY_RUN", "0") == "1",
        help="TestClient + fake engine (no ckpt / GPU)",
    )
    args = ap.parse_args()

    try:
        if args.dry:
            print("smoke_live_checks: DRY-RUN (ASGI fake engine, no real ckpt)", flush=True)
            run_dry()
        else:
            if not args.base_url:
                print(
                    "SMOKE FAIL connect: set --base-url or AVA_BASE_URL "
                    "(or use --dry / AVA_SMOKE_DRY_RUN=1)",
                    flush=True,
                )
                return 1
            print(f"smoke_live_checks: LIVE against {args.base_url}", flush=True)
            run_live(
                args.base_url,
                intervene_base_url=args.intervene_base_url or None,
            )
    except SmokeFail as e:
        print(f"SMOKE FAIL {e.step}: {e.detail}", flush=True)
        return 1
    except Exception as e:
        print(f"SMOKE FAIL unexpected: {type(e).__name__}: {e}", flush=True)
        return 1

    print("SMOKE PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
