# Solo personal project, no connection to employer, built with public/free-tier only
"""Shared fixtures: repo-root sys.path + dashed-directory skill module loading."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKILLS_DIR = ROOT / "skills"


def load_skill_module(name: str):
    """Import skills/<name>/skill.py despite the dash in the directory name."""
    modname = f"ava_test_skill_{name.replace('-', '_')}"
    if modname in sys.modules:
        return sys.modules[modname]
    path = SKILLS_DIR / name / "skill.py"
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod  # register before exec: dataclasses resolve cls.__module__
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def skill():
    return load_skill_module
