"""API alignment between train_1b_deepspeed.py and model_1b.get_model.

Non-mock ``train_1b_deepspeed.py --branch code --max_steps 50`` failed with:

1. TypeError: get_model() got an unexpected keyword argument 'critical_shift'
2. After the trainer's TypeError fallback: NameError: name 'use_short_conv'
   is not defined (get_model body referenced compression flags that were
   never parameters and that DottieModel1B does not accept).

This file is torch-free on purpose: it must run in the CPU image and must
not start a GPU train. It parses the two sources and checks the factory
can bind the trainer kwargs without executing a 1B construct.
"""

from __future__ import annotations

import ast
from pathlib import Path

_FACTORY = Path(__file__).resolve().parent.parent
_MODEL = _FACTORY / "model_1b.py"
_TRAINER = _FACTORY / "train_1b_deepspeed.py"

# Keywords the non-mock trainer actually passes to get_model today.
_TRAINER_GET_MODEL_KW = ("rope_type", "n_sinks", "use_peri_ln", "critical_shift")


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found")


def _param_names(fn: ast.FunctionDef) -> set[str]:
    names = {a.arg for a in fn.args.args}
    names.update(a.arg for a in fn.args.kwonlyargs)
    names.update(a.arg for a in fn.args.posonlyargs)
    if fn.args.vararg:
        names.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        names.add(fn.args.kwarg.arg)
    return names


def _module_bound_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _loaded_names(fn: ast.FunctionDef) -> set[str]:
    # Walk the body only — annotations like `critical_shift: int` are not runtime loads.
    names: set[str] = set()
    for stmt in fn.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
    return names


def _get_model_call_keywords(tree: ast.Module) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "get_model":
            for kw in node.keywords:
                if kw.arg:
                    keys.add(kw.arg)
    return keys


def test_get_model_accepts_trainer_critical_shift():
    params = _param_names(_func(_module(_MODEL), "get_model"))
    assert "critical_shift" in params, (
        "get_model must accept critical_shift — train_1b_deepspeed.py "
        "passes it on the non-mock path"
    )
    for name in _TRAINER_GET_MODEL_KW:
        assert name in params, f"get_model is missing {name!r} (trainer passes it)"


def test_get_model_body_has_no_undefined_names():
    """Catches the use_short_conv / use_relative NameError at ~get_model:877."""
    tree = _module(_MODEL)
    fn = _func(tree, "get_model")
    bound = _param_names(fn) | _module_bound_names(tree) | set(dir(__builtins__))
    undefined = _loaded_names(fn) - bound
    assert not undefined, (
        f"get_model references undefined name(s) {sorted(undefined)}; "
        "non-mock train_1b_deepspeed.py will NameError after the TypeError fallback"
    )


def test_get_model_executes_with_trainer_kwargs():
    """Execute get_model against a stub so NameError/TypeError surface without torch."""
    tree = _module(_MODEL)
    fn = _func(tree, "get_model")
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    captured: dict = {}

    def stub_model(**kwargs):
        captured.update(kwargs)
        return kwargs

    ns = {"DottieModel1B": stub_model}
    exec(compile(module, str(_MODEL), "exec"), ns)  # noqa: S102 — isolated factory body
    ns["get_model"](
        rope_type="yarn",
        n_sinks=4,
        use_peri_ln=True,
        critical_shift=6,
    )
    assert captured["critical_shift"] == 6
    assert captured["rope_type"] == "yarn"
    assert captured["n_sinks"] == 4
    assert captured["use_peri_ln"] is True
    assert "use_short_conv" not in captured
    assert "use_relative" not in captured
    assert "relative_max_distance" not in captured


def test_trainer_get_model_kwargs_are_in_factory_signature():
    model_params = _param_names(_func(_module(_MODEL), "get_model"))
    trainer_keys = _get_model_call_keywords(_module(_TRAINER))
    assert trainer_keys, "train_1b_deepspeed.py no longer calls get_model(...)"
    # Known trainer keys must be first-class so they reach DottieModel1B
    # rather than disappearing into **kwargs.
    missing = [name for name in _TRAINER_GET_MODEL_KW if name not in model_params]
    assert not missing, f"get_model is missing first-class trainer kwargs: {missing}"
    extra = trainer_keys - model_params
    extra.discard("kwargs")
    assert not extra, (
        f"train_1b_deepspeed.py passes get_model kwargs {sorted(extra)} "
        "that get_model does not declare"
    )
