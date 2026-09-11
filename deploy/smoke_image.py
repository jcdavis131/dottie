"""Exercise the real image on an ephemeral loopback port; no real credentials."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def main() -> None:
    name = f"dottie-smoke-{uuid.uuid4().hex[:10]}"
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "JARVIS_BEARER": token}
    image = os.environ.get("DOTTIE_TEST_IMAGE", "dottie/jarvisd:fleet-local")

    def docker(*args: str) -> str:
        return subprocess.check_output(["docker", *args], env=env, text=True).strip()

    docker(
        "run",
        "--rm",
        "-d",
        "--name",
        name,
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=64m",  # noqa: S108 -- private container tmpfs
        "-p",
        "127.0.0.1::8790",
        "-e",
        "JARVIS_BEARER",
        "-e",
        "JARVIS_BRAIN=off",
        image,
    )
    try:
        address = docker("port", name, "8790/tcp")
        assert address.startswith("127.0.0.1:")
        base = f"http://{address}"

        def request(path: str, body: dict | None = None, *, auth: bool = True) -> dict:
            headers = {"Content-Type": "application/json", "X-Agent-Id": "image-smoke"}
            if auth:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(  # noqa: S310 -- fixed loopback HTTP endpoint
                base + path,
                headers=headers,
                data=json.dumps(body).encode() if body is not None else None,
            )
            with urllib.request.urlopen(req, timeout=5) as response:  # noqa: S310
                return json.load(response)

        def healthy() -> None:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    assert request("/api/health", auth=False)["ok"]
                    return
                except (OSError, AssertionError):
                    time.sleep(0.5)
            raise RuntimeError("container did not become healthy")

        healthy()
        try:
            request("/api/goals", auth=False)
            raise AssertionError("unauthenticated goals were accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        pair = request("/api/pair/create", {})
        assert request("/api/pair/verify", {"code": pair["code"]})["paired"]
        try:
            request("/api/pair/verify", {"code": pair["code"]})
            raise AssertionError("pair code replay was accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 400
            assert json.load(error)["error"] == "already paired"
        goal = request(
            "/api/goals", {"repo": "image-smoke", "text": "verify durable state"}
        )["goal"]
        docker("restart", name)
        # Docker may allocate a new ephemeral host port when restarting.
        address = docker("port", name, "8790/tcp")
        assert address.startswith("127.0.0.1:")
        base = f"http://{address}"
        healthy()
        goals = request("/api/goals?repo=image-smoke")["goals"]
        assert any(item["id"] == goal["id"] for item in goals)
        docker("exec", name, "python", "-m", "dottie_loop", "spec", "status")
        print(
            json.dumps(
                {
                    "ok": True,
                    "image": image,
                    "checks": [
                        "health",
                        "authentication",
                        "pairing",
                        "pair_replay_denied",
                        "goal_survives_restart",
                        "dottie_loop_import",
                    ],
                }
            )
        )
    finally:
        docker("stop", "--time", "10", name)


if __name__ == "__main__":
    main()
