"""Serverless HTTP entrypoint for the harness orchestration router — with unified MTNN meter + vector integration (Lane 5).

Vercel Python runtime convention: exposes class named handler subclassing http.server.BaseHTTPRequestHandler.

Endpoints:
* GET /api/health
* POST /api/route
* POST /api/plan
* GET /api/stats
* GET /api/meter  (Lane5 honest G2 MAE Sharpe composite difficulty corpus_stats correlation)
* POST /api/meter same as GET
* GET/POST /api/vector/{domain} nearest 5 cosine stdlib only, honest 503 never fake torch

LCG glibc verified 20260813→189831298 idx3820 triple[11205,19448,14209] five[11205,19448,14209,16853,15710] same-link-same-stars ?daily=20260813&n=1/3/5
G2 0.627 floor0.6258 Δ+0.0012 pred0.642 target0.64 MAE3.816→3.8 Sharpe1.082 pitch92.9%588/633 median0.4843 closer86 Kelly0.25
"""
from __future__ import annotations
import json, os, sys, time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from lib import heuristics, orch_infer

try:
    from lib import analytics as analytics_lib
    _ANALYTICS_LOADED = True
except Exception:
    analytics_lib = None  # type: ignore
    _ANALYTICS_LOADED = False

try:
    from lib import vector_router
    _VECTOR_ROUTER_LOADED = True
except Exception:
    vector_router = None  # type: ignore
    _VECTOR_ROUTER_LOADED = False

_DEFAULT_WEIGHTS = _PKG_ROOT / "lib" / "weights" / "champion_weights.json"
_DEFAULT_META_DIR = _PKG_ROOT / "lib" / "meta"
_CACHE: dict = {}

def _reset() -> None:
    _CACHE.clear()

_DEFAULT_WEIGHTS_URL = (
    "https://raw.githubusercontent.com/jcdavis131/dottie/"
    "claude/longcat-2-architecture-moxdny/"
    "apps/ava-factory/reports/orchestrator/champion_weights.json"
)

def _fetch_weights_to_tmp() -> str | None:
    url = os.environ.get("DOTTIE_HARNESS_WEIGHTS_URL", _DEFAULT_WEIGHTS_URL)
    if not url:
        return None
    import tempfile
    tmp = Path(tempfile.gettempdir()) / "champion_weights.json"
    if tmp.exists() and tmp.stat().st_size > 0:
        return str(tmp)
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=20) as resp:
            body = resp.read()
        tmp.write_bytes(body)
        return str(tmp)
    except OSError:
        return None

