.PHONY: sync test lint forge doctor status ci

sync:
	uv sync
	uv run pre-commit install || true

test:
	uv run pytest packages/ava-skills -q
	uv run pytest packages/ava-open-harness -q
	uv run pytest apps/scout-cli/tests -q

lint:
	uv run ruff check packages/ava-skills packages/ava-open-harness packages/personal-graphify apps/scout-cli
	uv run ruff format --check packages/ava-skills packages/ava-open-harness packages/personal-graphify apps/scout-cli || true

forge:
	cd apps/scout-cli && uv run python -m bigbang.cli --json forge list

doctor:
	cd apps/scout-cli && uv run python -m bigbang.cli --json system doctor

status:
	python apps/ava-factory/scripts/dottie_continuous_loop.py --mode monitor || cat apps/ava-factory/reports/dottie_live_status.json 2>/dev/null | tail -n 20 || echo "no status"

ci: lint test forge doctor
	@echo "CI green ✓ — telemetry hygiene"
	@if git ls-files | grep -E "dottie_live_status|dottie_telemetry|STATUS.json|results.tsv" ; then echo "FAIL: telemetry still tracked"; exit 1; fi
	@echo "Telemetry clean ✓"
