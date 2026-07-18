# Solo personal project, no connection to employer, built with public/free-tier only
#
# Dottie service image. Build context is the DOTTIE MONOREPO ROOT (../.. from this file),
# so the dottie siblings Dottie integrates with ship inside the image at the same relative
# layout the resolution code expects (DOTTIE_ROOT=/dottie).
#
# torch is intentionally NOT installed (multi-GB): inside this container the ava backend and
# train-step refuse honestly; the ollama backend (the working brain) and the whole
# engine/API/flywheel-export/mint/eval-mock paths work. To enable the ava trainee in-container:
#   docker compose exec dottie pip install torch --index-url https://download.pytorch.org/whl/cpu
# and mount a checkpoint tree (see docker-compose.dottie.yml comments).

FROM python:3.11-slim

WORKDIR /dottie

# Only the siblings Dottie actually resolves at runtime — keeps the image lean.
COPY apps/ava-factory/ava            apps/ava-factory/ava
COPY apps/ava-factory/configs        apps/ava-factory/configs
COPY apps/ava-factory/scripts        apps/ava-factory/scripts
COPY apps/ava-factory/runs/cpu_pilot/tokenizer apps/ava-factory/runs/cpu_pilot/tokenizer
COPY packages/ava-open-harness       packages/ava-open-harness
COPY packages/ava-skills             packages/ava-skills
COPY apps/scout-cli/bigbang          apps/scout-cli/bigbang
COPY apps/dottie                     apps/dottie

# numpy + pyyaml: the eval harness (mock mode) needs them; dottie itself is in pyproject.
RUN pip install --no-cache-dir numpy pyyaml && \
    pip install --no-cache-dir ./apps/dottie

ENV DOTTIE_ROOT=/dottie \
    DOTTIE_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 8100

# stdlib healthcheck probe (slim image has no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/status', timeout=4)"]

CMD ["python", "-m", "dottie", "serve", "--host", "0.0.0.0", "--port", "8100"]