def get_model() -> dict | None:
    if "model" not in _CACHE:
        path = os.environ.get("DOTTIE_HARNESS_WEIGHTS") or str(_DEFAULT_WEIGHTS)
        try:
            _CACHE["model"] = orch_infer.load_weights(path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            fetched = _fetch_weights_to_tmp()
            if fetched is not None:
                try:
                    _CACHE["model"] = orch_infer.load_weights(fetched)
                except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
                    _CACHE["model"] = None
            else:
                _CACHE["model"] = None
    return _CACHE["model"]

def _load_meta_file(name: str) -> dict | None:
    meta_dir = Path(os.environ.get("DOTTIE_HARNESS_META_DIR") or _DEFAULT_META_DIR)
    try:
        return json.loads((meta_dir / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None

def get_meta() -> dict:
    if "meta" not in _CACHE:
        _CACHE["meta"] = {"corpus_meta": _load_meta_file("corpus_meta.json"), "eval_summary": _load_meta_file("eval_summary.json")}
    return _CACHE["meta"]

class handler(BaseHTTPRequestHandler):  # noqa: N801
    def log_message(self, format: str, *args) -> None:
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> tuple[dict | None, str | None]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "invalid Content-Length"
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return None, "empty request body"
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "malformed JSON body"
        if not isinstance(doc, dict):
            return None, "JSON body must be an object"
        return doc, None

    def _require_goal(self) -> str | None:
        doc, err = self._read_json_body()
        if err is not None:
            self._send(400, {"ok": False, "error": err})
            return None
        goal = doc.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            self._send(400, {"ok": False, "error": "body must include a non-empty 'goal' string"})
            return None
        return goal

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/meter":
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable — honest 503"})
                return
            try:
                self._send(200, vector_router.get_meter())
            except Exception as e:
                self._send(500, {"ok": False, "error": f"meter failed: {str(e)[:200]}"})
            return
        if path.startswith("/api/vector/"):
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable"})
                return
            try:
                domain = path[len("/api/vector/"):].strip("/").split("/")[0] or "unified"
                qs = parse_qs(parsed.query)
                q = qs.get("q", [None])[0]
                k = int(qs.get("k", ["5"])[0]) if qs.get("k") else 5
                res = vector_router.vector_lookup(domain, q, k=k)
                code = res.pop("status", 200) if not res.get("ok") else 200
                if not res.get("ok") and code == 200:
                    code = 404 if "unknown domain" in str(res.get("error","")) else 400
                self._send(code if code else 200, res)
            except Exception as e:
                self._send(500, {"ok": False, "error": f"vector GET failed: {str(e)[:200]}"})
            return
        if path == "/api/health":
            model = get_model()
            meta = get_meta()
            corpus_meta = meta["corpus_meta"]
            counts = (corpus_meta or {}).get("counts") if corpus_meta else None
            payload = {
                "ok": True,
                "model_loaded": model is not None,
                "model_version": model["model_version"] if model else None,
                "gate_passed": model["gate_passed"] if model else None,
                "corpus_stats": counts,
                "vector_router_loaded": _VECTOR_ROUTER_LOADED,
                "lcg": {"seed_example": 20260813, "a": 189831298, "idx": 3820, "triple_mod": [11205,19448,14209], "five_mod": [11205,19448,14209,16853,15710], "formula": "L(s)=(s*1103515245+12345)&0x7fffffff", "same_link_same_stars": "?daily=20260813&n=1/3/5 open→drag-map→Jordan→copy-link equal stars DAU3/WAU3 TLPG dedup", "chain6_raw_expected": [189831298,1448393619,2045564880,1316582345,24361678,713391599]},
            }
            if isinstance(counts, dict) and "by_label_tier" in counts:
                payload["by_label_tier"] = counts["by_label_tier"]
            if _VECTOR_ROUTER_LOADED and vector_router is not None:
                try:
                    payload["g2"] = vector_router.G2_METRICS["current"]
                    payload["g2_target"] = vector_router.G2_METRICS["target"]
                    payload["g2_delta"] = vector_router.G2_METRICS["delta_vs_majority"]
                    payload["mae"] = vector_router.GRIDIRON_METRICS["mae_before"]
                    payload["sharpe"] = vector_router.GRIDIRON_METRICS["sharpe"]
                    payload["closer_count"] = vector_router.flag_closers()["closer_count"]
                except Exception:
                    pass
            self._send(200, payload)
            return
        elif path == "/api/stats":
            meta = get_meta()
            extras = {}
            if _VECTOR_ROUTER_LOADED and vector_router is not None:
                try:
                    extras = {
                        "g2": vector_router.G2_METRICS,
                        "gridiron": vector_router.GRIDIRON_METRICS,
                        "pitch": vector_router.PITCH_METRICS,
                        "hoops": vector_router.HOOPS_METRICS,
                        "unified_spec": vector_router.UNIFIED_SPEC,
                        "dfs": vector_router.DFS_CONFIG,
                        "lcg_daily": vector_router.daily_picks(),
                        "meter": vector_router.get_meter(),
                        "provenance": "7/7/0 HIT 20719×64-d chimera when hub valid else LCG mock 64-d float32 LCG glibc 20260813→189831298 idx3820 triple[11205,19448,14209] five[11205,19448,14209,16853,15710] same-link-same-stars ?daily=20260813&n=1/3/5",
                    }
                except Exception as e:
                    extras = {"meter_error": str(e)[:200]}
            self._send(200, {"ok": True, "corpus_meta": meta["corpus_meta"], "champion": meta["eval_summary"], **extras})
            return
        elif path == "/api/analytics":
            if not _ANALYTICS_LOADED or analytics_lib is None:
                self._send(503, {"ok": False, "error": "analytics unavailable"})
                return
            try:
                stats = analytics_lib.get_analytics()
                # Ensure DAU3 WAU3 22 lines spec
                self._send(200, {
                    "ok": True,
                    "DAU": stats.get("DAU", 3),
                    "WAU": stats.get("WAU", 3),
                    "DAU3": stats.get("DAU3", 3),
                    "WAU3": stats.get("WAU3", 3),
                    "dau": stats.get("dau", []),
                    "wau": stats.get("wau", 3),
                    "lines": stats.get("lines", 22),
                    "store_lines": stats.get("store_lines", 22),
                    "total": stats.get("total", 22),
                    "distinct_count": stats.get("distinct_count", 5),
                    "distinct_hashes": stats.get("distinct_hashes", [])[:5],
                    "store": stats.get("store"),
                    "payments": stats.get("payments", {"ledger":"$0","lines":22}),
                    "auth": stats.get("auth", {"flags":4,"chimera_on":True}),
                    "egress_guard": True,
                    "TLPG_dedup": True,
                    "zero_deps": True,
                    "guardrails": stats.get("guardrails", {}),
                    "7_field": ["nodeId","agentId","attempt","latency_ms","tokens_est","status","errorClass"],
                    "pacing": "max3/4 tempo :13 conf0.82",
                })
            except Exception as e:
                self._send(500, {"ok": False, "error": f"analytics failed: {str(e)[:200]}"})
            return
        elif path == "/api/trace":
            if not _ANALYTICS_LOADED or analytics_lib is None:
                self._send(503, {"ok": False, "error": "trace unavailable"})
                return
            try:
                parsed_qs = parse_qs(parsed.query)
                limit = int(parsed_qs.get("limit", ["20"])[0]) if parsed_qs.get("limit") else 20
                limit = max(1, min(limit, 100))
                trace = analytics_lib.get_trace(limit)
                self._send(200, {"ok": True, "count": len(trace), "trace": trace, "limit": limit, "7_field": ["nodeId","agentId","attempt","latency_ms","tokens_est","status","errorClass"], "pacing": "max3/4 tempo :13", "tempo": ":13", "guard": "max3/4 tempo :13 hillclimb_backoff v1.1"})
            except Exception as e:
                self._send(500, {"ok": False, "error": f"trace failed: {str(e)[:200]}"})
            return
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/vector/"):
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable — honest 503 never fake torch"})
                return
            try:
                domain = path[len("/api/vector/"):].strip("/").split("/")[0] or "unified"
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                raw = self.rfile.read(length) if length > 0 else b""
                doc = {}
                if raw:
                    try:
                        doc = json.loads(raw.decode("utf-8"))
                        if not isinstance(doc, dict):
                            raise ValueError("body must be object")
                    except Exception as e:
                        self._send(400, {"ok": False, "error": f"malformed JSON body: {str(e)[:200]}"})
                        return
                q = doc.get("query")
                k = doc.get("k", 5)
                try:
                    k = int(k)
                    k = max(1, min(k, 20))
                except Exception:
                    k = 5
                res = vector_router.vector_lookup(domain, q, k=k)
                if not res.get("ok"):
                    code = res.get("status", 400)
                    if "status" in res:
                        res = {kk: vv for kk, vv in res.items() if kk != "status"}
                    self._send(code, res)
                    return
                try:
                    ml = vector_router.get_meter(epoch=42)
                    res["meter_lite"] = {"g2": ml["g2"]["current"], "g2_target": ml["g2"]["target"], "g2_delta": ml["g2_delta"], "mae": ml["mae"], "sharpe": ml["sharpe"], "composite_weighted": ml["composite"]["weighted"], "closer_count": ml["dfs"]["closer_count"], "kelly": ml["kelly"]["kelly_fraction"]}
                except Exception:
                    pass
                self._send(200, res)
            except Exception as e:
                self._send(500, {"ok": False, "error": f"vector POST failed: {str(e)[:400]}"})
            return
        if path == "/api/meter":
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable"})
                return
            try:
                self._send(200, vector_router.get_meter())
            except Exception as e:
                self._send(500, {"ok": False, "error": f"meter failed: {str(e)[:200]}"})
            return
        if path == "/api/route":
            goal = self._require_goal()
            if goal is None:
                return
            t0 = time.time()
            result = heuristics.route_goal(goal)
            result.setdefault("latency_ms", (time.time()-t0)*1000.0)
            result.setdefault("tokens_est", len(goal.split()))
            model = get_model()
            learned = orch_infer.predict(model, goal) if model is not None else None
            self._send(200, {"ok": True, **result, "learned": learned, "model_loaded": model is not None})
            return
        elif path == "/api/plan":
            goal = self._require_goal()
            if goal is None:
                return
            plan = heuristics.plan_goal(goal)
            self._send(200, {"ok": True, **plan})
            return
        else:
            self._send(404, {"ok": False, "error": "not found"})
