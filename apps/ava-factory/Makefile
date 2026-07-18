.PHONY: help images volumes up down logs ps bench train serve report test smoke clean-consumed

AVA_PRESET ?= nano
COMPOSE    := docker compose

help:
	@echo "Ava continuous pipeline"
	@echo "  make volumes        create the five external named volumes"
	@echo "  make images         build ava/cpu and ava/gpu"
	@echo "  make up             start the whole pipeline (gather+clean+train+serve)"
	@echo "  make up-data        data plane only (collector + curator)"
	@echo "  make down           stop everything"
	@echo "  make logs           follow trainer logs"
	@echo "  make ps             pipeline status + shard counts by state"
	@echo "  make bench          measure collector/curator/trainer throughput"
	@echo "  make train          one-off trainer run in the foreground"
	@echo "  make serve          serve latest checkpoint on :8000"
	@echo "  make report         regenerate reports/index.html"
	@echo "  make test           run the full test suite (in the cpu image)"
	@echo "  make smoke          end-to-end nano smoke test"

# Docker creates named volumes root-owned; our containers run as uid 1000 (ava).
# Without the chown the manifest cannot create /state/manifest.db. Idempotent.
volumes:
	@for v in ava_raw ava_packed ava_ckpt ava_state ava_reports; do \
		docker volume create $$v >/dev/null; done
	@docker run --rm --user 0 \
		-v ava_raw:/raw -v ava_packed:/packed -v ava_ckpt:/ckpt \
		-v ava_state:/state -v ava_reports:/reports \
		busybox:latest sh -c 'chown -R 1000:1000 /raw /packed /ckpt /state /reports' \
		&& echo "volumes ready (owned by uid 1000)"

images:
	$(COMPOSE) build

up: volumes
	AVA_PRESET=$(AVA_PRESET) $(COMPOSE) up -d

up-data: volumes
	AVA_PRESET=$(AVA_PRESET) $(COMPOSE) up -d collector curator janitor

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f trainer

ps:
	@$(COMPOSE) ps
	@echo "--- shards by state ---"
	@docker run --rm -v ava_state:/state ava/cpu:latest \
		python -m ava.pipeline.manifest --summary

# scripts/ is not baked into the images (Dockerfile copies ava/configs/evals only).
# Bind-mount scripts + data so the bench runs without a rebuild.
# NOTE: ava/gpu currently lacks datasketch (CPU-image dep). Until the GPU image
# is rebuilt with datasketch, prefer host:
#   python scripts/bench_pipeline.py --preset nano --device cuda
bench:
	docker run --rm --gpus all \
		-v "$(CURDIR)/scripts:/app/scripts:ro" \
		-v "$(CURDIR)/data:/app/data:ro" \
		-v "$(CURDIR)/ava:/app/ava:ro" \
		-v "$(CURDIR)/configs:/app/configs:ro" \
		-v "$(CURDIR)/reports:/app/reports" \
		-e AVA_TOKENIZER=/app/data/$(AVA_PRESET)/tokenizer/ava_$(AVA_PRESET)_bpe.json \
		-e PYTHONPATH=/app \
		ava/gpu:latest python scripts/bench_pipeline.py --preset $(AVA_PRESET)

train:
	AVA_PRESET=$(AVA_PRESET) $(COMPOSE) run --rm trainer

serve:
	$(COMPOSE) up -d server && \
	echo "serving on http://localhost:8000  (viewer: /jspace/viewer, report: /report)"

report:
	docker run --rm \
		-v "$(CURDIR)/scripts:/app/scripts:ro" \
		-v "$(CURDIR)/configs:/app/configs:ro" \
		-v "$(CURDIR)/reports:/reports" \
		-e PYTHONPATH=/app \
		ava/cpu:latest python scripts/make_report.py --runs /reports --out /reports/index.html --eval /reports/branch_eval_results_real.json

# The two images carry disjoint deps on purpose (see tests/conftest.py), so the
# full suite is the union of both runs.
test: test-cpu test-gpu

test-cpu:
	docker run --rm -v "$(CURDIR)/tests:/app/tests:ro" -v "$(CURDIR)/ava:/app/ava:ro" \
		-v "$(CURDIR)/evals:/app/evals:ro" -v "$(CURDIR)/configs:/app/configs:ro" \
		ava/cpu:latest python -m pytest tests/ -q

test-gpu:
	docker run --rm --gpus all -v "$(CURDIR)/tests:/app/tests:ro" -v "$(CURDIR)/ava:/app/ava:ro" \
		-v "$(CURDIR)/evals:/app/evals:ro" -v "$(CURDIR)/configs:/app/configs:ro" \
		-v "$(CURDIR)/data:/app/data:ro" -v "$(CURDIR)/reports:/app/reports:ro" \
		-v "$(CURDIR)/model_1b.py:/app/model_1b.py:ro" \
		-v "$(CURDIR)/multi_jspace_module.py:/app/multi_jspace_module.py:ro" \
		ava/gpu:latest python -m pytest tests/ -q

smoke:
	bash scripts/smoke_e2e.sh
