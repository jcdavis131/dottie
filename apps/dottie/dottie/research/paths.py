# Solo personal project, no connection to employer, built with public/free-tier only
"""Filesystem layout for the research loop — everything under the Dottie data dir's research/."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from dottie.engine import DottieEngine


def research_dir(data_dir: Optional[str | Path] = None) -> Path:
    d = DottieEngine(data_dir).data_dir / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path(data_dir: Optional[str | Path] = None) -> Path:
    return research_dir(data_dir) / "ledger.sqlite3"


def workspace_root(data_dir: Optional[str | Path] = None) -> Path:
    p = research_dir(data_dir) / "workspaces"
    p.mkdir(parents=True, exist_ok=True)
    return p


def metrics_path(data_dir: Optional[str | Path] = None) -> Path:
    return research_dir(data_dir) / "metrics.jsonl"


def status_path(data_dir: Optional[str | Path] = None) -> Path:
    return research_dir(data_dir) / "status.json"
