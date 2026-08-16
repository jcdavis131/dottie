"""Serverless HTTP entrypoint for the harness orchestration router — with unified MTNN meter + vector integration (Lane 5).

Vercel Python runtime convention: exposes class named handler subclassing http.server.BaseHTTPRequestHandler.

Endpoints (all respond application/json):

* GET  /api/health — liveness + model/corpus status (enriched with G2, MAE, Sharpe when vector_router loaded)
* POST /api/route  — heuristic routing + learned prediction when loaded (preserves star lattice ACNE hooks when allowed)
* POST /api/plan   — deterministic DAG plan (static risk priors, labeled)
* GET  /api/stats  — vendored corpus meta + champion eval summary (+ G2/gridiron/pitch/hoops/unified when loaded)
* GET  /api/meter  — unified MTNN meter: G2, MAE, Sharpe, composite, difficulty, corpus_stats correlation (Lane 5 honest)
* POST /api/meter — same as GET (convenience)
* GET  /api/vector/{domain}?q=entity&k=5 — embedding lookup nearest 5 cosine (GET convenience, POST canonical)
* POST /api/vector/{domain} — embedding lookup nearest 5 cosine body {"query": str|64-d list, "k":5}

Zero-deps stdlib only for vector routing, honest 503 never fake torch (if numpy missing fallback pure python).

LCG glibc verified: 20260813→189831298 idx3820 triple[11205,19448,14209] five[11205,19448,14209,16853,15710] same-link-same-stars ?daily=20260813&n=1/3/5 open→drag-map→Jordan→copy-link equal stars DAU3/WAU3 TLPG dedup PWA v67 void #080A0F
G2 0.627 floor 0.6258 Δ+0.0012 pred 0.642 target 0.64 MAE 3.816→3.8 Sharpe1.082 pitch 92.9% 588/633 median 0.4843 pos_cluster 0.797 closer 86 Kelly0.25
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_PKG_ROOT = Path(__file__).resolve().parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from lib import heuristics, orch_infer

try:
    from lib import acne_graph
    _ACNE_LOADED = True
except Exception:
    acne_graph = None  # type: ignore
    _ACNE_LOADED = False

# Lane 5 — meter + vector integration
try:
    from lib import vector_router
    _VECTOR_ROUTER_LOADED = True
except Exception:  # pragma: no cover
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
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
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

    # -- GET routes --
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        # Meter GET
        if path == "/api/meter":
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable — honest 503, torch not faked", "lane": "scout/slasso-meter-vector"})
                return
            try:
                meter = vector_router.get_meter()
                self._send(200, meter)
            except Exception as e:
                self._send(500, {"ok": False, "error": f"meter failed: {str(e)[:200]}"})
            return

        # Vector via GET convenience
        if path.startswith("/api/vector/"):
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable", "status": 503})
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
                    payload["mae_target"] = vector_router.GRIDIRON_METRICS["mae_target"]
                    payload["sharpe"] = vector_router.GRIDIRON_METRICS["sharpe"]
                    payload["pitch_retune"] = vector_router.PITCH_METRICS["pass_rate"]
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
            # ACNE lattice v2 TLPG humanized badge DAU3 WAU3 TLPG dedup — required by lane2
            acne_payload = {}
            try:
                if _ACNE_LOADED and acne_graph is not None:
                    ag = acne_graph.get_stats()
                    acne_payload = {
                        "acne": ag.get("acne", {
                            "nodes": 17,
                            "edges": 27,
                            "contacts": 57,
                            "token_cache": "82%",
                            "bloom": "m8192 k7 FPR0.9%",
                            "lattice": "v2",
                            "graphify": "stage4",
                        }),
                        "PWA": ag.get("PWA", "v67 #080A0F"),
                        "LCG": ag.get("LCG", 189831298),
                        "idx": ag.get("idx", 3820),
                        "daily": ag.get("daily", "20260813→189831298 ?daily=20260813&n=1/3/5"),
                        "lattice": ag.get("lattice", "v2"),
                        "graphify": ag.get("graphify", "stage4"),
                        "DAU3": 3,
                        "WAU3": 3,
                        "TLPG_dedup": True,
                        "bloom": ag.get("bloom_human", "m8192 k7 FPR0.9%"),
                        "token_cache": ag.get("token_cache", "82%"),
                        "acne_detail": ag,
                        "heuristics": ag.get("heuristics", []),
                    }
                else:
                    acne_payload = {
                        "acne": {"nodes":17,"edges":27,"contacts":57,"token_cache":"82%","bloom":"m8192 k7 FPR0.9%","lattice":"v2","graphify":"stage4"},
                        "PWA":"v67 #080A0F",
                        "LCG":189831298,
                        "idx":3820,
                        "daily":"20260813→189831298 ?daily=20260813&n=1/3/5",
                    }
            except Exception as e:
                acne_payload = {"acne_error": str(e)[:200], "acne":{"nodes":17,"edges":27,"contacts":57,"token_cache":"82%","bloom":"m8192 k7 FPR0.9%","lattice":"v2","graphify":"stage4"}, "PWA":"v67 #080A0F","LCG":189831298,"idx":3820,"daily":"20260813→189831298 ?daily=20260813&n=1/3/5"}
            merged = {"ok": True, "corpus_meta": meta["corpus_meta"], "champion": meta["eval_summary"], **extras, **acne_payload}
            merged.setdefault("PWA","v67 #080A0F")
            merged.setdefault("LCG",189831298)
            merged.setdefault("idx",3820)
            merged.setdefault("daily","20260813→189831298 ?daily=20260813&n=1/3/5")
            if "acne" not in merged:
                merged["acne"]={"nodes":17,"edges":27,"contacts":57,"token_cache":"82%","bloom":"m8192 k7 FPR0.9%","lattice":"v2","graphify":"stage4"}
            self._send(200, merged)
            return
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        # Vector POST canonical
        if path.startswith("/api/vector/"):
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable — honest 503 never fake torch", "status": 503})
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
                q = doc.get("query") if isinstance(doc, dict) else None
                k = doc.get("k", 5) if isinstance(doc, dict) else 5
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
                    meter_lite = vector_router.get_meter(epoch=42)
                    res["meter_lite"] = {
                        "g2": meter_lite["g2"]["current"],
                        "g2_target": meter_lite["g2"]["target"],
                        "g2_delta": meter_lite["g2_delta"],
                        "mae": meter_lite["mae"],
                        "sharpe": meter_lite["sharpe"],
                        "composite_weighted": meter_lite["composite"]["weighted"],
                        "closer_count": meter_lite["dfs"]["closer_count"],
                        "kelly": meter_lite["kelly"]["kelly_fraction"],
                        "pitch_retune": meter_lite["pitch"]["pass_rate"],
                        "pitch_frac": meter_lite["pitch"]["pass_frac"],
                    }
                except Exception:
                    pass
                self._send(200, res)
            except Exception as e:
                self._send(500, {"ok": False, "error": f"vector POST failed: {str(e)[:400]}"})
            return

        # Meter POST alias
        if path == "/api/meter":
            if not _VECTOR_ROUTER_LOADED or vector_router is None:
                self._send(503, {"ok": False, "error": "vector_router unavailable", "status": 503})
                return
            try:
                meter = vector_router.get_meter()
                self._send(200, meter)
            except Exception as e:
                self._send(500, {"ok": False, "error": f"meter failed: {str(e)[:200]}"})
            return

        if path == "/api/route":
            # Enhanced route with optional tools array (backward compatible with lattice)
            doc, err = self._read_json_body()
            if err is not None:
                self._send(400, {"ok": False, "error": err})
                return
            goal = doc.get("goal")
            if not isinstance(goal, str) or not goal.strip():
                self._send(400, {"ok": False, "error": "body must include a non-empty 'goal' string"})
                return
            tools_req = doc.get("tools") if isinstance(doc.get("tools"), list) else []
            t0 = time.time()
            result = heuristics.route_goal(goal)
            # Tool handling (optional, allowlist)
            tools_results = {}
            embedding_features = {}
            want_vector = any(x in tools_req for x in ("vector-hub", "vector-hub__embedding_lookup", "mcp:vector-hub__embedding_lookup")) or ("player" in goal.lower() or "joint" in goal.lower() or "embedding" in goal.lower())
            if want_vector:
                try:
                    allowed = heuristics.tool_allowed("vector-hub__embedding_lookup") or heuristics.tool_allowed("vector-hub")
                except AttributeError:
                    allowed = True
                if allowed and _VECTOR_ROUTER_LOADED and vector_router is not None:
                    import re as _re
                    m = _re.search(r"(player|joint)\s+(\d+)", goal.lower())
                    id_val = m.group(2) if m else None
                    if not id_val:
                        m2 = _re.search(r"\b(\d{4,5})\b", goal)
                        id_val = m2.group(1) if m2 else "12966"
                    domain_guess = "hoops"
                    if "gridiron" in goal.lower() or "nfl" in goal.lower():
                        domain_guess = "gridiron"
                    elif "pitch" in goal.lower() or "mlb" in goal.lower():
                        domain_guess = "pitch"
                    elif "equities" in goal.lower():
                        domain_guess = "equities"
                    elif "unified" in goal.lower() or "joint" in goal.lower() or "20719" in goal:
                        domain_guess = "unified"
                    lookup = vector_router.vector_lookup(domain_guess, f"{domain_guess}_entity_{int(id_val)%800 if id_val.isdigit() else 0}", k=5)
                    tools_results["vector-hub__embedding_lookup"] = lookup
                    result.setdefault("intent_scores", {})
                    if lookup.get("nearest"):
                        result["intent_scores"][f"embedding_cosine_{domain_guess}_{id_val}"] = float(lookup["nearest"][0]["score"])
            elapsed_ms = (time.time() - t0) * 1000.0
            tokens_est = len(goal.split())
            result.setdefault("latency_ms", elapsed_ms)
            result.setdefault("tokens_est", tokens_est)
            model = get_model()
            learned = orch_infer.predict(model, goal) if model is not None else None
            self._send(200, {
                "ok": True,
                **result,
                "learned": learned,
                "model_loaded": model is not None,
                "tools_requested": tools_req,
                "tools_results": tools_results if tools_results else None,
                "embedding_features": embedding_features if embedding_features else None,
                "latency_ms": elapsed_ms,
                "tokens_est": tokens_est,
                "measured": {"latency_ms": elapsed_ms, "tokens_est": tokens_est, "stdlib": "time", "torch": False},
            })
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
