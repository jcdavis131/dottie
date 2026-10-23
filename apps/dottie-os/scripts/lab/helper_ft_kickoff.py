#!/usr/bin/env python3
"""Forge-runner HELPER FT ``POST /train/kickoff`` handler (:8765).

Re-fetches the Cam-signed pack-pin from the pinned Swarm HQ origin, verifies
Cam's Ed25519 signature against the committed public key, then hashes and
counts only the run-private copies (never request paths, never the inbox).
``stampVerified`` and ``pack_matches`` are advisory and never sufficient.
A pin carried only in the request body is not provenance.

``inbox: latest`` and every other HELPER FT start route are refused.
``default_launch_trainer`` refuses unless a real launcher is wired.
The trainer is passed only run-dir copy paths. After the launcher
returns (this process waits), those recorded paths are re-hashed on
this host. Does not promote, does not touch serve, :8770, or champion files.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from wsgiref.simple_server import make_server

_LAB = str(Path(__file__).resolve().parent)
if _LAB not in sys.path:
    sys.path.insert(0, _LAB)

import cam_pin_spec
import helper_ft_trackio
import kick_helper_ft

CHUNK = 1 << 20
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
MAX_EVIDENCE_AGE_SECONDS = 15 * 60
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Radar: the only HTTP training-start route in this repository.
TRAINING_START_ROUTES = (("POST", "/train/kickoff"),)
# jev-ava's trainer is not served from this tree. Empty on purpose.
JEV_AVA_TRAINING_START_ROUTES: tuple[tuple[str, str], ...] = ()
SWARM_HQ_AGENT_TOKEN_ENV = cam_pin_spec.SWARM_HQ_AGENT_TOKEN_ENV
PIN_SOURCE = "swarm-hq-cam-pin"
HQ_PIN_REQUIRED_KEYS = cam_pin_spec.HQ_PIN_REQUIRED_KEYS
HQ_PIN_ALLOWED_KEYS = cam_pin_spec.HQ_PIN_ALLOWED_KEYS
PACK_FILE = "curated_pack_v2.jsonl"
TRAIN_FILE = "curated_pack_v2_train.jsonl"
HOLDOUT_FILE = "curated_pack_v2_holdout.jsonl"
MANIFEST_FILE = "MANIFEST.json"
# (sha field, run-private filename, MANIFEST row field, pin row field)
ARTIFACTS = (
    ("sha256_pack", PACK_FILE, "rows", "rows_total"),
    ("sha256_train", TRAIN_FILE, "train_rows", "rows_train"),
    ("sha256_holdout", HOLDOUT_FILE, "holdout_rows", "rows_holdout"),
)
MAX_BODY_BYTES = 64 * 1024
# Every HELPER FT start path other than POST /train/kickoff.
OTHER_HELPER_FT_START_PATHS = frozenset(
    {
        "/train/start",
        "/train/run",
        "/train/helper",
        "/train/helper-ft",
        "/train/inbox-validate",
        "/train/inbox",
        "/train/kick",
        "/inbox/latest",
        "/inbox_latest",
        "/train/kickoff/latest",
    }
)
LaunchTrainer = Callable[[dict[str, Any]], dict[str, Any]]


def _bad(field: str, expected: object, actual: object) -> dict[str, Any]:
    return {
        "ok": False,
        "field": field,
        "expected": expected,
        "actual": actual,
        "error": f"HELPER FT kickoff refused: {field}: expected {expected} actual {actual}",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _require_sha(field: str, value: object) -> str | dict[str, Any]:
    try:
        return cam_pin_spec.require_sha256_hex(field, value)
    except cam_pin_spec.CamPinError as exc:
        return _bad(exc.field, exc.expected, exc.actual)


def _require_int(field: str, value: object) -> int | dict[str, Any]:
    try:
        return cam_pin_spec.require_int(field, value)
    except cam_pin_spec.CamPinError as exc:
        return _bad(exc.field, exc.expected, exc.actual)


def _count_rows(path: Path) -> int | dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except UnicodeDecodeError:
        return _bad(path.name, "utf-8 text", "invalid encoding")
    except OSError as exc:
        return _bad(path.name, "readable text file", f"OSError:{exc.errno}")


def _no_duplicate_manifest_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate {key}")
        seen[key] = value
    return seen


def _read_run_private_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_FILE
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return _bad(MANIFEST_FILE, "present", "missing")
    except OSError as exc:
        return _bad(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    if stat.S_ISLNK(info.st_mode):
        return _bad(MANIFEST_FILE, "regular file", "symlink")
    if not stat.S_ISREG(info.st_mode):
        return _bad(MANIFEST_FILE, "regular file", "non-regular")
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return _bad(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    try:
        raw = os.read(fd, cam_pin_spec.MAX_PIN_BYTES + 1)
    finally:
        os.close(fd)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _bad(MANIFEST_FILE, "utf-8 text", "invalid encoding")
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_manifest_keys)
    except ValueError as exc:
        if "duplicate" in str(exc):
            return _bad(MANIFEST_FILE, "unique keys", str(exc))
        return _bad(MANIFEST_FILE, "valid JSON object", "invalid JSON")
    if not isinstance(payload, dict):
        return _bad(MANIFEST_FILE, "object", type(payload).__name__)
    return payload


def _parse_checked_at(value: object) -> datetime | dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return _bad("checked_at", "present", "missing")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _bad("checked_at", "ISO-8601 UTC", value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_launch_trainer(body: dict[str, Any]) -> dict[str, Any]:
    """Refuse unless a real trainer launcher is wired in."""
    del body
    return _bad("trainer", "wired launch_trainer", "default no-op")


def _parse_hq_pin_payload(payload: object) -> dict[str, Any]:
    try:
        return cam_pin_spec.parse_hq_pin_payload(payload)
    except cam_pin_spec.CamPinError as exc:
        return _bad(exc.field, exc.expected, exc.actual)


def fetch_cam_pin(pack_id: str) -> dict[str, Any]:
    """GET the pinned-origin pin and verify Cam's Ed25519 signature."""
    if type(pack_id) is not str or not pack_id:
        return _bad("pack_id", "present", "missing")
    try:
        parsed = cam_pin_spec.fetch_signed_pin(pack_id)
    except cam_pin_spec.CamPinError as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    return {"ok": True, "pin": parsed}


