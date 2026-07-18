# Solo personal project, no connection to employer, built with public/free-tier only
FROM pytorch/pytorch:2.4.0-cuda12.4-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV WANDB_MODE=offline
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
ENV OLLAMA_HOST=http://host.docker.internal:11434
ENV HF_HUB_ENABLE_HF_TRANSFER=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git git-lfs build-essential curl tmux htop \
    python3-dev libssl-dev libffi-dev jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt /workspace/requirements.txt

RUN pip install --upgrade pip && \
    pip install torch --index-url https://download.pytorch.org/whl/cu124 && \
    pip install -r requirements.txt && \
    pip install bitsandbytes>=0.43.0 einops accelerate safetensors tiktoken chonkie \
    ninja packaging wheel websockets hf_transfer \
    pandas pyarrow huggingface_hub datasets prefect==3.4.0 boto3 scikit-learn && \
    pip install flash-attn --no-build-isolation || echo "flash-attn build failed, using torch SDPA fallback"

COPY . /workspace

EXPOSE 8000
CMD ["/bin/bash"]
