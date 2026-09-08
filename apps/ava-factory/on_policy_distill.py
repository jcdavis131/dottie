"""Retired Ava on-policy distillation command.

The former implementation documented MOPD, privileged self-distillation,
earlier-teacher restoration, and off-policy distillation research patterns.
It was not connected to Ava's canonical configuration and shard-provenance
contracts, so executing it could produce artifacts with an untrustworthy data
identity. The compatibility CLI is intentionally retained only to fail closed.
"""

from __future__ import annotations

import argparse
from typing import NoReturn, Sequence


UNAVAILABLE_MESSAGE = (
    "on-policy distillation is unavailable until it is ported to the canonical "
    "dottie.config + Manifest/StreamingShardSampler provenance pipeline and the "
    "external tokenizers CVE/assets blockers clear; no model, data, checkpoint, "
    "log, metric, evaluation hook, or output artifact was accessed or written"
)


def build_parser() -> argparse.ArgumentParser:
    """Preserve the legacy command's argument and help surface."""
    parser = argparse.ArgumentParser(
        description=(
            "Ava on-policy distillation (retired; fail-closed until canonical "
            "configuration, provenance, and external security gates are complete)"
        )
    )
    parser.add_argument(
        "--mode",
        default="mopd",
        choices=["mopd", "privileged", "earlier", "offpolicy"],
    )
    parser.add_argument(
        "--student-ckpt", default="checkpoints/base1b/ava_stable_736k.pt"
    )
    parser.add_argument("--student-config", default="configs/base1b.yaml")
    parser.add_argument("--teacher-config", default=None)
    parser.add_argument(
        "--teachers",
        default=(
            "code:checkpoints/code/exp.pt,"
            "math:checkpoints/math/exp.pt,"
            "chat:checkpoints/chat/exp.pt"
        ),
    )
    parser.add_argument("--hint", default="")
    parser.add_argument("--data_root", default="data/streaming_shards")
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--seq_len", type=int, default=2048)
    parser.add_argument("--tokens_total", type=int, default=500_000_000)
    parser.add_argument("--lr", type=float, default=8e-5)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--preserve-router", action="store_true", default=True)
    parser.add_argument(
        "--no-preserve-router", dest="preserve_router", action="store_false"
    )
    parser.add_argument("--router-weight", type=float, default=0.1)
    parser.add_argument("--offpolicy-alpha", type=float, default=0.5)
    parser.add_argument("--earlier-kl-weight", type=float, default=0.7)
    parser.add_argument("--earlier-ce-weight", type=float, default=0.3)
    parser.add_argument("--deepspeed", default="deepspeed_zero3_bf16.json")
    parser.add_argument(
        "--no-deepspeed", dest="deepspeed", action="store_const", const=""
    )
    parser.add_argument(
        "--optimizer", default="adamw8bit", choices=["adamw", "adamw8bit"]
    )
    parser.add_argument("--gradient-checkpointing", action="store_true", default=True)
    parser.add_argument(
        "--no-gradient-checkpointing",
        dest="gradient_checkpointing",
        action="store_false",
    )
    parser.add_argument("--compile", action="store_true", default=True)
    parser.add_argument("--no-compile", dest="compile", action="store_false")
    parser.add_argument("--grad-clip", type=float, default=1.0)
    parser.add_argument("--shuffle_buffer", type=int, default=10000)
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument("--ckpt-every", type=int, default=500)
    parser.add_argument("--eval-every", type=int, default=1000)
    parser.add_argument("--use-wsd", action="store_true", default=True)
    parser.add_argument("--no-wsd", dest="use_wsd", action="store_false")
    return parser


def train_loop(args: argparse.Namespace | object | None = None) -> NoReturn:
    """Refuse legacy training before any model, data, or output access."""
    del args
    raise RuntimeError(UNAVAILABLE_MESSAGE)


def main(argv: Sequence[str] | None = None) -> NoReturn:
    """Parse legacy arguments, then deterministically fail closed."""
    args = build_parser().parse_args(argv)
    train_loop(args)


if __name__ == "__main__":
    main()
