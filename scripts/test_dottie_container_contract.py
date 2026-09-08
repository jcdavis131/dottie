#!/usr/bin/env python3
"""Daemon-free contract tests for the canonical jarvisd container release.

    uv run --no-sync python scripts/test_dottie_container_contract.py
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.dottie.yml"
DOCKERFILE_PATH = ROOT / "Dockerfile.jarvisd"
DOCKERIGNORE_PATH = ROOT / "Dockerfile.jarvisd.dockerignore"

PACKAGES = {
    "jarvisd": ("apps/jarvisd", "jarvisd"),
    "scout-cli": ("apps/scout-cli", "bigbang"),
    "personal-graphify": ("packages/personal-graphify", "personal_graphify"),
    "ava-skills": ("packages/ava-skills", "skills"),
    "ava-open-harness": ("packages/ava-open-harness", "harness"),
}
FORBIDDEN_RUNTIME_PACKAGES = {
    "anthropic",
    "mypy",
    "pytest",
    "pytest-cov",
    "ruff",
    "tokenizers",
    "torch",
}

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(name)
    tail = f"  — {detail}" if detail and not condition else ""
    print(f"{'PASS' if condition else 'FAIL'}  {name}{tail}")


compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
compose = yaml.safe_load(compose_text)
dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
dockerignore = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

service = compose["services"]["jarvisd"]
environment = service["environment"]
expected_bearer = (
    "${JARVIS_BEARER:?JARVIS_BEARER must be set and non-empty}"
)

check(
    "compose uses the exact required bearer interpolation",
    environment["JARVIS_BEARER"] == expected_bearer,
)
check("compose has no bearer default", "${JARVIS_BEARER:-" not in compose_text)
check("canonical brain is disabled by default", environment["JARVIS_BRAIN"] == "${JARVIS_BRAIN:-off}")
check("canonical Ollama model is qwen3:8b", environment["OLLAMA_MODEL"] == "${OLLAMA_MODEL:-qwen3:8b}")
check(
    "canonical compose does not pass Anthropic credentials",
    not any("ANTHROPIC" in str(key).upper() for key in environment),
)
check(
    "canonical compose selects no optional image extras",
    service["build"]["args"] == {"JARVISD_SYNC_ARGS": ""},
)

check("host publication is loopback-only", service["ports"] == ["127.0.0.1:8790:8790"])
check("container runs explicitly as uid/gid 1000", service["user"] == "1000:1000")
check("all Linux capabilities are dropped", service["cap_drop"] == ["ALL"])
check("privilege escalation is disabled", "no-new-privileges:true" in service["security_opt"])
check("root filesystem is read-only", service["read_only"] is True)
check("temporary writes use tmpfs", any(str(item).startswith("/tmp:") for item in service["tmpfs"]))
check("compose never enables privileged mode", service.get("privileged") is not True)
check(
    "compose never mounts the Docker socket",
    "docker.sock" not in compose_text.lower(),
)
check("compose never uses host networking", service.get("network_mode") != "host")

mounts = set(service["volumes"])
check("state is a writable named /data volume", "jarvis-data:/data" in mounts)
check("runs use a writable named /workspace volume", "jarvis-workspace:/workspace" in mounts)
check(
    "both writable volume names are declared",
    {"jarvis-data", "jarvis-workspace"} <= set(compose["volumes"]),
)

workspace_members = set(root_project["tool"]["uv"]["workspace"]["members"])
lock_packages = {package["name"] for package in lock["package"]}
lock_by_name = {package["name"]: package for package in lock["package"]}
check(
    "root workspace lists the five release packages",
    workspace_members == {path for path, _ in PACKAGES.values()},
    f"members={sorted(workspace_members)}",
)
check(
    "frozen lock contains the five release distributions",
    set(PACKAGES) <= lock_packages,
    f"missing={sorted(set(PACKAGES) - lock_packages)}",
)
for distribution, (member, import_name) in PACKAGES.items():
    metadata = tomllib.loads((ROOT / member / "pyproject.toml").read_text(encoding="utf-8"))
    check(f"{member} declares distribution {distribution}", metadata["project"]["name"] == distribution)
    module_candidates = [ROOT / member / import_name, ROOT / member / "src" / import_name]
    check(
        f"{distribution} ships import {import_name}",
        any(path.is_dir() for path in module_candidates),
    )
    check(f"Docker context includes {member}", f"!{member}" in dockerignore)
    metadata_copy = f"COPY {member}/pyproject.toml"
    source_copy = re.search(
        rf"^COPY\s+({re.escape(member)}|{re.escape(str(Path(member).parent).replace(chr(92), '/'))})\s+",
        dockerfile,
        flags=re.MULTILINE,
    )
    check(f"builder copies {member} metadata", metadata_copy in dockerfile)
    check(f"builder copies {member} sources", source_copy is not None)

sync_commands = re.findall(r"uv sync [^\n]+", dockerfile)
check("both image sync phases are frozen", len(sync_commands) == 2 and all("--frozen" in line for line in sync_commands))
check("both image sync phases exclude dev dependencies", all("--no-dev" in line for line in sync_commands))
check(
    "dependency layer resolves every workspace package",
    any("--no-install-workspace --all-packages" in line for line in sync_commands),
)
check(
    "source layer installs every workspace package",
    any("--all-packages" in line and "--no-install-workspace" not in line for line in sync_commands),
)
check("Anthropic brain image extra is opt-in", 'ARG JARVISD_SYNC_ARGS=""' in dockerfile)
check("image performs no pip install", "pip install" not in dockerfile.lower())
check("runtime command forbids uv synchronization", "UV_NO_SYNC=1" in dockerfile)
check(
    "uv binary is pinned exactly",
    "COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/" in dockerfile,
)

runtime_closure = set(PACKAGES)
pending = list(PACKAGES)
while pending:
    package_name = pending.pop()
    for dependency in lock_by_name[package_name].get("dependencies", []):
        dependency_name = dependency["name"]
        if dependency_name not in runtime_closure:
            runtime_closure.add(dependency_name)
            pending.append(dependency_name)
check(
    "default runtime closure excludes dev Anthropic tokenizers and Torch",
    not (runtime_closure & FORBIDDEN_RUNTIME_PACKAGES),
    f"found={sorted(runtime_closure & FORBIDDEN_RUNTIME_PACKAGES)}",
)

check("image declares a healthcheck", "HEALTHCHECK " in dockerfile)
check("healthcheck probes loopback", "http://127.0.0.1:" in dockerfile)
check("healthcheck probes /api/health", "/api/health" in dockerfile)
check("image creates uid 1000", "ARG JARVISD_UID=1000" in dockerfile)
check("image drops to the jarvis user", "USER jarvis" in dockerfile)

ignore_rules = {
    line.strip()
    for line in dockerignore.splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
for required_rule in (
    "**/.git",
    "**/node_modules",
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/checkpoints",
):
    check(
        f"Docker context excludes {required_rule}",
        required_rule in ignore_rules,
    )

print()
print(f"{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
