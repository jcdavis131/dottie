"""One heuristic: harness-api routes exactly as the Dottie router's MoMA-lite.

lib/moma_lite.py is vendored from packages/dottie-loop/dottie_loop/backends.py
by scripts/vendor_router.py (Vercel deploys this app without the monorepo).
These tests fail when the vendored copy is stale, and hold production routing
to the router's goldens (packages/dottie-loop/tests/fixtures/moma_route_goldens.json).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO = PACKAGE_ROOT.parents[1]
GOLDENS = REPO / "packages" / "dottie-loop" / "tests" / "fixtures" / "moma_route_goldens.json"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lib import production_routing


def test_vendored_heuristic_is_current():
    r = subprocess.run([sys.executable, str(PACKAGE_ROOT / "scripts" / "vendor_router.py"), "--check"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not GOLDENS.is_file(), reason="monorepo goldens not present")
@pytest.mark.parametrize("case", json.loads(GOLDENS.read_text(encoding="utf-8"))["cases"] if GOLDENS.is_file() else [],
                         ids=lambda c: c["goal"][:40] or "<empty>")
def test_production_routing_matches_router_goldens(case):
    out = production_routing.route_goal(case["goal"])
    assert out["intent"] == case["intent"]
    assert out["intent_scores"] == case["intent_scores"]
    assert out["complexity"] == case["complexity"]
    assert out["moma_tier"] == case["moma_tier"]
    assert out["recommended_agents"] == case["routed_agents"]
    assert round(out["heuristic_score"], 2) == case["confidence"]


def test_no_second_classifier_in_production_routing():
    src = (PACKAGE_ROOT / "lib" / "production_routing.py").read_text(encoding="utf-8")
    assert '"words":' not in src and "re.search" not in src  # keywords live in the vendored copy only
    assert not (PACKAGE_ROOT / "lib" / "heuristics.py").exists()
    assert not (PACKAGE_ROOT / "lib" / "vector_router.py").exists()
