"""Typed config tree over configs/{nano,mini,base1b}.yaml.

The YAML files are the authoritative schema. This module mirrors their nested
sections (`model:`, `jspace:`, `training:`, `phases:`, `branch_chat:`, ...) as
dataclasses so that a typo in a key is a load-time error rather than a silent
default three hours into a training run.

Space keys are `system1 / system2 / critic / planner` everywhere -- matching
`DottieModel1B.freeze_spaces()` and the blueprint's BRANCH_CONFIGS.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

SPACES = ("system1", "system2", "critic", "planner")
TASK_TYPES = ("automatic", "deliberate", "safety", "temporal")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = Path(os.environ.get("DOTTIE_CONFIG_DIR", os.environ.get("AVA_CONFIG_DIR", _REPO_ROOT / "configs")))


class ConfigError(ValueError):
    pass


def _strict(section: str, data: Mapping[str, Any], cls: type) -> dict:
    """Reject unknown keys: catch typos at load, not at step 40,000."""
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"{section}: unknown key(s) {sorted(unknown)}; known: {sorted(known)}")
    return dict(data)


@dataclasses.dataclass(frozen=True)
class ModelConfig:
    vocab_size: int
    d_model: int
    n_heads: int
    head_dim: int
    n_text_layers: int
    n_fusion_layers: int
    n_reasoning_layers: int
    tie_lm_head: bool = True
    tie_verbalizer: bool = True
    multimodal: bool = False
    qk_norm: bool = True
    rope_base_init: int = 10000
    n_kv_heads: int | None = None
    mlp: str = "gelu"
    mlp_mult: int = 4
    mlp_ratio: float | None = None
    jspace_num_heads: int = 4
    rope_type: str = "yarn"
    n_sinks: int = 0
    use_peri_ln: bool = False
    use_short_conv: bool = False
    use_relative: bool = False
    relative_max_distance: int = 128
    # MoE config (Inkling/DeepSeek-V3)
    use_moe: bool = False
    moe_n_routed_experts: int = 32
    moe_n_shared_experts: int = 2
    moe_top_k: int = 2
    moe_every_n: int = 2
    moe_hidden_ratio: float | None = None
    moe_norm_type: str = "softmax"
    moe_routing_lr: float = 1e-3
    # Effort conditioning
    use_effort: bool = False

    def __post_init__(self) -> None:
        if self.n_heads * self.head_dim != self.d_model:
            raise ConfigError(
                f"n_heads*head_dim ({self.n_heads}*{self.head_dim}="
                f"{self.n_heads * self.head_dim}) != d_model ({self.d_model})"
            )
        kv = self.n_kv_heads or self.n_heads
        if self.n_heads % kv:
            raise ConfigError(f"n_heads ({self.n_heads}) must be divisible by n_kv_heads ({kv})")
        if self.mlp not in ("gelu", "swiglu"):
            raise ConfigError(f"mlp must be 'gelu' or 'swiglu', got {self.mlp!r}")
        if self.rope_type not in ("yarn", "longrope2", "relative"):
            raise ConfigError(f"rope_type must be 'yarn' or 'longrope2' or 'relative', got {self.rope_type!r}")
        if self.n_sinks < 0:
            raise ConfigError(f"n_sinks must be >= 0, got {self.n_sinks}")
        if self.relative_max_distance <= 0:
            raise ConfigError(f"relative_max_distance must be >0, got {self.relative_max_distance}")
        if self.moe_n_routed_experts < 1:
            raise ConfigError(f"moe_n_routed_experts must be >=1")
        if self.moe_top_k < 1 or self.moe_top_k > self.moe_n_routed_experts:
            raise ConfigError(f"moe_top_k must be in [1, n_routed]")
        # Packed token shards are uint16; a larger vocab would silently wrap.
        if self.vocab_size > 65535:
            raise ConfigError(f"vocab_size {self.vocab_size} > 65535 breaks uint16 token packing")
        # Alias handling: use_relative True implies relative rope
        if self.use_relative and self.rope_type != "relative":
            # dataclass frozen, cannot mutate, but allow both: treat use_relative as alias
            # Validation will accept relative anyway; if user set use_relative True but yarn, we treat as relative intent
            # Can't override frozen field, but downstream build_model will normalize
            pass

    @property
    def kv_heads(self) -> int:
        return self.n_kv_heads or self.n_heads

    @property
    def n_layers(self) -> int:
        return self.n_text_layers + self.n_fusion_layers + self.n_reasoning_layers


@dataclasses.dataclass(frozen=True)
class JSpaceConfig:
    slots: dict[str, int]
    half_life: dict[str, float]
    hl_weight: dict[str, float]
    broadcast_target: dict[str, float]
    routing_targets: dict[str, list[float]]
    base_loss_weights: dict[str, float]
    j_weight: dict[str, float]
    s2_verbalizable_mass: float = 0.065
    critic_vm: float = 0.08
    inter_mi_cos_target: float = 0.45
    inter_mi_weight: float = 0.3
    routing_weight: float = 0.4
    # The workspace is chunk-recurrent so it stays causal (see multi_jspace_module
    # docstring). Smaller chunks = fresher broadcast, more sequential steps.
    causal: bool = True
    chunk_size: int = 128

    def __post_init__(self) -> None:
        for field in ("slots", "half_life", "hl_weight", "broadcast_target"):
            keys = set(getattr(self, field))
            if keys != set(SPACES):
                raise ConfigError(f"jspace.{field} keys {sorted(keys)} != {sorted(SPACES)}")
        if set(self.routing_targets) != set(TASK_TYPES):
            raise ConfigError(f"jspace.routing_targets keys != {sorted(TASK_TYPES)}")
        for tt, probs in self.routing_targets.items():
            if len(probs) != 4 or abs(sum(probs) - 1.0) > 1e-6:
                raise ConfigError(f"routing_targets[{tt}] must be 4 probs summing to 1, got {probs}")

    def j_weight_for_phase(self, phase: int) -> float:
        """Blueprint: 0.08 for the early phases (P0-P2), 0.15 for reasoning/long (P3+)."""
        return self.j_weight["early"] if phase <= 2 else self.j_weight["late"]


@dataclasses.dataclass(frozen=True)
class WSDConfig:
    warmup_steps: int
    stable_frac: float
    lr_max: float
    lr_min: float


@dataclasses.dataclass(frozen=True)
class OptimizerConfig:
    name: str = "adamw"
    betas: tuple[float, float] = (0.9, 0.95)
    weight_decay: float = 0.1
    grad_clip: float = 1.0


@dataclasses.dataclass(frozen=True)
class TrainingConfig:
    device: str
    precision: str
    wsd: WSDConfig
    optimizer: OptimizerConfig
    tokens_per_step: int
    tokens_total: int | None = None
    threads: int | None = None
    compile: bool = False
    gradient_checkpointing: bool = False
    checkpoint_every_steps: int = 250
    metrics_every_steps: int = 10
    stable_ckpt_name: str = "stable.pt"
    final_ckpt_name: str = "final.pt"


@dataclasses.dataclass(frozen=True)
class PhaseConfig:
    name: str
    seq: int
    rope_base: int
    mix: dict[str, float]
    tokens: int | None = None
    frac: float | None = None
    ntk: float = 1.0
    yarn: bool = False

    @property
    def index(self) -> int:
        return int(self.name.split("_")[0].lstrip("p"))


@dataclasses.dataclass(frozen=True)
class DottieConfig:
    preset: str
    model: ModelConfig
    jspace: JSpaceConfig
    training: TrainingConfig
    phases: list[PhaseConfig]
    data: dict[str, Any] = dataclasses.field(default_factory=dict)
    branch_chat: dict[str, Any] | None = None
    branches: dict[str, Any] | None = None
    milestones: list[dict[str, Any]] | None = None

    # -- loading ------------------------------------------------------------

    @classmethod
    def load(cls, preset: str, config_dir: str | Path | None = None) -> "DottieConfig":
        d = Path(config_dir or _CONFIG_DIR)
        path = d / f"{preset}.yaml"
        if not path.exists():
            available = sorted(p.stem for p in d.glob("*.yaml"))
            raise FileNotFoundError(f"no preset {preset!r} at {path}; available: {available}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DottieConfig":
        try:
            model = ModelConfig(**_strict("model", raw["model"], ModelConfig))
            jspace = JSpaceConfig(**_strict("jspace", raw["jspace"], JSpaceConfig))

            t = dict(raw["training"])
            wsd = WSDConfig(**_strict("training.wsd", t.pop("wsd"), WSDConfig))
            opt_raw = dict(t.pop("optimizer", {}))
            if "betas" in opt_raw:
                opt_raw["betas"] = tuple(opt_raw["betas"])
            optimizer = OptimizerConfig(**_strict("training.optimizer", opt_raw, OptimizerConfig))
            training = TrainingConfig(
                wsd=wsd, optimizer=optimizer, **_strict("training", t, TrainingConfig)
            )

            phases = [PhaseConfig(**_strict("phases[]", p, PhaseConfig)) for p in raw["phases"]]
        except KeyError as e:
            raise ConfigError(f"missing required section {e}") from e

        return cls(
            preset=raw["preset"], model=model, jspace=jspace, training=training, phases=phases,
            data=raw.get("data", {}), branch_chat=raw.get("branch_chat"),
            branches=raw.get("branches"), milestones=raw.get("milestones"),
        )

    # -- derived ------------------------------------------------------------

    def phase(self, index: int) -> PhaseConfig:
        return self.phases[index]

    def total_steps(self) -> int:
        total = self.training.tokens_total
        if total is None:
            raise ConfigError(f"{self.preset}: tokens_total unset (milestone presets set it per milestone)")
        return max(1, total // self.training.tokens_per_step)

    def analytic_param_count(self) -> int:
        """Parameter count without building the model (works without torch).

        Cross-checked against the built model in tests/test_model.py; they must
        agree within 10%.
        """
        m = self.model
        d, v = m.d_model, m.vocab_size

        embed = v * d * (1 if m.tie_lm_head else 2)

        kv = m.kv_heads
        attn = d * d + 2 * (kv * m.head_dim * d) + d * d          # q, k, v, o
        if m.mlp == "swiglu":
            hidden = int((m.mlp_ratio or 4.0) * d)
            mlp = 3 * d * hidden
        else:
            mlp = 2 * d * (m.mlp_mult * d)
        per_layer = attn + mlp + 2 * d                             # + 2 RMSNorms
        layers = m.n_layers * per_layer

        # Multi-J-Space: 4 workspaces (2 MHA each = 4d^2 apiece, gate + broadcast
        # proj = 2d^2), 4 cross-attentions, router, arbitration. Verbalizer tied.
        ws = sum(
            (4 * d * d) + (4 * d * d) + (d * d + d) + (d * d + d) + slots * d
            for slots in m_slots(self)
        )
        cross = 4 * (4 * d * d)
        router = d * 128 + 128 * 4
        arbitration = (2 * d) * 128 + 128
        verbalizer = 0 if m.tie_verbalizer else 4 * v * d

        return embed + layers + ws + cross + router + arbitration + verbalizer


def m_slots(cfg: DottieConfig) -> Sequence[int]:
    return [cfg.jspace.slots[s] for s in SPACES]


def load(preset: str, config_dir: str | Path | None = None) -> DottieConfig:
    return DottieConfig.load(preset, config_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description="Dottie config")
    ap.add_argument("--preset", required=True)
    ap.add_argument("--count-params", action="store_true")
    ap.add_argument("--analytic", action="store_true", help="skip building the model")
    args = ap.parse_args()

    try:
        cfg = DottieConfig.load(args.preset)
    except (FileNotFoundError, ConfigError) as e:
        print(f"error: {e}")
        return 2

    if not args.count_params:
        print(f"preset={cfg.preset} d_model={cfg.model.d_model} layers={cfg.model.n_layers} "
              f"vocab={cfg.model.vocab_size}")
        return 0

    if args.analytic:
        n = cfg.analytic_param_count()
        src = "analytic"
    else:
        try:
            from dottie.model import build_model
            n = sum(p.numel() for p in build_model(cfg).parameters())
            src = "built"
        except ImportError:
            n = cfg.analytic_param_count()
            src = "analytic (torch unavailable)"

    print(f"preset={cfg.preset} params={n} (~{n/1e6:.1f}M) [{src}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
