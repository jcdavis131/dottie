"""Tests for branch_anneal — real asserts on BRANCH_CONFIGS"""
import importlib.util, pathlib, pytest, sys
MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/branch_anneal.py"

def load():
    spec = importlib.util.spec_from_file_location("branch_anneal", MOD_PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m

mod = load()

def test_branch_configs_keys():
    assert hasattr(mod, "BRANCH_CONFIGS")
    cfg = mod.BRANCH_CONFIGS
    assert isinstance(cfg, dict)
    assert set(cfg.keys()) == {"code","math","chat"}

def test_each_branch_has_data_and_eval():
    for k,v in mod.BRANCH_CONFIGS.items():
        assert "data" in v and "eval" in v, f"{k} missing"
        assert isinstance(v["data"], str) and len(v["data"]) > 5
        assert isinstance(v["eval"], list) and len(v["eval"]) >= 2

def test_eval_lists_contain_strings():
    for br in ["code","math","chat"]:
        evals = mod.BRANCH_CONFIGS[br]["eval"]
        assert all(isinstance(x, str) for x in evals)

def test_main_callable_and_argparse():
    assert callable(mod.main)
    import inspect
    sig = inspect.signature(mod.main)
    assert len(sig.parameters) == 0

def test_main_creates_mock_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import sys
    sys.argv = ["branch_anneal.py","--branch","code","--steps","10","--stable_ckpt","nonexist.pt"]
    mod.main()
    out = tmp_path / "dottie_code_final_800k.pt"
    assert out.exists()
    assert "code" in out.read_text()
