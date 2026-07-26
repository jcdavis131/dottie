
"""Tests for convert_to_hf — verifies config.json and README creation"""
import importlib.util, pathlib, json, sys, pytest

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/convert_to_hf.py"
spec = importlib.util.spec_from_file_location("convert_to_hf", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def test_main_exists():
    assert hasattr(mod, "main") and callable(mod.main)

def test_convert_creates_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ckpt = tmp_path / "dummy.pt"
    ckpt.write_text("ckpt")
    out = tmp_path / "hf_out"
    sys_argv_old = sys.argv
    sys.argv = ["convert_to_hf.py","--ckpt", str(ckpt),"--out", str(out)]
    try:
        mod.main()
    finally:
        sys.argv = sys_argv_old
    cfg = out / "config.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert data["hidden_size"] == 2048
    assert data["num_layers"] == 48
    assert data["model_type"] == "ava"
    readme = out / "README.md"
    assert readme.exists()
    assert str(ckpt) in readme.read_text() or "Converted" in readme.read_text()

def test_convert_default_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ckpt = tmp_path / "ckpt.pt"
    ckpt.write_text("x")
    sys.argv = ["convert_to_hf.py","--ckpt", str(ckpt)]
    mod.main()
    default_out = tmp_path / "hf_model"
    assert default_out.exists()
    assert (default_out / "config.json").exists()

def test_config_json_valid_json_structure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sys.argv = ["convert_to_hf.py","--ckpt","a.pt","--out", str(tmp_path/"o2")]
    mod.main()
    data = json.loads((tmp_path/"o2"/"config.json").read_text())
    assert isinstance(data, dict)
    assert "hidden_size" in data
