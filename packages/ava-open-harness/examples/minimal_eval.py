"""
minimal_eval.py — example custom eval

Solo personal project, no connection to employer, built with public/free-tier only
"""
from __future__ import annotations
from harness.registry import register_eval

@register_eval(name="my_custom_eval", description="Example custom eval — checks model exists", group="custom")
def my_custom_eval(model, tokenizer, device="cpu", **kw):
    # measured must be computed, not hardcoded mock literals like 0.82 etc
    try:
        has_model = model is not None
    except Exception:
        has_model = False
    return {
        "test": "my_custom_eval",
        "measured": {"has_model": has_model, "seed": getattr(model,"seed",0)},
        "pass": bool(has_model),
        "bar": "model not None"
    }

if __name__ == "__main__":
    from harness.runner import run_harness, write_reports
    res = run_harness(eval_names=["my_custom_eval"], mode="mock", verbose=True)
    print(res)
