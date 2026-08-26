"""scopes/packs package"""

from pathlib import Path

__all__ = ["import_pack"]

def import_pack(url: str, name: str | None = None) -> dict:
    # lazy import to avoid circular
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("packs_import", Path(__file__).parent / "import.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod.import_pack(url, name)
