.PHONY: sync test lint gates forge doctor status ci

# WHY THIS FILE MIRRORS ci.yml, and what it got wrong until 2026-08-01.
#
# `make ci` is what a developer runs to believe the push will be green. Measured against
# the real workflow, it was materially weaker in five ways at once — every one of which
# made it PASS while CI would not:
#
#   1. `test` omitted packages/personal-graphify entirely (77 tests, a HARD gate in CI).
#   2. `test` omitted scripts/'s four self-test suites (241 tests) — themselves only wired
#      into CI on 2026-08-01, having previously run nowhere at all.
#   3. `test` ran `pytest apps/scout-cli/tests` from the REPO ROOT. Measured: 21 failed,
#      2255 passed. From apps/scout-cli, where CI runs it: 2270 passed. Those tests use
#      CWD-relative fixtures, which the 2026-07-22 review already recorded, so `make test`
#      has been showing 21 phantom failures.
#   4. `lint` used `uv run ruff`. ruff is NOT a workspace dependency, so that resolves only
#      by accident of what is on PATH — it works on this box and dies with
#      "Failed to spawn: ruff" on a clean checkout, which is exactly how ci.yml's ruff step
#      went unnoticed for months (61b922e). Now pinned to the same uvx version CI uses, so
#      local and CI cannot report different findings.
#   5. `ci` ran none of the three ratchets, which are the checks most likely to be the
#      thing that reds a push.
#
# If you add a gate to ci.yml, add it here. A local "ci" that is a subset of the real one
# is worse than no local target, because it is trusted.

sync:
	uv sync --all-groups --frozen
	uv run pre-commit install || true

test:
	uv run pytest packages/ava-skills -q
	uv run pytest packages/personal-graphify -q
	uv run pytest packages/ava-open-harness -q || true   # non-blocking: dottie name collision, mirrors ci.yml
	cd apps/scout-cli && uv run pytest tests -q          # MUST run from here: CWD-relative fixtures
	uv run python scripts/test_gate_audit.py
	uv run python scripts/test_retrieval_eval.py
	uv run python scripts/test_task_eval_slice.py
	uv run python scripts/test_check_declared_capabilities.py

lint:
	uvx ruff@0.15.22 check packages/ava-skills
	uvx ruff@0.15.22 check packages/ava-open-harness packages/personal-graphify apps/scout-cli --exclude apps/scout-cli/.venv || true
	@echo "ava-skills is the HARD gate (at 0). The rest is the documented 252-finding debt."

# `ruff format --check` is deliberately absent. It was here as `... || true`, which is a
# suppressed check — nothing in this repo satisfies it, so it could only ever be noise or a
# permanently red gate. ci.yml removed it for the same reason. Re-add it scoped and
# blocking only after a reformat has actually landed.

gates:
	uv run python scripts/gate_audit.py --check --baseline scripts/gate_audit_baseline.json
	uv run python scripts/check_declared_capabilities.py --check --baseline scripts/declared_capabilities_baseline.json
	uv run python scripts/check_documented_counts.py --check

forge:
	cd apps/scout-cli && uv run python -m bigbang.cli --json forge list

doctor:
	cd apps/scout-cli && uv run python -m bigbang.cli --json system doctor

status:
	python apps/ava-factory/scripts/dottie_continuous_loop.py --mode monitor || cat apps/ava-factory/reports/dottie_live_status.json 2>/dev/null | tail -n 20 || echo "no status"

ci: lint gates test forge doctor
	@echo "CI green ✓ — telemetry hygiene"
	@if git ls-files | grep -E "dottie_live_status|dottie_telemetry|STATUS.json|results.tsv" ; then echo "FAIL: telemetry still tracked"; exit 1; fi
	@echo "Telemetry clean ✓"
