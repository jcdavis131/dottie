#!/usr/bin/env python3
"""Forge-runner HELPER FT ``POST /train/kickoff`` handler (:8765).

Verifies the staged ``swarm-hq-pin-v2`` file the server already verified
(fd or path under ``FORGE_RUN_PRIVATE_ROOT``) and hashes the exact fds it
passes to the trainer. Never re-fetches a pin from HQ. A pin carried only
in the request body is not provenance. ``build_command`` always passes
``--run-id`` and ``--pin`` to the child. v1 pins are refused for kicks.

``inbox: latest`` and every other HELPER FT start route are refused.
``default_launch_trainer`` refuses unless a real launcher is wired.
``run_private_dir`` must sit under ``FORGE_RUN_PRIVATE_ROOT`` (realpath plus
a dir-fd walk). This handler hashes the exact fd it will pass to the
trainer and never reopens that file by path; the trainer receives sealed
memfds or held ``/proc/self/fd/N`` descriptors. An end-of-training re-hash
mismatch is REFUSED and uses those same fds. Does not promote, does not touch
serve, :8770, or champion files.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Mapping
from wsgiref.simple_server import make_server

_MODULE_FILE = str(globals().get("__file__") or "")
_LAB = str(Path(_MODULE_FILE).resolve().parent) if _MODULE_FILE else "/var/empty"
_SEALED_FILE = (
    (not _MODULE_FILE)
    or _MODULE_FILE.startswith("/proc/")
    or "memfd:" in _MODULE_FILE
)
if not _SEALED_FILE and _LAB not in sys.path:
    sys.path.insert(0, _LAB)

import cam_pin_spec
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


def build_command(
    *,
    pack: Path | str,
    run_id: str,
    pin_path: Path | str,
    log_path: Path | str | None = None,
    kickoff_url: str | None = None,
    smoke: bool = False,
    python: str | None = None,
) -> list[str]:
    """Launcher argv for the HELPER FT child. Always includes ``--run-id`` and ``--pin``."""
    if type(run_id) is not str or not run_id:
        raise kick_helper_ft.KickRefused("run-id", "present", "missing")
    if pin_path is None or pin_path == "":
        raise kick_helper_ft.KickRefused("cam-pin", "staged v2 pin path or fd", "missing")
    cmd = [
        python or sys.executable,
        "-I",
        str(Path(__file__).resolve().parent / "kick_helper_ft.py"),
        "--pack",
        str(pack),
        "--run-id",
        run_id,
        "--pin",
        str(pin_path),
    ]
    if log_path is not None:
        cmd.extend(["--log", str(log_path)])
    if kickoff_url:
        cmd.extend(["--kickoff-url", str(kickoff_url)])
    if smoke:
        cmd.append("--smoke")
    return cmd


def _read_path_once(path: Path, field: str) -> bytes:
    """Single open+read. Caller must not re-open this path for the same pin."""
    try:
        fd = os.open(path, kick_helper_ft._open_flags_read())
    except OSError as exc:
        raise kick_helper_ft.KickRefused(field, "readable regular file", f"OSError:{exc.errno}") from exc
    try:
        return kick_helper_ft._read_fd_bytes(fd)
    except OSError as exc:
        raise kick_helper_ft.KickRefused(field, "readable regular file", f"OSError:{exc.errno}") from exc
    finally:
        os.close(fd)


def seal_code_pins(code_pins: Mapping[str, str], *, root: Path) -> dict[str, int]:
    """Hash+copy each CODE_PINS file in one read into a sealed memfd. No path re-read."""
    base = Path(root).resolve()
    expected = cam_pin_spec.require_code_pins(dict(code_pins))
    verified: dict[str, bytes] = {}
    for rel in cam_pin_spec.CODE_PINS:
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise kick_helper_ft.KickRefused(
                f"cam-pin.code_pins.{rel}", f"under {base}", str(path)
            ) from exc
        buf = _read_path_once(path, f"cam-pin.code_pins.{rel}")
        actual = hashlib.sha256(buf).hexdigest()
        if actual != expected[rel]:
            raise kick_helper_ft.KickRefused(f"cam-pin.code_pins.{rel}", expected[rel], actual)
        verified[rel] = buf
    fds: dict[str, int] = {}
    try:
        for rel, buf in verified.items():
            field = f"cam-pin.code_pins.{rel}"
            name = "codepin-" + rel.replace("/", "_")
            fd = kick_helper_ft._register_held_fd(kick_helper_ft._memfd_create(name))
            kick_helper_ft._write_all(fd, buf, field)
            try:
                os.lseek(fd, 0, os.SEEK_SET)
            except OSError as exc:
                raise kick_helper_ft.KickRefused(field, "seekable memfd", f"OSError:{exc.errno}") from exc
            kick_helper_ft._seal_memfd(fd, field)
            fds[rel] = fd
    except kick_helper_ft.KickRefused:
        for fd in fds.values():
            kick_helper_ft._close_quietly(fd)
        raise
    return fds


def _sealed_bootstrap_source(
    *,
    module_fds: Mapping[str, int],
    main_fd: int,
    repo_root: str,
) -> bytes:
    payload = {
        "module_fds": {name: int(fd) for name, fd in module_fds.items()},
        "main_fd": int(main_fd),
        "repo_root": str(repo_root),
        "lab_rel": "apps/dottie-os/scripts/lab",
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return (
        "#!/usr/bin/env python3\n"
        "import importlib.abc\n"
        "import importlib.machinery\n"
        "import importlib.util\n"
        "import hashlib\n"
        "import json\n"
        "import os\n"
        "import runpy\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"_SEAL = json.loads({blob!r})\n"
        "PINNED = {str(k): int(v) for k, v in _SEAL['module_fds'].items()}\n"
        "MAIN_FD = int(_SEAL['main_fd'])\n"
        "REPO = Path(_SEAL['repo_root']).resolve()\n"
        "LAB = REPO / _SEAL['lab_rel']\n"
        "class PinnedMetaFinder(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path, target=None):\n"
        "        fd = PINNED.get(fullname)\n"
        "        if fd is not None:\n"
        "            origin = f'/proc/self/fd/{fd}'\n"
        "            class _FdLoader(importlib.machinery.SourceFileLoader):\n"
        "                def exec_module(self, module):\n"
        "                    module.__dict__['__file__'] = self.path\n"
        "                    module.__file__ = self.path\n"
        "                    return super().exec_module(module)\n"
        "            loader = _FdLoader(fullname, origin)\n"
        "            spec = importlib.util.spec_from_loader(fullname, loader, origin=origin)\n"
        "            if spec is not None:\n"
        "                spec.has_location = True\n"
        "            return spec\n"
        "        stem = fullname.split('.', 1)[0]\n"
        "        guess = LAB / (fullname.replace('.', '/') + '.py')\n"
        "        if guess.is_file() and stem not in PINNED:\n"
        "            raise ImportError(\n"
        "                f'HELPER FT refused: import {fullname}: expected pinned or stdlib actual unpinned'\n"
        "            )\n"
        "        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)\n"
        "        origin = getattr(spec, 'origin', None) if spec is not None else None\n"
        "        if origin and origin not in ('built-in', 'frozen'):\n"
        "            try:\n"
        "                resolved = Path(origin).resolve()\n"
        "                resolved.relative_to(REPO)\n"
        "            except (ValueError, OSError):\n"
        "                return None\n"
        "            raise ImportError(\n"
        "                f'HELPER FT refused: import {fullname}: expected pinned or stdlib actual unpinned {origin}'\n"
        "            )\n"
        "        return None\n"
        "cleaned = []\n"
        "for entry in sys.path:\n"
        "    if not entry:\n"
        "        continue\n"
        "    try:\n"
        "        Path(entry).resolve().relative_to(REPO)\n"
        "        continue\n"
        "    except (ValueError, OSError):\n"
        "        cleaned.append(entry)\n"
        "sys.path[:] = cleaned\n"
        "sys.meta_path.insert(0, PinnedMetaFinder())\n"
        "if '--sealed-probe' in sys.argv:\n"
        "    os.lseek(MAIN_FD, 0, os.SEEK_SET)\n"
        "    digest = hashlib.sha256()\n"
        "    with open(f'/proc/self/fd/{MAIN_FD}', 'rb') as handle:\n"
        "        digest.update(handle.read())\n"
        "    os.lseek(MAIN_FD, 0, os.SEEK_SET)\n"
        "    import cam_pin_spec, content_uuid, kick_helper_ft  # noqa: F401\n"
        "    extra = os.environ.get('HELPER_FT_PROBE_IMPORT')\n"
        "    if extra:\n"
        "        __import__(extra)\n"
        "    sys.stdout.write('HELPER_FT_SEALED_OK\\n')\n"
        "    sys.stdout.write('HELPER_FT_SEALED_MAIN_SHA=' + digest.hexdigest() + '\\n')\n"
        "    raise SystemExit(0)\n"
        "runpy.run_path(f'/proc/self/fd/{MAIN_FD}', run_name='__main__')\n"
    ).encode("ascii")


def launch_sealed_child(
    *,
    root: Path,
    pin: Mapping[str, Any],
    run_id: str,
    argv: list[str] | None = None,
    python: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    after_seal: Callable[[], None] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Verify the v2 pin, seal CODE_PINS into memfds, exec ``python -I`` from those fds.

    The repo is not on the child ``sys.path``. Unpinned first-party imports are
    refused. Fds are inherited; hashed paths are never re-opened after the
    single read in ``seal_code_pins``.
    """
    try:
        parsed = cam_pin_spec.parse_kick_pin_payload(dict(pin), run_id=run_id)
    except cam_pin_spec.CamPinError as exc:
        raise kick_helper_ft.KickRefused(exc.field, exc.expected, exc.actual) from exc
    base = Path(root).resolve()
    fds: dict[str, int] = {}
    bootstrap_fd: int | None = None
    try:
        fds = seal_code_pins(parsed["code_pins"], root=base)
        if after_seal is not None:
            after_seal()
        module_fds = {
            name: fds[rel] for name, rel in cam_pin_spec.CODE_PIN_MODULE_NAMES.items()
        }
        main_fd = fds[cam_pin_spec.CODE_PIN_MODULE_NAMES["kick_helper_ft"]]
        bootstrap = _sealed_bootstrap_source(
            module_fds=module_fds, main_fd=main_fd, repo_root=str(base)
        )
        bootstrap_fd = kick_helper_ft._register_held_fd(
            kick_helper_ft._memfd_create("codepin-bootstrap")
        )
        kick_helper_ft._write_all(bootstrap_fd, bootstrap, "sealed.bootstrap")
        try:
            os.lseek(bootstrap_fd, 0, os.SEEK_SET)
        except OSError as exc:
            raise kick_helper_ft.KickRefused(
                "sealed.bootstrap", "seekable memfd", f"OSError:{exc.errno}"
            ) from exc
        kick_helper_ft._seal_memfd(bootstrap_fd, "sealed.bootstrap")
        pass_fds = tuple([bootstrap_fd, *fds.values()])
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        if extra_env:
            env.update({str(key): str(value) for key, value in extra_env.items()})
        cmd = [
            python or sys.executable,
            "-I",
            f"/proc/self/fd/{bootstrap_fd}",
            *(argv or ["--sealed-probe"]),
        ]
        return subprocess.run(
            cmd,
            pass_fds=pass_fds,
            cwd="/",
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    finally:
        if bootstrap_fd is not None:
            kick_helper_ft._close_quietly(bootstrap_fd)
        for fd in fds.values():
            kick_helper_ft._close_quietly(fd)


def require_staged_v2_pin(
    pin_ref: object,
    pack_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Verify the staged v2 pin the server handed over. Never fetches."""
    try:
        record = kick_helper_ft.load_staged_v2_pin(pin_ref, run_id=run_id)
    except kick_helper_ft.KickRefused as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    pin_pack = record.get("pack_id")
    if type(pin_pack) is not str or not pin_pack:
        return _bad("cam-pin.pack_id", "present", "missing")
    if pin_pack != pack_id:
        return _bad("cam-pin.pack_id", pack_id, pin_pack)
    if record.get("run_id") != run_id:
        return _bad("cam-pin.binding.run_id", record.get("run_id"), run_id)
    pin: dict[str, Any] = dict(record)
    pin["source"] = PIN_SOURCE
    for sha_field, _filename, _manifest_rows, pin_rows_field in ARTIFACTS:
        required = _require_sha(f"cam-pin.{sha_field}", record.get(sha_field))
        if isinstance(required, dict):
            return required
        pin[sha_field] = required
        if pin_rows_field in record:
            rows = _require_int(f"cam-pin.{pin_rows_field}", record.get(pin_rows_field))
            if isinstance(rows, dict):
                return rows
            pin[pin_rows_field] = rows
        elif pin_rows_field not in pin:
            missing = _require_int(f"cam-pin.{pin_rows_field}", record.get(pin_rows_field))
            if isinstance(missing, dict):
                return missing
    return {"ok": True, "pin": pin}


def handle_train_kickoff(
    body: dict[str, Any] | None,
    *,
    launch_trainer: LaunchTrainer | None = None,
) -> dict[str, Any]:
    """Refuse HELPER FT kickoff unless the staged v2 pin matches re-hashed files.

    Verifies the staged pin file (fd or path under the private root). Never
    fetches. A body-only pin is refused. ``stampVerified`` and ``pack_matches``
    are advisory and never sufficient. ``inbox: latest`` is never accepted.
    Evidence ``ok: true`` is not trust. v1 pins are refused.
    """
    if not isinstance(body, dict):
        return _bad("body", "object", type(body).__name__)
    try:
        if cam_pin_spec.PINNED_COPY_ROOT is None:
            blobs = cam_pin_spec.require_committed_trust()
        else:
            pins = cam_pin_spec.live_code_pins(root=cam_pin_spec.PINNED_COPY_ROOT)
            blobs = dict(pins)
            blobs["HEAD"] = "pinned-copy"
    except cam_pin_spec.CamPinError as trans_exc:
        return _bad(trans_exc.field, trans_exc.expected, trans_exc.actual)
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
    # Never take evidence_path, trust_blobs, or fd names from the request body.
    evidence_path = None
    if isinstance(evidence, dict):
        evidence.pop("trust_blobs", None)
    pin = body.get("pin")
    if not isinstance(pin, dict) or not pin:
        return _bad("pin", "present", "missing")
    if pin.get("pack_id") != pack_id:
        return _bad("pin.pack_id", pack_id, pin.get("pack_id"))
    run_private = body.get("run_private_dir")
    if type(run_private) is not str or not run_private:
        return _bad("run_private_dir", "present", "missing")
    try:
        root = kick_helper_ft._require_run_private_dir(Path(run_private))
    except kick_helper_ft.KickRefused as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    body.pop("pin_path", None)
    candidate = root / kick_helper_ft.STAGED_PIN_NAME
    pin_ref = str(candidate) if candidate.is_file() else None
    if pin_ref is None or pin_ref == "":
        return _bad("cam-pin", "staged v2 pin fd or path under run_private_root", "missing")
    staged = require_staged_v2_pin(pin_ref, pack_id, run_id)
    if staged.get("ok") is not True:
        return staged
    hq_pin = staged["pin"]
    hq_id = cam_pin_spec.pin_identity(hq_pin)
    body_id = cam_pin_spec.pin_identity(pin)
    ev_pin = evidence.get("pin") if isinstance(evidence.get("pin"), dict) else {}
    ev_id = cam_pin_spec.pin_identity(ev_pin) if ev_pin else None
    if body_id != hq_id:
        return _bad("pin", hq_id, body_id)
    if ev_id is not None and ev_id != hq_id:
        return _bad("evidence.pin", hq_id, ev_id)
    fetched_pin = {"ok": True, "pin": hq_pin, "source": PIN_SOURCE, "staged": True}
    evidence["kickoff_pin_fetch"] = fetched_pin
    pin_root = (
        Path(cam_pin_spec.PINNED_COPY_ROOT)
        if cam_pin_spec.PINNED_COPY_ROOT is not None
        else cam_pin_spec.code_pins_root()
    )
    try:
        cam_pin_spec.verify_code_pins_match(hq_pin["code_pins"], root=pin_root)
        sealed_pins = seal_code_pins(hq_pin["code_pins"], root=pin_root)
        for fd in sealed_pins.values():
            kick_helper_ft._close_quietly(fd)
        kick_helper_ft.probe_sealed_code_pins(
            root=pin_root, pin=hq_pin, run_id=run_id
        )
    except cam_pin_spec.CamPinError as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    except kick_helper_ft.KickRefused as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    claimed_paths = body.get("paths")
    if isinstance(claimed_paths, dict):
        pack_dir_claim = claimed_paths.get("pack_dir")
        if pack_dir_claim:
            return _bad("paths.pack_dir", "absent (run-dir copies only)", pack_dir_claim)
        # Body path names (including /proc/self/fd/N) are not used. Open from dir_fd.
    held_fds: dict[str, int] = {}
    sealed_fds: dict[str, int] = {}
    verified_bufs: dict[str, bytes] = {}
    manifest_shas: dict[str, str] = {}
    manifest: dict[str, Any] = {}
    try:
        dir_fd = kick_helper_ft._open_dir_nofollow(str(root))
        try:
            try:
                man_fd = os.open(
                    MANIFEST_FILE,
                    kick_helper_ft._open_flags_read(),
                    dir_fd=dir_fd,
                )
            except OSError as exc:
                return _bad(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
            held_fds["manifest"] = man_fd
            try:
                man_buf = kick_helper_ft._read_fd_bytes(man_fd)
                try:
                    os.lseek(man_fd, 0, os.SEEK_SET)
                except OSError:
                    pass
            except OSError as exc:
                return _bad(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
            verified_bufs["manifest"] = man_buf
            try:
                man_text = man_buf.decode("utf-8")
            except UnicodeDecodeError:
                return _bad(MANIFEST_FILE, "utf-8 text", "invalid encoding")
            try:
                parsed_manifest = json.loads(
                    man_text, object_pairs_hook=_no_duplicate_manifest_keys
                )
            except ValueError as exc:
                if "duplicate" in str(exc):
                    return _bad(MANIFEST_FILE, "unique keys", str(exc))
                return _bad(MANIFEST_FILE, "valid JSON object", "invalid JSON")
            if not isinstance(parsed_manifest, dict):
                return _bad(MANIFEST_FILE, "object", type(parsed_manifest).__name__)
            manifest = parsed_manifest
            if manifest.get("pack_id") != pack_id:
                return _bad("pack_id", pack_id, manifest.get("pack_id"))
            man_digest = hashlib.sha256(man_buf).hexdigest()
            claimed_manifest = hq_pin.get("sha256_manifest")
            if claimed_manifest != man_digest:
                return _bad("cam-pin.sha256_manifest", man_digest, claimed_manifest)
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
                try:
                    fd = os.open(
                        filename,
                        kick_helper_ft._open_flags_read(),
                        dir_fd=dir_fd,
                    )
                except OSError as exc:
                    if getattr(exc, "errno", None) in (errno.ELOOP, getattr(errno, "EPERM", None)):
                        return _bad(sha_field, "regular file", "symlink")
                    return _bad(filename, "readable regular file", f"OSError:{exc.errno}")
                held_fds[path_key] = fd
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode):
                        return _bad(sha_field, "regular file", "non-regular")
                    buf = kick_helper_ft._read_fd_bytes(fd)
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                    except OSError:
                        pass
                except OSError as exc:
                    return _bad(filename, "readable regular file", f"OSError:{exc.errno}")
                counted = sum(1 for line in buf.splitlines() if line.strip())
                if pin_rows != counted:
                    return _bad(pin_rows_field, pin_rows, counted)
                actual = hashlib.sha256(buf).hexdigest()
                if actual != hq_sha:
                    return _bad(sha_field, hq_sha, actual)
                if actual != req:
                    return _bad(sha_field, req, actual)
                verified_bufs[path_key] = buf
        finally:
            kick_helper_ft._close_quietly(dir_fd)
        try:
            sealed_fds = kick_helper_ft.seal_verified_buffers(verified_bufs)
        except kick_helper_ft.KickRefused as exc:
            return _bad(exc.field, exc.expected, exc.actual)
        fd_paths = kick_helper_ft.trainer_fd_paths(sealed_fds)
        try:
            kick_helper_ft.enforce_pack_gates(
                manifest,
                fd_paths,
                smoke=smoke,
                pack_dir=str(root),
            )
        except kick_helper_ft.KickRefused as exc:
            return _bad(exc.field, exc.expected, exc.actual)
        host = socket.gethostname()
        trainer_config = {"host": host, "paths": fd_paths}
        trainer_argv = kick_helper_ft.build_trainer_argv(fd_paths)
        launch_body = dict(body)
        launch_body.pop("pin_path", None)
        launch_body["paths"] = fd_paths
        launch_body["trainer_config"] = trainer_config
        launch_body["trainer_argv"] = trainer_argv
        ev_paths = evidence.get("paths") if isinstance(evidence.get("paths"), dict) else {}
        launch_evidence = dict(evidence)
        launch_evidence.pop("private_copy_shas", None)
        launch_evidence["paths"] = fd_paths
        launch_evidence["run_private_dir"] = str(root.resolve())
        if isinstance(ev_paths, dict) and ev_paths.get("pack_dir"):
            return _bad("paths.pack_dir", "absent (run-dir copies only)", ev_paths.get("pack_dir"))
        launch_body["evidence"] = launch_evidence
        launcher = launch_trainer if launch_trainer is not None else default_launch_trainer
        launched = launcher(launch_body)
        if not isinstance(launched, dict) or launched.get("ok") is not True:
            return _bad("trainer", "ok", launched)
        exit_info = kick_helper_ft.wait_for_training_exit(launched)
        record = kick_helper_ft.rehash_held_fds(
            sealed_fds,
            pin=hq_pin,
            manifest_shas=manifest_shas,
            host=host,
            refuse_on_mismatch=True,
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
                public = kick_helper_ft._public_integrity_record(record)
                try:
                    sealed = kick_helper_ft.write_integrity_evidence_held(public, ckpt_path)
                except kick_helper_ft.KickRefused as exc:
                    return _bad(exc.field, exc.expected, exc.actual)
                in_memory_result = (
                    record["status"]
                    if record.get("status")
                    in (kick_helper_ft.CHECKPOINT_MATCH, kick_helper_ft.CHECKPOINT_REFUSED)
                    else kick_helper_ft.CHECKPOINT_REFUSED
                )
                evidence["sha256_evidence"] = sealed["sha256_evidence"]
                evidence["integrity_evidence"] = sealed["integrity_evidence"]
                evidence["result"] = in_memory_result
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
            "paths": fd_paths,
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
    except kick_helper_ft.KickRefused as exc:
        return _bad(exc.field, exc.expected, exc.actual)
    finally:
        for fd in list(held_fds.values()) + list(sealed_fds.values()):
            kick_helper_ft._close_quietly(fd)


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
