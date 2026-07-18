"""Unit tests for pure-CPU pieces of train.py."""

import math

import pytest
import torch

import prepare
import train


# --- _resolve_gpu_profile tier boundaries ---------------------------------

ADA = (8, 9)
TURING = (7, 5)


def resolve(name="NVIDIA GeForce RTX 4080", cc=ADA, vram=16.0, is_windows=True):
    return train._resolve_gpu_profile(name, cc, vram, is_windows)


def test_16gb_card_underreporting_lands_in_ada_16gb():
    profile = resolve(vram=15.99)
    assert profile.name == "ada-16gb"
    assert profile.train_batch_candidates == (32, 16, 8, 4)
    assert profile.default_checkpointing is False


def test_24gb_card_underreporting_lands_in_ada_24gb_plus():
    profile = resolve(name="NVIDIA GeForce RTX 4090", vram=23.99)
    assert profile.name == "ada-24gb-plus"
    assert profile.train_batch_candidates == (64, 32, 16, 8, 4)


def test_exact_boundaries_keep_documented_tier():
    assert resolve(vram=16.0).name == "ada-16gb"
    assert resolve(name="RTX 4090", vram=24.0).name == "ada-24gb-plus"


def test_mid_tier_ada_12gb():
    profile = resolve(name="NVIDIA GeForce RTX 4070", vram=11.99)
    assert profile.name == "ada-10-15gb"
    assert profile.train_batch_candidates == (16, 8, 4)
    assert profile.default_checkpointing is True
    assert profile.eval_batch_cap == 16  # profile default


def test_below_16gb_tolerance_band_stays_mid_tier():
    # 15.4 is below the 15.5 tolerance boundary: still mid-tier
    assert resolve(vram=15.4).name == "ada-10-15gb"


def test_turing_low_vram_tier():
    profile = resolve(name="NVIDIA GeForce RTX 2070", cc=TURING, vram=8.0)
    assert profile.name == "turing-8-11gb"
    assert profile.eval_batch_cap == 4
    assert profile.checkpoint_modes == (True,)


def test_turing_12gb_underreporting_lands_in_mid_tier():
    profile = resolve(name="RTX 2080 Ti", cc=TURING, vram=11.99)
    assert profile.name == "turing-12-15gb"


def test_non_rtx_falls_to_compatibility():
    profile = resolve(name="NVIDIA A100-SXM4-40GB", cc=(8, 0), vram=40.0)
    assert profile.name == "compatibility"
    assert profile.is_compatibility_only is True


def test_laptop_falls_to_compatibility():
    profile = resolve(name="NVIDIA GeForce RTX 4080 Laptop GPU", vram=12.0)
    assert profile.name == "compatibility"


def test_below_vram_floor_falls_to_compatibility():
    profile = resolve(name="RTX 3080", cc=(8, 6), vram=8.0)  # ampere floor is 10GB
    assert profile.name == "compatibility"


# --- _get_gpu_peak_flops ---------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("NVIDIA GeForce RTX 4090", 330.3e12),
        ("NVIDIA GeForce RTX 4090 D", 280.0e12),
        ("NVIDIA GeForce RTX 4080", 242.5e12),
        ("NVIDIA GeForce RTX 4080 SUPER", 260.0e12),
        ("NVIDIA GeForce RTX 5090", 360.0e12),
        ("NVIDIA GeForce RTX 3060", 51.0e12),
        ("Totally Unknown GPU", None),
    ],
)
def test_get_gpu_peak_flops(name, expected):
    assert train._get_gpu_peak_flops(name) == expected


# --- autotune cache round-trip --------------------------------------------

def test_autotune_cache_round_trip(tmp_path):
    path = tmp_path / "cache" / "gpu-profile-v2.json"
    entries = {
        "RTX 4080|8.9|17171480576|2.13|Windows|2048": {
            "train_batch_size": 32,
            "use_activation_checkpointing": False,
            "tok_per_sec": 123456.789,
            "peak_memory_bytes": 14000000000,
            "updated_unix": 1752537600,
        }
    }
    train._save_autotune_entries(path, entries)
    assert path.exists()
    assert train._load_autotune_entries(path) == entries


def test_autotune_cache_missing_file_returns_empty(tmp_path):
    assert train._load_autotune_entries(tmp_path / "nope.json") == {}


