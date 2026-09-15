"""Slack ingress: fail-closed on every refusal path, a real goal on the happy one.

Signatures here are produced by `jarvisd.slack.sign`, the same function the verifier
uses. A hand-rolled HMAC in this file would be a second implementation that can drift
until it agrees with a bug in the first.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from jarvisd.app import build_app
from jarvisd.config import Config
from jarvisd.slack import (
    MAX_BODY_BYTES,
    MAX_SKEW_SECONDS,
    SLACK_PATH,
    ReplayGuard,
    SlackRefusalError,
    goal_text_from,
    parse_payload,
    sign,
    verify,
)
from jarvisd.state import State

from .conftest import BASE_URL

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"  # noqa: S105 - a test fixture, not a credential


@pytest.fixture
def slack_client(tmp_path: Path) -> Iterator[TestClient]:
    """A daemon with Slack ingress configured."""
    config = Config(
        host="127.0.0.1",
        port=8790,
        db_path=tmp_path / "slack.db",
        bearer="test-bearer-secret",
        slack_signing_secret=SECRET,
    )
    state = State(config.db_path)
    with TestClient(build_app(config, state=state), base_url=BASE_URL) as client:
        yield client
    state.close()


@pytest.fixture
def unconfigured_client(tmp_path: Path) -> Iterator[TestClient]:
    """The same daemon with no signing secret — ingress must be shut, not open."""
    config = Config(
        host="127.0.0.1",
        port=8790,
        db_path=tmp_path / "noslack.db",
        bearer="test-bearer-secret",
    )
    state = State(config.db_path)
    with TestClient(build_app(config, state=state), base_url=BASE_URL) as client:
        yield client
    state.close()


def _post(
    client: TestClient,
    body: bytes,
    *,
    content_type: str,
    timestamp: int | None = None,
    signature: str | None = None,
) -> Any:
    ts = int(time.time()) if timestamp is None else timestamp
    sig = sign(SECRET, ts, body) if signature is None else signature
    return client.post(
        SLACK_PATH,
        content=body,
        headers={
            "content-type": content_type,
            "x-slack-request-timestamp": str(ts),
            "x-slack-signature": sig,
        },
    )


def _slash(text: str, *, user: str = "jc", command: str = "/jarvis") -> bytes:
    return urllib.parse.urlencode(
        {
            "command": command,
            "text": text,
            "user_name": user,
            "team_domain": "dottie",
        }
    ).encode()


# ---- the branch that matters most: not configured means shut ----------------------


def test_unconfigured_slack_refuses_and_does_not_process(
    unconfigured_client: TestClient,
) -> None:
    """No signing secret must mean 503, never a 200 on an unsigned post."""
    r = unconfigured_client.post(
        SLACK_PATH,
        content=_slash("ship it"),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 503
    assert r.json()["ok"] is False
    # And nothing was written.
    goals = unconfigured_client.get(
        "/api/goals", headers={"authorization": "Bearer test-bearer-secret"}
    )
    assert goals.json()["goals"] == []


def test_unconfigured_refuses_even_a_correctly_signed_request(
    unconfigured_client: TestClient,
) -> None:
    """A valid signature against some other secret must not open the door."""
    r = _post(
        unconfigured_client,
        _slash("ship it"),
        content_type="application/x-www-form-urlencoded",
    )
    assert r.status_code == 503


def test_oversized_body_is_413_before_signature_or_config(
    slack_client: TestClient, unconfigured_client: TestClient
) -> None:
    """The public path must refuse before the bytes sit in memory.

    Content-Length over MAX_BODY_BYTES is 413 even with no signing secret and
    even with no Slack headers — otherwise an unauthenticated client can fill
    the daemon before HMAC or the 503-unconfigured branch run.
    """
    huge = b"x" * (MAX_BODY_BYTES + 1)
    for client in (slack_client, unconfigured_client):
        r = client.post(
            SLACK_PATH,
            content=huge,
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 413
        assert r.json()["ok"] is False


def test_chunked_oversized_body_is_413(slack_client: TestClient) -> None:
    def chunks() -> Any:
        yield b"x" * (MAX_BODY_BYTES // 2)
        yield b"x" * (MAX_BODY_BYTES // 2 + 1)

    r = slack_client.post(
        SLACK_PATH,
        content=chunks(),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


def test_slack_path_is_ip_rate_limited(tmp_path: Path) -> None:
    """Bearer-exempt is not limiter-exempt; Slack still counts against the IP bucket."""
    config = Config(
        host="127.0.0.1",
        port=8790,
        db_path=tmp_path / "rate.db",
        bearer="test-bearer-secret",
        slack_signing_secret=SECRET,
        rate_ip=2,
    )
    state = State(config.db_path)
    with TestClient(build_app(config, state=state), base_url=BASE_URL) as client:
        first = _post(client, _slash("one"), content_type="application/x-www-form-urlencoded")
        second = _post(client, _slash("two"), content_type="application/x-www-form-urlencoded")
        third = _post(client, _slash("three"), content_type="application/x-www-form-urlencoded")
        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429
        assert third.json()["error"] == "rate limited"
    state.close()


# ---- signature enforcement --------------------------------------------------------


def test_missing_signature_headers_are_refused(slack_client: TestClient) -> None:
    r = slack_client.post(
        SLACK_PATH,
        content=_slash("ship it"),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401


def test_bad_signature_is_refused(slack_client: TestClient) -> None:
    r = _post(
        slack_client,
        _slash("ship it"),
        content_type="application/x-www-form-urlencoded",
        signature="v0=" + "0" * 64,
    )
    assert r.status_code == 401
    assert r.json()["error"] == "bad signature"


def test_a_tampered_body_no_longer_matches_its_signature(
    slack_client: TestClient,
) -> None:
    """The signature covers the body, so editing the body must invalidate it."""
    original = _slash("open a harmless goal")
    ts = int(time.time())
    sig = sign(SECRET, ts, original)
    r = slack_client.post(
        SLACK_PATH,
        content=_slash("rm -rf everything"),
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-slack-request-timestamp": str(ts),
            "x-slack-signature": sig,
        },
    )
    assert r.status_code == 401


def test_a_stale_timestamp_is_refused(slack_client: TestClient) -> None:
    old = int(time.time()) - MAX_SKEW_SECONDS - 30
    r = _post(
        slack_client,
        _slash("ship it"),
        content_type="application/x-www-form-urlencoded",
        timestamp=old,
    )
    assert r.status_code == 401


def test_a_future_timestamp_is_refused_too(slack_client: TestClient) -> None:
    """The window is two-sided; a one-sided check accepts next year."""
    ahead = int(time.time()) + MAX_SKEW_SECONDS + 30
    r = _post(
        slack_client,
        _slash("ship it"),
        content_type="application/x-www-form-urlencoded",
        timestamp=ahead,
    )
    assert r.status_code == 401


def test_a_malformed_timestamp_is_refused(slack_client: TestClient) -> None:
    body = _slash("ship it")
    r = slack_client.post(
        SLACK_PATH,
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-slack-request-timestamp": "not-a-number",
            "x-slack-signature": sign(SECRET, "not-a-number", body),
        },
    )
    assert r.status_code == 401


# ---- the happy path: a goal typed in Slack is a goal in the daemon ----------------


def test_a_slash_command_opens_a_real_goal(slack_client: TestClient) -> None:
    r = _post(
        slack_client,
        _slash("ship the release notes"),
        content_type="application/x-www-form-urlencoded",
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["ok"] is True
    assert doc["response_type"] == "ephemeral"
    assert "ship the release notes" in doc["text"]

    # It is really in the database, readable through the daemon's own API.
    goals = slack_client.get(
        "/api/goals", headers={"authorization": "Bearer test-bearer-secret"}
    ).json()["goals"]
    assert len(goals) == 1
    assert goals[0]["text"] == "ship the release notes"
    assert goals[0]["agent"] == "slack:jc"
    assert goals[0]["status"] == "open"


def test_an_app_mention_opens_a_goal_with_the_mention_stripped(
    slack_client: TestClient,
) -> None:
    body = json.dumps(
        {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "user": "U123",
                "text": "<@U0JARVIS> write the postmortem",
            },
        }
    ).encode()
    r = _post(slack_client, body, content_type="application/json")
    assert r.status_code == 200, r.text
    goals = slack_client.get(
        "/api/goals", headers={"authorization": "Bearer test-bearer-secret"}
    ).json()["goals"]
    assert goals[0]["text"] == "write the postmortem"
    assert goals[0]["agent"] == "slack:U123"


def test_an_empty_command_explains_itself_and_opens_nothing(
    slack_client: TestClient,
) -> None:
    r = _post(
        slack_client, _slash(""), content_type="application/x-www-form-urlencoded"
    )
    assert r.status_code == 200
    assert "/jarvis" in r.json()["text"]
    goals = slack_client.get(
        "/api/goals", headers={"authorization": "Bearer test-bearer-secret"}
    ).json()["goals"]
    assert goals == []


def test_url_verification_echoes_the_challenge_but_only_when_signed(
    slack_client: TestClient,
) -> None:
    body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
    r = _post(slack_client, body, content_type="application/json")
    assert r.status_code == 200
    assert r.json()["challenge"] == "abc123"

    unsigned = slack_client.post(
        SLACK_PATH, content=body, headers={"content-type": "application/json"}
    )
    assert unsigned.status_code == 401


# ---- replay ------------------------------------------------------------------------


def test_a_slack_retry_does_not_open_a_second_goal(slack_client: TestClient) -> None:
    """Slack retries on a slow 200; the same signature must be accepted once."""
    body = _slash("do the thing once")
    ts = int(time.time())
    sig = sign(SECRET, ts, body)
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "x-slack-request-timestamp": str(ts),
        "x-slack-signature": sig,
    }
    first = slack_client.post(SLACK_PATH, content=body, headers=headers)
    second = slack_client.post(SLACK_PATH, content=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 409

    goals = slack_client.get(
        "/api/goals", headers={"authorization": "Bearer test-bearer-secret"}
    ).json()["goals"]
    assert len(goals) == 1


def test_replay_guard_evicts_past_the_window() -> None:
    guard = ReplayGuard()
    guard.check_and_record("sig-a", now=1000.0)
    assert len(guard) == 1
    # Far enough ahead that the old entry is outside the replay window.
    guard.check_and_record("sig-b", now=1000.0 + MAX_SKEW_SECONDS + 1)
    assert len(guard) == 1


def test_replay_guard_is_bounded() -> None:
    guard = ReplayGuard(capacity=8)
    for i in range(50):
        guard.check_and_record(f"sig-{i}", now=1000.0)
    assert len(guard) == 8


# ---- refusing what we do not understand, rather than waving it through -------------


def test_an_unknown_content_type_is_refused(slack_client: TestClient) -> None:
    r = _post(slack_client, b"<xml/>", content_type="application/xml")
    assert r.status_code == 400


def test_an_unhandled_event_type_is_refused_not_silently_accepted(
    slack_client: TestClient,
) -> None:
    """A 200 on something we did not process is the fail-open this repo keeps finding."""
    body = json.dumps(
        {"type": "event_callback", "event": {"type": "reaction_added", "user": "U1"}}
    ).encode()
    r = _post(slack_client, body, content_type="application/json")
    assert r.status_code == 400
    assert "reaction_added" in r.json()["error"]


def test_a_bot_message_is_ignored_so_the_daemon_cannot_talk_to_itself(
    slack_client: TestClient,
) -> None:
    body = json.dumps(
        {
            "type": "event_callback",
            "event": {"type": "message", "bot_id": "B1", "text": "Opened goal #1"},
        }
    ).encode()
    r = _post(slack_client, body, content_type="application/json")
    assert r.status_code == 400
    goals = slack_client.get(
        "/api/goals", headers={"authorization": "Bearer test-bearer-secret"}
    ).json()["goals"]
    assert goals == []


def test_a_subtyped_message_is_ignored(slack_client: TestClient) -> None:
    body = json.dumps(
        {
            "type": "event_callback",
            "event": {
                "type": "message",
                "subtype": "channel_join",
                "user": "U1",
                "text": "joined",
            },
        }
    ).encode()
    assert _post(slack_client, body, content_type="application/json").status_code == 400


def test_an_unrecognised_payload_is_refused(slack_client: TestClient) -> None:
    body = json.dumps({"hello": "world"}).encode()
    r = _post(slack_client, body, content_type="application/json")
    assert r.status_code == 400


# ---- unit-level checks on the primitives -------------------------------------------


def test_verify_without_a_secret_raises_503() -> None:
    with pytest.raises(SlackRefusalError) as excinfo:
        verify(None, {}, b"")
    assert excinfo.value.status == 503


def test_verify_oversized_body_is_413_even_without_a_secret() -> None:
    with pytest.raises(SlackRefusalError) as excinfo:
        verify(None, {}, b"x" * (MAX_BODY_BYTES + 1))
    assert excinfo.value.status == 413


def test_parse_payload_refuses_non_utf8() -> None:
    with pytest.raises(SlackRefusalError):
        parse_payload("application/json", b"\xff\xfe")


def test_goal_text_from_refuses_a_challengeless_verification() -> None:
    with pytest.raises(SlackRefusalError):
        goal_text_from({"type": "url_verification"})


def test_sign_is_stable_and_matches_the_documented_shape() -> None:
    sig = sign(SECRET, 1531420618, b"token=x&text=hi")
    assert sig.startswith("v0=")
    assert len(sig) == 3 + 64
    assert sign(SECRET, 1531420618, b"token=x&text=hi") == sig
    assert sign(SECRET, 1531420619, b"token=x&text=hi") != sig
