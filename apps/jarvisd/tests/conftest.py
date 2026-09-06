"""Shared fixtures: a throwaway DB per test, a bearer-protected app, a TestClient.

The TestClient's base_url is a loopback host:port on purpose — FastMCP's default
DNS-rebinding allowlist for a loopback bind admits `127.0.0.1:*` and rejects
`testserver`, and real clients send the loopback host anyway.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from jarvisd.app import build_app
from jarvisd.config import Config
from jarvisd.state import State

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

warnings.filterwarnings("ignore", message=".*httpx.*starlette.testclient.*")

BEARER = "test-bearer-secret"
BASE_URL = "http://127.0.0.1:8790"


@pytest.fixture(autouse=True)
def _brain_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the brain provider so no test probes a real Ollama on the dev box.

    The default `JARVIS_BRAIN=auto` would `GET OLLAMA_HOST/api/tags`; with Ollama
    running locally that would turn the "brain unavailable" tests into live calls.
    Anthropic tests inject a fake client; Ollama tests set `JARVIS_BRAIN` and fake
    `urllib.request.urlopen` themselves.
    """
    monkeypatch.setenv("JARVIS_BRAIN", "anthropic")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def bearer() -> str:
    return BEARER


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jarvis.db"


@pytest.fixture
def state(db_path: Path) -> Iterator[State]:
    s = State(db_path)
    yield s
    s.close()


@pytest.fixture
def config(tmp_path: Path, db_path: Path) -> Config:
    return Config(
        host="127.0.0.1",
        port=8790,
        db_path=db_path,
        bearer=BEARER,
        workspace=tmp_path / "workspace",
    )


@pytest.fixture
def app(config: Config, state: State):
    return build_app(config, state=state)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {BEARER}", "X-Agent-Id": "tester"}