def test_autotune_cache_corrupt_file_returns_empty(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json!!")
    assert train._load_autotune_entries(path) == {}


def test_autotune_cache_non_dict_payload_returns_empty(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]")
    assert train._load_autotune_entries(path) == {}
    path.write_text('{"entries": [1, 2]}')
    assert train._load_autotune_entries(path) == {}


# --- _filter_train_batch_sizes divisibility --------------------------------

def test_filter_train_batch_sizes_keeps_divisible_candidates():
    # TOTAL_BATCH_SIZE = 2**19, MAX_SEQ_LEN = 2048 -> batch must divide 256
    assert train._filter_train_batch_sizes((64, 32, 16, 8, 4)) == [64, 32, 16, 8, 4]


def test_filter_train_batch_sizes_drops_non_divisible_and_invalid():
    assert train._filter_train_batch_sizes((3, 5, 0, -2, 8)) == [8]


def test_filter_train_batch_sizes_dedups_preserving_order():
    assert train._filter_train_batch_sizes((8, 8, 4, 8)) == [8, 4]


def test_filter_train_batch_sizes_raises_when_nothing_valid():
    with pytest.raises(RuntimeError):
        train._filter_train_batch_sizes((3, 5, 0))


# --- evaluate_bpb math on a constant-loss stub model -----------------------

class _ConstantLossModel:
    """Stub model returning a constant per-token loss of ln(2) nats."""

    def __init__(self, loss_nats):
        self.loss_nats = loss_nats

    def __call__(self, x, y, reduction="none"):
        assert reduction == "none"
        return torch.full((y.numel(),), self.loss_nats, dtype=torch.float32)


def test_evaluate_bpb_constant_loss(monkeypatch):
    batch_size = 2
    seq_len = prepare.MAX_SEQ_LEN

    def fake_loader(tokenizer, bs, sl, split, device=None, dataset=None):
        assert split == "val"
        while True:
            x = torch.zeros((bs, sl), dtype=torch.long)
            y = torch.ones((bs, sl), dtype=torch.long)
            yield x, y, 0

    # every token id maps to 2 bytes
    token_bytes = torch.full((prepare.VOCAB_SIZE,), 2, dtype=torch.long)
    monkeypatch.setattr(prepare, "make_dataloader", fake_loader)
    monkeypatch.setattr(prepare, "get_token_bytes", lambda device=None, dataset=None: token_bytes)

    model = _ConstantLossModel(loss_nats=math.log(2))
    tokenizer = type("Tok", (), {"dataset": "tinystories"})()
    bpb = prepare.evaluate_bpb(
        model,
        tokenizer,
        batch_size,
        device="cpu",
        dataset="tinystories",
        eval_tokens=batch_size * seq_len,  # exactly one step
    )
    # loss ln(2) nats/token over 2 bytes/token -> 0.5 bits per byte
    assert bpb == pytest.approx(0.5, rel=1e-6)


def test_evaluate_bpb_excludes_zero_byte_tokens(monkeypatch):
    batch_size = 1
    seq_len = prepare.MAX_SEQ_LEN

    def fake_loader(tokenizer, bs, sl, split, device=None, dataset=None):
        while True:
            x = torch.zeros((bs, sl), dtype=torch.long)
            # half the targets are token id 0 (zero bytes: special), half id 1 (2 bytes)
            y = torch.arange(sl, dtype=torch.long).remainder(2).unsqueeze(0)
            yield x, y, 0

    token_bytes = torch.full((prepare.VOCAB_SIZE,), 2, dtype=torch.long)
    token_bytes[0] = 0
    monkeypatch.setattr(prepare, "make_dataloader", fake_loader)
    monkeypatch.setattr(prepare, "get_token_bytes", lambda device=None, dataset=None: token_bytes)

    model = _ConstantLossModel(loss_nats=math.log(2))
    tokenizer = type("Tok", (), {"dataset": "tinystories"})()
    bpb = prepare.evaluate_bpb(
        model, tokenizer, batch_size, device="cpu", dataset="tinystories",
        eval_tokens=batch_size * seq_len,
    )
    # only the 1024 two-byte tokens count: (1024 * ln2) / (ln2 * 2048) = 0.5
    assert bpb == pytest.approx(0.5, rel=1e-6)


# --- misc runtime plumbing -------------------------------------------------

def test_runtime_config_has_no_use_compile_field():
    # constant-False use_compile plumbing was removed (audit finding 14)
    assert "use_compile" not in train.RuntimeConfig.__dataclass_fields__
    assert train.USE_COMPILE is False
