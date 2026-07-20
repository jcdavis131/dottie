# Solo personal project, no connection to employer, built with public/free-tier only
"""Filesystem layout for the research loop — everything under the Dottie data dir's research/."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dottie.engine import DottieEngine

if TYPE_CHECKING:
    from pathlib import Path


def research_dir(data_dir: str | Path | None = None) -> Path:
    d = DottieEngine(data_dir).data_dir / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path(data_dir: str | Path | None = None) -> Path:
    return research_dir(data_dir) / "ledger.sqlite3"


def workspace_root(data_dir: str | Path | None = None) -> Path:
    p = research_dir(data_dir) / "workspaces"
    p.mkdir(parents=True, exist_ok=True)
    return p


def metrics_path(data_dir: str | Path | None = None) -> Path:
    return research_dir(data_dir) / "metrics.jsonl"


def status_path(data_dir: str | Path | None = None) -> Path:
    return research_dir(data_dir) / "status.json"
