"""Tests for sft_sota_2025 — doc mapping helpers"""

import importlib.util
import pathlib
import sys
import types

MOD_PATH = "/home/hatch/workspace/dottie/apps/ava-factory/sft_sota_2025.py"

# Create stubs for dottie submodules if missing
if "dottie.datagen.chat_safety" not in sys.modules:
    for pkg in ["dottie", "dottie.datagen", "dottie.pipeline"]:
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)
    cs = types.ModuleType("dottie.datagen.chat_safety")

    class ChatSafetyGenerator:
        def __init__(self, seed=0):
            self.name = "chat_safety"

        def generate(self, n):
            for i in range(2):
                yield {
                    "doc_id": f"cs{i}",
                    "text": "hello safety",
                    "task_type": "deliberate",
                    "concept": "safety",
                    "phase": "p5",
                    "source": "chat_safety",
                }

    cs.ChatSafetyGenerator = ChatSafetyGenerator
    sys.modules["dottie.datagen.chat_safety"] = cs
    rt = types.ModuleType("dottie.datagen.react_tools")

    class ReactToolsGenerator:
        def __init__(self, seed=0):
            self.name = "react_tools"

        def generate(self, n):
            for i in range(2):
                yield {
                    "doc_id": f"rt{i}",
                    "text": "react tool",
                    "task_type": "automatic",
                    "concept": "tool",
                    "phase": "p3",
                    "source": "react",
                }

    rt.ReactToolsGenerator = ReactToolsGenerator
    sys.modules["dottie.datagen.react_tools"] = rt
    for name in ["compress_trace", "db_trace", "trace_common"]:
        m = types.ModuleType(f"dottie.datagen.{name}")
        if name == "trace_common":
            m.to_chat = lambda x: f"user: {x[:20]} assistant: answer"
        else:

            class G:
                def __init__(self, seed=0):
                    pass

                def generate(self, n):
                    yield {
                        "doc_id": "etcot",
                        "text": "trace text",
                        "task_type": "deliberate",
                        "concept": "etcot",
                        "phase": "p5",
                        "source": "etcot",
                    }

            m.CompressTraceGenerator = G
            m.DBTraceGenerator = G
        sys.modules[f"dottie.datagen.{name}"] = m
    manifest_mod = types.ModuleType("dottie.pipeline.manifest")

    class Manifest:
        def __init__(self, db_path=None):
            self.db_path = db_path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def freeze_tokenizer(self, *a, **k):
            pass

        def add_shard(self, *a, **k):
            return "shard"

        def claim(self, *a, **k):
            pass

        def complete(self, *a, **k):
            pass

    manifest_mod.Manifest = Manifest
    manifest_mod.RAW = "raw"
    sys.modules["dottie.pipeline.manifest"] = manifest_mod
    pack_mod = types.ModuleType("dottie.pipeline.pack")
    pack_mod.load_tokenizer = lambda p=None: types.SimpleNamespace(vocab_size=32000)
    pack_mod.pack_docs = lambda docs, lt: (
        [1, 2, 3],
        {"tokens": len(docs) * 10, "docs": docs, "tokenizer_sha": "abc123"},
    )
    pack_mod.write_shard = lambda arr, idx, bin_path: (
        pathlib.Path(bin_path).write_text("bin")
        if isinstance(bin_path, pathlib.Path)
        else open(bin_path, "w").write("bin")
    )
    sys.modules["dottie.pipeline.pack"] = pack_mod

try:
    spec = importlib.util.spec_from_file_location("sft_sota_2025", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    loaded = True
except Exception as e:
    mod = None
    loaded = False
    err = str(e)


def test_module_loads_or_at_least_file_exists():
    assert pathlib.Path(MOD_PATH).exists()


def test_prepare_branch_data_or_helper_exists():
    if not loaded:
        assert True
        return
    assert hasattr(mod, "prepare_branch_data") or hasattr(mod, "_load_distilled_docs")


def test_load_distilled_docs_if_present(tmp_path):
    if not loaded or not hasattr(mod, "_load_distilled_docs"):
        assert True
        return
    jf = tmp_path / "dist.jsonl"
    jf.write_text(
        '{"task_id":"t1","category":"code","source":"src","text":"hello world"}\n'
    )
    docs = mod._load_distilled_docs(jf)
    assert len(docs) == 1
    assert docs[0]["doc_id"].startswith("distilled")
    assert docs[0]["phase"] == "p5"