def require_hq_cam_pin(pack_id: str) -> dict[str, Any]:
    """Re-fetch the Cam-signed pin. A request-body pin is not provenance."""
    fetched = fetch_cam_pin(pack_id)
    if fetched.get("ok") is not True:
        return fetched
    record = fetched.get("pin")
    if not isinstance(record, dict) or not record:
        return _bad("cam-pin", "present", "missing")
    pin_pack = record.get("pack_id")
    if type(pin_pack) is not str or not pin_pack:
        return _bad("cam-pin.pack_id", "present", "missing")
    if pin_pack != pack_id:
        return _bad("cam-pin.pack_id", pack_id, pin_pack)
    pin: dict[str, Any] = {
        "pack_id": pack_id,
        "source": PIN_SOURCE,
        "recordedAt": record.get("recordedAt"),
        "kid": record.get("kid"),
        "cam_key_id": record.get("cam_key_id"),
        "cam_sig": record.get("cam_sig"),
    }
    for sha_field, _filename, _manifest_rows, pin_rows_field in ARTIFACTS:
        required = _require_sha(f"cam-pin.{sha_field}", record.get(sha_field))
        if isinstance(required, dict):
            return required
        pin[sha_field] = required
        rows = _require_int(f"cam-pin.{pin_rows_field}", record.get(pin_rows_field))
        if isinstance(rows, dict):
            return rows
        pin[pin_rows_field] = rows
    return {"ok": True, "pin": pin}


