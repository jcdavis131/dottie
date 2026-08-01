# Ava serve image (Stage 8 self-host package).
# Two-stage: builder installs into /opt/venv; runtime copies venv + app code.
# Checkpoints are NOT baked in - mount runs/ and set AVA_CKPT.
#
# CPU (default):
#   docker build -t ava-serve .
# CUDA wheels:
#   docker build -t ava-serve --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 .
#
# Primary multi-service path remains docker-compose.yml + docker/Dockerfile.gpu.
# This image is the slim single-process serve package from specs/07.

ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

FROM python:3.11-slim AS builder
ARG TORCH_INDEX
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# Torch from the chosen index; remaining deps from PyPI.
RUN pip install --no-cache-dir \
        "torch" --index-url "${TORCH_INDEX}" \
 && pip install --no-cache-dir \
        "fastapi>=0.110" "uvicorn[standard]>=0.27" "pydantic>=2" \
        "numpy" "pyyaml" "safetensors" "tokenizers" "httpx"

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    AVA_CKPT=/app/runs/chat/ava_nano_chat.pt
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# dottie/ is the real package since the Ava->Dottie rename; ava/ is the compat shim
# (`from dottie import *`). server.py:23 does `from dottie.serve_engine import get_engine`
# at MODULE level, so without this line the container dies at boot with
# ModuleNotFoundError. docker/Dockerfile.gpu:28-30 carries this same COPY and the same
# warning; this slim image simply never got it, and compose builds docker/Dockerfile.{cpu,gpu}
# rather than this file, so nothing exercised the omission. Flagged in the 2026-07-22
# review (knowledge/reviews/factory.md), fixed 2026-08-01.
COPY dottie/ /app/dottie/
COPY ava/ /app/ava/
COPY evals/ /app/evals/
COPY multi_jspace_module.py /app/multi_jspace_module.py
COPY server.py /app/server.py
COPY scripts/ /app/scripts/
COPY configs/ /app/configs/
# Needs the `!data/nano/tokenizer/` negation in .dockerignore: `data/` is excluded there,
# and a COPY whose source is fully dockerignored is a hard build failure, not a skip.
COPY data/nano/tokenizer/ /app/data/nano/tokenizer/
# REMOVED 2026-08-01: `COPY reports/ /app/reports/`, commented "optional ... when present
# at build time". It could never be present: .dockerignore excludes `reports/` outright,
# under the heading "these live in named volumes, never in the image" — and compose does
# mount `ava_reports:/reports`. So the line contradicted the project's own design AND broke
# the build, while its comment implied a graceful no-op. Deleted rather than negated,
# because the named volume is the intended source. Do not re-add without also removing the
# .dockerignore entry and deciding which of the two is authoritative.
RUN useradd -m -u 1000 ava \
 && mkdir -p /app/runs \
 && chown -R ava:ava /app
USER ava
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