def _session_from_body(body: dict[str, Any] | None) -> helper_ft_trackio.RunSession:
    run_id = None
    run_dir = None
    if isinstance(body, dict):
        raw_id = body.get("run_id")
        if type(raw_id) is str and raw_id:
            run_id = raw_id
        evidence = body.get("evidence") if isinstance(body.get("evidence"), dict) else {}
        if run_id is None:
            ev_id = evidence.get("run_id")
            if type(ev_id) is str and ev_id:
                run_id = ev_id
        ev_path = body.get("evidence_path") or evidence.get("evidence_path")
        if isinstance(ev_path, str) and ev_path:
            run_dir = Path(ev_path).parent
    return helper_ft_trackio.RunSession(run_id=run_id, run_dir=run_dir)


def _track_kickoff_result(
    session: helper_ft_trackio.RunSession,
    body: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Record MATCH/REFUSED after the gate has already decided. Fail-open."""
    try:
        evidence = body.get("evidence") if isinstance(body, dict) and isinstance(body.get("evidence"), dict) else {}
        config = helper_ft_trackio.config_from_evidence({**evidence, **payload})
        if payload.get("ok") is True:
            if not session.inited:
                session.start(config)
            smoke = payload.get("smoke") is True
            session.log_integrity(
                {
                    "sha256_evidence": payload.get("sha256_evidence"),
                    "result": payload.get("result"),
                    "exit_code": payload.get("exit_code"),
                    "smoke": smoke,
                    "scorable": False if smoke else True,
                    "host": payload.get("host"),
                }
            )
            session.finish()
            return payload
        session.refuse(payload, config=config)
    except Exception:
        pass
    return payload


def handle_train_kickoff(
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
) -> dict[str, Any]:
    """Refuse HELPER FT kickoff unless HQ pin matches re-hashed files.

    Re-fetches the Cam pin from Swarm HQ. A body-only pin is refused.
    ``stampVerified`` and ``pack_matches`` are advisory and never sufficient.
    ``inbox: latest`` is never accepted. Evidence ``ok: true`` is not trust.
    """
    session = _session_from_body(body)
    return _track_kickoff_result(session, body, _handle_train_kickoff(body, launch_trainer=launch_trainer, session=session))


def _handle_train_kickoff(
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
    session: helper_ft_trackio.RunSession | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        return _bad("body", "object", type(body).__name__)
    try:
        blobs = cam_pin_spec.require_committed_trust()
    except cam_pin_spec.CamPinError as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    try:
        kick_helper_ft.refuse_inbox_latest(body)
    except kick_helper_ft.KickRefused as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    mode = body.get("mode")
    if mode == "inbox-validate":
        return _bad("mode", "helper-ft", "inbox-validate")
    smoke = kick_helper_ft.is_smoke_mode(body)
    if mode not in ("helper-ft", "helper-ft-smoke"):
        return _bad("mode", "helper-ft", mode)
    evidence = body.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return _bad("evidence", "present", "missing")
    if evidence.get("ok") is not True:
        return _bad("evidence.ok", True, evidence.get("ok"))
    pack_id = body.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        return _bad("pack_id", "present", "missing")
    if evidence.get("pack_id") != pack_id:
        return _bad("pack_id", pack_id, evidence.get("pack_id"))
    run_id = body.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return _bad("run_id", "present", "missing")
    ev_run = evidence.get("run_id")
    if ev_run != run_id:
        return _bad("evidence.run_id", run_id, ev_run)
    checked = _parse_checked_at(evidence.get("checked_at") or body.get("checked_at"))
    if isinstance(checked, dict):
        return checked
    age = (datetime.now(timezone.utc) - checked).total_seconds()
    if age > MAX_EVIDENCE_AGE_SECONDS or age < -60:
        return _bad("checked_at", f"age<={MAX_EVIDENCE_AGE_SECONDS}s", f"age={int(age)}s")
    evidence_path = body.get("evidence_path") or evidence.get("evidence_path")
    if isinstance(evidence_path, str) and evidence_path:
        disk_path = Path(evidence_path)
        if not disk_path.is_file():
            return _bad("evidence_path", "present", "missing")
        try:
            disk_ev = json.loads(disk_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return _bad("evidence_path", "readable JSON", type(exc).__name__)
        if not isinstance(disk_ev, dict):
            return _bad("evidence_path", "object", type(disk_ev).__name__)
        if disk_ev.get("run_id") != run_id:
            return _bad("evidence.run_id", run_id, disk_ev.get("run_id"))
        if disk_ev.get("ok") is False:
            return _bad("evidence.ok", True, False)
    pin = body.get("pin")
    if not isinstance(pin, dict) or not pin:
        return _bad("pin", "present", "missing")
    if pin.get("pack_id") != pack_id:
        return _bad("pin.pack_id", pack_id, pin.get("pack_id"))
    hq = require_hq_cam_pin(pack_id)
    if hq.get("ok") is not True:
        return hq
    hq_pin = hq["pin"]
    hq_id = cam_pin_spec.pin_identity(hq_pin)
    body_id = cam_pin_spec.pin_identity(pin)
    ev_pin = evidence.get("pin") if isinstance(evidence.get("pin"), dict) else {}
    ev_id = cam_pin_spec.pin_identity(ev_pin) if ev_pin else None
    if body_id != hq_id:
        return _bad("pin", hq_id, body_id)
    if ev_id is not None and ev_id != hq_id:
        return _bad("evidence.pin", hq_id, ev_id)
    run_private = body.get("run_private_dir")
    if type(run_private) is not str or not run_private:
        return _bad("run_private_dir", "present", "missing")
    root = Path(run_private)
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return _bad("run_private_dir", "present", "missing")
    except OSError as exc:
        return _bad("run_private_dir", "readable directory", f"OSError:{exc.errno}")
    if stat.S_ISLNK(info.st_mode):
        return _bad("run_private_dir", "real directory", "symlink")
    if not stat.S_ISDIR(info.st_mode):
        return _bad("run_private_dir", "directory", "not a directory")
    manifest = _read_run_private_manifest(root)
    if manifest.get("ok") is False and "field" in manifest:
        return manifest
    if manifest.get("pack_id") != pack_id:
        return _bad("pack_id", pack_id, manifest.get("pack_id"))
    fetched_pin = {"ok": True, "pin": hq_pin, "source": PIN_SOURCE}
    evidence["kickoff_pin_fetch"] = fetched_pin
    trainer_paths = kick_helper_ft.trainer_input_paths(root)
    claimed_paths = body.get("paths")
    if isinstance(claimed_paths, dict):
        pack_dir_claim = claimed_paths.get("pack_dir")
        if pack_dir_claim:
            claimed_dir = str(Path(str(pack_dir_claim)).resolve())
            if claimed_dir != str(root.resolve()):
                return _bad("paths.pack_dir", "absent (run-dir copies only)", pack_dir_claim)
        for key, expected in trainer_paths.items():
            got = claimed_paths.get(key)
            if type(got) is not str:
                return _bad(f"paths.{key}", expected, "missing")
            if str(Path(got).resolve()) != expected:
                return _bad(f"paths.{key}", expected, got)
    recorded_paths = dict(trainer_paths)
    manifest_shas: dict[str, str] = {}
    for sha_field, filename, manifest_rows_field, pin_rows_field in ARTIFACTS:
        req = _require_sha(sha_field, body.get(sha_field))
        if isinstance(req, dict):
            return req
        hq_sha = hq_pin[sha_field]
        if req != hq_sha:
            return _bad(sha_field, hq_sha, req)
        pin_rows = hq_pin[pin_rows_field]
        if manifest_rows_field not in manifest:
            return _bad(manifest_rows_field, "present", "missing")
        expected_rows = _require_int(manifest_rows_field, manifest[manifest_rows_field])
        if isinstance(expected_rows, dict):
            return expected_rows
        if pin_rows != expected_rows:
            return _bad(pin_rows_field, pin_rows, expected_rows)
        man_sha = _require_sha(f"manifest.{sha_field}", manifest.get(sha_field))
        if isinstance(man_sha, dict):
            return man_sha
        if man_sha != hq_sha:
            return _bad(sha_field, hq_sha, man_sha)
        manifest_shas[sha_field] = man_sha
        path_key = kick_helper_ft.PATH_KEY_BY_SHA[sha_field]
        path = Path(recorded_paths[path_key])
        try:
            finfo = os.lstat(path)
        except FileNotFoundError:
            return _bad(filename, "present", "missing")
        except OSError as exc:
            return _bad(filename, "readable regular file", f"OSError:{exc.errno}")
        if stat.S_ISLNK(finfo.st_mode):
            return _bad(filename, "regular file", "symlink")
        if not stat.S_ISREG(finfo.st_mode):
            return _bad(filename, "regular file", "non-regular")
        if os.name == "posix" and finfo.st_mode & 0o222:
            return _bad(filename, "0400", oct(stat.S_IMODE(finfo.st_mode)))
        counted = _count_rows(path)
        if isinstance(counted, dict):
            return counted
        if pin_rows != counted:
            return _bad(pin_rows_field, pin_rows, counted)
        try:
            actual = _sha256_file(path)
        except OSError as exc:
            return _bad(filename, "readable regular file", f"OSError:{exc.errno}")
        if actual != hq_sha:
            return _bad(sha_field, hq_sha, actual)
        if actual != req:
            return _bad(sha_field, req, actual)
    source_pack = body.get("source_pack_dir") or evidence.get("source_pack_dir")
    try:
        kick_helper_ft.enforce_pack_gates(
            manifest,
            recorded_paths,
            smoke=smoke,
            pack_dir=source_pack if isinstance(source_pack, str) else None,
        )
    except kick_helper_ft.KickRefused as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    host = socket.gethostname()
    trainer_config = {"host": host, "paths": recorded_paths}
    trainer_argv = kick_helper_ft.build_trainer_argv(recorded_paths)
    if session is not None:
        session.run_id = run_id
        session.start(
            helper_ft_trackio.config_from_evidence(
                {
                    **evidence,
                    "run_id": run_id,
                    "pack_id": pack_id,
                    "computed_shas": {
                        "sha256_pack": hq_pin["sha256_pack"],
                        "sha256_train": hq_pin["sha256_train"],
                        "sha256_holdout": hq_pin["sha256_holdout"],
                    },
                    "pin": hq_pin,
                    "host": host,
                    "head_sha": blobs.get("HEAD"),
                    "trainer_config": trainer_config,
                }
            )
        )
    launch_body = dict(body)
    launch_body["paths"] = recorded_paths
    launch_body["trainer_config"] = trainer_config
    launch_body["trainer_argv"] = trainer_argv
    ev_paths = evidence.get("paths") if isinstance(evidence.get("paths"), dict) else {}
    launch_evidence = dict(evidence)
    launch_evidence["paths"] = recorded_paths
    launch_evidence["run_private_dir"] = str(root.resolve())
    if isinstance(ev_paths, dict) and ev_paths.get("pack_dir"):
        return _bad("paths.pack_dir", "absent (run-dir copies only)", ev_paths.get("pack_dir"))
    launch_body["evidence"] = launch_evidence
    launcher = launch_trainer if launch_trainer is not None else default_launch_trainer
    launched = launcher(launch_body)
    if not isinstance(launched, dict) or launched.get("ok") is not True:
        return _bad("trainer", "ok", launched)
    if session is not None:
        log_path = None
        if isinstance(evidence_path, str) and evidence_path:
            log_path = Path(evidence_path).parent / kick_helper_ft.DEFAULT_LOG_NAME
        session.log_losses_from_launch(launched, log_path=log_path)
    exit_info = kick_helper_ft.wait_for_training_exit(launched)
    record = kick_helper_ft.rehash_recorded_trainer_paths(
        recorded_paths,
        pin=hq_pin,
        manifest_shas=manifest_shas,
        host=host,
    )
    kick_helper_ft.apply_trainer_exit(record, exit_info)
    ckpt_id = launched.get("checkpoint_id")
    run_dir = Path(evidence_path).parent if isinstance(evidence_path, str) and evidence_path else root.parent
    if ckpt_id:
        try:
            ckpt_dir = kick_helper_ft.checkpoint_dir_for(run_dir, ckpt_id)
        except kick_helper_ft.KickRefused as exc:
            return _bad(exc.field, exc.expected, exc.actual)
        if ckpt_dir is not None:
            ckpt_path = ckpt_dir / kick_helper_ft.INTEGRITY_EVIDENCE_NAME
            if smoke:
                record["smoke"] = True
            kick_helper_ft.write_evidence(
                kick_helper_ft._public_integrity_record(record),
                ckpt_path,
                mode=0o400,
            )
            try:
                sealed = kick_helper_ft.load_integrity_completion(ckpt_path)
            except kick_helper_ft.KickRefused as exc:
                return _bad(exc.field, exc.expected, exc.actual)
            evidence["sha256_evidence"] = sealed["sha256_evidence"]
            evidence["integrity_evidence"] = sealed["integrity_evidence"]
            evidence["result"] = sealed["result"]
            evidence["exit_code"] = record.get("exit_code", 0)
            if smoke:
                evidence["smoke"] = True
                evidence["checkpoint_integrity_status"] = kick_helper_ft.CHECKPOINT_UNSCORED
            else:
                evidence["checkpoint_integrity_evidence_path"] = str(ckpt_path.resolve())
                evidence["checkpoint_integrity_status"] = record["status"]
    evidence["post_train_shas"] = record["computed_shas"]
    evidence["post_train_host"] = record["host"]
    evidence["post_train_paths"] = record["paths"]
    evidence["trust_blobs"] = blobs
    evidence["head_sha"] = blobs.get("HEAD")
    if record["status"] != kick_helper_ft.CHECKPOINT_MATCH:
        return _bad(record.get("field", "post_train"), record.get("expected"), record.get("actual"))
    result = {
        "ok": True,
        "pack_id": pack_id,
        "run_id": run_id,
        "launched": True,
        "host": host,
        "paths": recorded_paths,
        "trainer_config": trainer_config,
        "trainer_argv": trainer_argv,
        "post_train_shas": record["computed_shas"],
        "post_train_host": record["host"],
        "post_train_paths": record["paths"],
        "kickoff_pin_fetch": fetched_pin,
        "trust_blobs": blobs,
        "head_sha": blobs.get("HEAD"),
        "exit_code": record.get("exit_code", 0),
    }
    if ckpt_id and not smoke:
        result["checkpoint_id"] = ckpt_id
    if smoke:
        result["smoke"] = True
        result.pop("checkpoint_id", None)
    if evidence.get("sha256_evidence"):
        result["sha256_evidence"] = evidence.get("sha256_evidence")
        result["integrity_evidence"] = evidence.get("integrity_evidence")
        result["result"] = evidence.get("result")
    return result


def _json_status(payload: dict[str, Any]) -> str:
    return "200 OK" if payload.get("ok") is True else "400 Bad Request"


def dispatch(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
    query: str = "",
) -> tuple[str, dict[str, Any]]:
    """Route table for :8765. Only POST /train/kickoff can start HELPER FT."""
    method = (method or "").upper()
    path = path or "/"
    query_l = (query or "").lower()
    if "inbox=latest" in query_l or "inbox_latest" in query_l:
        payload = _bad("inbox", "named pack_id", "latest")
        return _json_status(payload), payload
    if path.rstrip("/").endswith("/latest"):
        payload = _bad("inbox", "named pack_id", "latest")
        return _json_status(payload), payload
    if path.rstrip("/") in OTHER_HELPER_FT_START_PATHS or path in OTHER_HELPER_FT_START_PATHS:
        payload = _bad("route", "POST /train/kickoff", f"{method} {path}")
        return _json_status(payload), payload
    if path.rstrip("/") != "/train/kickoff":
        payload = _bad("route", "POST /train/kickoff", f"{method} {path}")
        return _json_status(payload), payload
    if method != "POST":
        payload = _bad("method", "POST", method)
        return _json_status(payload), payload
    payload = handle_train_kickoff(body, launch_trainer=launch_trainer)
    return _json_status(payload), payload


def make_app(*, launch_trainer: LaunchTrainer | None = None):
    """WSGI app for ``POST http://127.0.0.1:8765/train/kickoff``."""

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD") or "GET")
        path = str(environ.get("PATH_INFO") or "/")
        query = str(environ.get("QUERY_STRING") or "")
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            payload = _bad("body", f"<={MAX_BODY_BYTES} bytes", length)
            blob = json.dumps(payload).encode("utf-8")
            start_response(
                "400 Bad Request",
                [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
            )
            return [blob]
        raw = environ.get("wsgi.input").read(length) if length else b""
        if len(raw) > MAX_BODY_BYTES:
            payload = _bad("body", f"<={MAX_BODY_BYTES} bytes", len(raw))
            blob = json.dumps(payload).encode("utf-8")
            start_response(
                "400 Bad Request",
                [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
            )
            return [blob]
        parsed: dict[str, Any] | None
        if not raw:
            parsed = None
        else:
            try:
                loaded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                payload = _bad("body", "JSON object", "invalid JSON")
                blob = json.dumps(payload).encode("utf-8")
                start_response(
                    "400 Bad Request",
                    [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
                )
                return [blob]
            parsed = loaded if isinstance(loaded, dict) else None
            if parsed is None:
                payload = _bad("body", "object", type(loaded).__name__)
                blob = json.dumps(payload).encode("utf-8")
                start_response(
                    "400 Bad Request",
                    [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
                )
                return [blob]
        status, payload = dispatch(
            method, path, parsed, launch_trainer=launch_trainer, query=query
        )
        blob = json.dumps(payload).encode("utf-8")
        start_response(
            status,
            [("Content-Type", "application/json"), ("Content-Length", str(len(blob)))],
        )
        return [blob]

    return app


class TestResponse:
    """Minimal response object for :class:`TestClient`."""

    def __init__(self, status: str, body: bytes) -> None:
        self.status = status
        self.status_code = int(status.split()[0])
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else {}


class TestClient:
    """In-process WSGI test client for the real :8765 handler. No GPU, no TCP."""

    def __init__(self, *, launch_trainer: LaunchTrainer | None = None) -> None:
        self.app = make_app(launch_trainer=launch_trainer)

    def post(self, path: str, json: dict[str, Any] | None = None) -> TestResponse:
        return self.request("POST", path, body=json)

    def get(self, path: str) -> TestResponse:
        return self.request("GET", path)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> TestResponse:
        route, _, query = path.partition("?")
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": route,
            "QUERY_STRING": query,
            "wsgi.input": BytesIO(payload),
            "CONTENT_LENGTH": str(len(payload)),
            "CONTENT_TYPE": "application/json",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": True,
        }
        captured: dict[str, Any] = {"status": "500 Internal Server Error"}

        def start_response(status: str, _headers: list[tuple[str, str]], exc_info: Any = None) -> None:
            del exc_info
            captured["status"] = status

        parts = self.app(environ, start_response)
        return TestResponse(captured["status"], b"".join(parts))


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    launch_trainer: LaunchTrainer | None = None,
) -> None:
    httpd = make_server(host, port, make_app(launch_trainer=launch_trainer))
    httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--serve":
        serve()
        return 0
    raise SystemExit(
        "helper_ft_kickoff is the :8765 HELPER FT handler; factory-trainer POSTs JSON "
        "to POST /train/kickoff (or pass --serve)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
