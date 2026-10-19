#!/usr/bin/env python3
"""Stage-5 HELPER factory-trainer kick: point-of-use pack integrity, then kickoff.

The trust anchor is Cam's Ed25519 signature over the canonical pin bytes
(see ``cam_pin_spec.py``), verified against the public key committed at
``apps/dottie-os/trust/cam_pin_ed25519.pub``. Swarm HQ is only a transport:
``stampVerified`` and ``pack_matches`` are advisory and never sufficient.
The HQ origin is the hardcoded ``cam_pin_spec.SWARM_HQ_ORIGIN`` (HTTPS, no
redirects, no proxies). There is no ``SWARM_HQ_URL`` env, CLI, or config
override. Redis is never read.

This process hashes and counts the run-private copies itself and compares
those to the signed v2 pin and MANIFEST. The launcher passes a required
``--run-id`` that must match the pin binding. The child verifies the staged
v2 pin file (fd or path under the private root) the server already verified
and never fetches from HQ. ``--cam-pin``, a pin env var, and a local pin
file in the inbox pack are refused before hashing or kickoff. After the gate
passes, this script POSTs ``/train/kickoff``; ``inbox: latest`` is never
sent. v1 pins are verify-only history and are refused for kicks. Copies are 0400 in a 0700 directory under a container-private tmpfs
(``FORGE_RUN_PRIVATE_ROOT``, default ``/run/forge-runner/private``). The
**forge-runner server** creates that default root (mode 0700, euid-owned,
on the compose tmpfs) before launching this child; this process fails
closed if the root is missing and never POSTs to create it. r5 sized the
tmpfs at 16 MiB — enough for dual copies of a tiny pack (~8 MiB) and
nothing more. Real packs need
``FORGE_RUN_PRIVATE_RECOMMENDED_BYTES`` (256 MiB) so pack+train+holdout+
MANIFEST staging plus sealed memfds fit; a pack that exceeds free space
is refused with ``run_private.capacity``.

Verification finishes **before** the trainer starts. This process opens
each staged copy with ``O_NOFOLLOW``, requires a regular file, ``nlink==1``,
euid owner, no group/other write, and ``st_dev`` equal to the tmpfs root,
hashes that fd, compares in constant time to the signed pin (and
re-verifies MANIFEST bytes at point of use), then hands the trainer
sealed memfds (``F_SEAL_WRITE|F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_SEAL``)
or held ``O_RDONLY`` fds via ``/proc/self/fd/N`` — never reopenable
paths. An end-of-training re-hash, if any, is informational and runs
against those same fds. Completion ``result`` and ``sha256_evidence``
come from the 0400 evidence file this process wrote, never from scraped
stdout. Nonzero trainer exit, a signal, or a timeout is ``REFUSED`` even
when hashes match. This process POSTs a kick event and a completion event
to the pinned HQ origin. Run-private copies are removed on every path
(success, refusal, exception, SIGTERM/atexit).

There is no skip flag or skip env var. Does not promote, does not touch serve,
:8770, champion files, or the LIVE gate.
"""
from __future__ import annotations

import argparse
import atexit
import base64
import builtins
import ctypes
import ctypes.util
import errno
import fcntl
import hashlib
import hmac
import html
import json
import math
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import io
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, NoReturn

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
import content_uuid
import denied_field_schema
import row_fields

PACK_FILE = "curated_pack_v2.jsonl"
TRAIN_FILE = "curated_pack_v2_train.jsonl"
HOLDOUT_FILE = "curated_pack_v2_holdout.jsonl"
MANIFEST_FILE = "MANIFEST.json"
DEFAULT_LOG_NAME = "helper_ft.log"
DEFAULT_KICKOFF_URL = "http://127.0.0.1:8765/train/kickoff"
SWARM_HQ_AGENT_TOKEN_ENV = cam_pin_spec.SWARM_HQ_AGENT_TOKEN_ENV
PIN_SOURCE = "swarm-hq-cam-pin"
HQ_PIN_REQUIRED_KEYS = cam_pin_spec.HQ_PIN_REQUIRED_KEYS
HQ_PIN_ALLOWED_KEYS = cam_pin_spec.HQ_PIN_ALLOWED_KEYS
CHUNK = 1 << 20
SHA256_LEN = 64
GIT_SHA_LEN = 40
_HEX = frozenset("0123456789abcdef")
FORGE_ENTRYPOINT_PINS_ENV = "FORGE_ENTRYPOINT_PINS"
FORGE_PINS_SOURCE_COMMIT_ENV = "FORGE_PINS_SOURCE_COMMIT"
FORGE_RUN_PRIVATE_ROOT_ENV = "FORGE_RUN_PRIVATE_ROOT"
DEFAULT_FORGE_RUN_PRIVATE_ROOT = "/run/forge-runner/private"
TMPFS_MAGIC = 0x01021994
# r5 compose tmpfs is 16 MiB — dual-copy of a tiny pack only. Real packs need 256 MiB.
FORGE_RUN_PRIVATE_R5_BYTES = 16 * 1024 * 1024
FORGE_RUN_PRIVATE_RECOMMENDED_BYTES = 256 * 1024 * 1024
F_ADD_SEALS = getattr(fcntl, "F_ADD_SEALS", 1033)
F_SEAL_SEAL = getattr(fcntl, "F_SEAL_SEAL", 0x0001)
F_SEAL_SHRINK = getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
F_SEAL_GROW = getattr(fcntl, "F_SEAL_GROW", 0x0004)
F_SEAL_WRITE = getattr(fcntl, "F_SEAL_WRITE", 0x0008)
MEMFD_SEALS = F_SEAL_WRITE | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_SEAL
MFD_CLOEXEC = getattr(os, "MFD_CLOEXEC", 1)
MFD_ALLOW_SEALING = getattr(os, "MFD_ALLOW_SEALING", 2)
PROC_SELF_FD_PREFIX = "/proc/self/fd/"
SHA_FIELD_BY_PATH_KEY = {
    "pack": "sha256_pack",
    "train": "sha256_train",
    "holdout": "sha256_holdout",
    "manifest": "sha256_manifest",
}
PINS_JSON_NAME = "PINS.json"
PINNED_COPY_DEPTH = 4
PINNED_COPY_REASON = "pinned-copy"
PINNED_COPY_KICK_REL = "apps/dottie-os/scripts/lab/kick_helper_ft.py"
PINNED_COPY_KICKOFF_REL = "apps/dottie-os/scripts/lab/helper_ft_kickoff.py"
PINNED_COPY_SPEC_REL = "apps/dottie-os/scripts/lab/cam_pin_spec.py"
PINNED_COPY_UUID_REL = "apps/dottie-os/scripts/lab/content_uuid.py"
REPO_TRUST_PUB_REL = "apps/dottie-os/trust/cam_pin_ed25519.pub"
REPO_TRUST_KEY_ID_REL = "apps/dottie-os/trust/cam_pin_key_id"
REPO_TRUST_RESERVED_REL = "apps/dottie-os/trust/reserved_content_uuids.jsonl"
# Server layout. Child and launcher both pin these exact repo-relative paths.
PINNED_COPY_PUB_REL = REPO_TRUST_PUB_REL
PINNED_COPY_KEY_ID_REL = REPO_TRUST_KEY_ID_REL
PINNED_COPY_RESERVED_REL = REPO_TRUST_RESERVED_REL
# One object: cam_pin_spec.CODE_PINS. No second pin-list literal.
REQUIRED_PINS = cam_pin_spec.CODE_PINS
PINNED_COPY_REQUIRED_RELS = REQUIRED_PINS
ENTRYPOINT_PIN_RELS = REQUIRED_PINS
ENTRYPOINT_PIN_BASENAMES = tuple(
    Path(rel).name for rel in REQUIRED_PINS if rel.endswith(".py")
)
STAGED_PIN_NAME = "cam-pin-v2.json"
PINS_JSON_MAX_BYTES = 64 * 1024
_GATE_OK = object()
_UNSET = object()
RESERVED_EVAL_PARTITION: dict[str, object] = {
    "n": content_uuid.RESERVED_EVAL_PARTITION_N,
    "residues": sorted(content_uuid.RESERVED_EVAL_PARTITION_RESIDUES),
}
# Per-entry uuid-less allowlist. Keys are (source.hf, source.config) or
# (source.hf, source.config, source.revision). A 3-tuple requires an exact
# source.revision match. MANIFEST cannot add, remove, or edit entries.
# v3 Math rows carry no revision, so the live key is the 2-tuple.
ULTRADATA_MATH_L1_SHAPE: dict[str, object] = {
    "schema": "dottie-os-decision-schema-1.0.0",
    "tier": "L2",
    "top_keys": frozenset(
        {
            "schema",
            "id",
            "tier",
            "source",
            "state",
            "questions",
            "labels",
            "consent",
            "subset",
        }
    ),
    "source_keys": frozenset(
        {"hf", "config", "split", "row", "record_id", "content_uuid"}
    ),
    "state_keys": frozenset({"message", "meta"}),
    "state_meta_keys": frozenset({"kind"}),
    "state_meta_kind": "math_problem",
    "questions_keys": frozenset({"difficulty", "solvable"}),
    "questions_fields": {
        "difficulty": frozenset({"type", "instructions", "criteria"}),
        "solvable": frozenset({"type", "instructions"}),
    },
    "questions_types": {"difficulty": "score", "solvable": "noul"},
    "labels_keys": frozenset({"difficulty", "solvable"}),
    "labels_fields": {
        "difficulty": frozenset({"type", "score"}),
        "solvable": frozenset({"type", "noul"}),
    },
    "labels_types": {"difficulty": "score", "solvable": "noul"},
    "labels_score_range": (0.0, 1.0),
    "consent_required": True,
    "consent_champion": False,
    "consent_keys": frozenset({"capture_training", "public_hf", "champion"}),
    "forbidden_keys": frozenset(
        {
            "trajectoryid",
            "trajectory",
            "step",
            "steps",
            "toolcall",
            "toolcalls",
            "tooluse",
            "functioncall",
            "action",
            "command",
            "shell",
            "bash",
            "tool",
            "cmd",
            "toolname",
            "function",
            "arguments",
            "exec",
            "run",
            "subprocess",
            "sh",
        }
    ),
    "forbidden_string_patterns": (
        r"\$\(",
        r"\b(?:ba)?sh\s+-c\b",
        r"\b(?:curl|wget)\b[\s\S]{0,120}\|\s*(?:ba)?sh\b",
        r"\bbase64\b[\s\S]{0,120}\|\s*(?:ba)?sh\b",
        r"<tool_call\s*>",
        r"['\"]tool['\"]\s*:",
        r"['\"]command['\"]\s*:",
        r"(?:```|~~~)\s*(?:ba)?sh\b",
        r"(?:```|~~~)\s*zsh\b",
        r"\bpython(?:3)?\s+-c\b",
        r"(?<!\\)\brm\s+-",
        r"\btool\s*=",
        r"`[A-Za-z][A-Za-z0-9_./-]*`",
    ),
}
UUIDLESS_SOURCE_ALLOWLIST: dict[tuple[str, ...], dict[str, object]] = {
    ("openbmb/UltraData-Math", "UltraData-Math-L1"): ULTRADATA_MATH_L1_SHAPE,
}
# Closed pack-subset allowlist. Case-variant / unknown / missing → refused.
PACK_SUBSETS = frozenset({"Math", "Agent", "Code"})
_HF_TO_SUBSET = {
    "openbmb/UltraData-Math": "Math",
    "openbmb/UltraData-SFT-Agent-2609": "Agent",
    "openbmb/UltraData-Code": "Code",
}
RESERVED_CONTENT_UUIDS_REL = PINNED_COPY_RESERVED_REL
RESERVED_CONTENT_UUIDS_NAME = "reserved_content_uuids.jsonl"
# Gate-owned sha of apps/dottie-os/trust/reserved_content_uuids.jsonl. Not argv/env.
RESERVED_CONTENT_UUIDS_SHA256 = (
    "bc8926d5a18adf4105372c528fcbcfd32ca898e6235c1701859b837be435163c"
)
RESERVED_CONTENT_UUIDS_MIN_ROWS = 250
RESERVED_NEAR_DUP_FPS_REL = "apps/dottie-os/trust/reserved_near_dup_fingerprints.jsonl"
RESERVED_NEAR_DUP_FPS_NAME = "reserved_near_dup_fingerprints.jsonl"
RESERVED_NEAR_DUP_FPS_SHA256 = (
    "9ce40baf0bbdc30f78a88282a6ab833b3b0adf820315d441f77c9a8e7f16aae5"
)
# Gate-config path for the HMAC shingle key. Never from the request body.
RESERVED_NEAR_DUP_HMAC_KEY_PATH = "/run/forge-runner/reserved_near_dup_hmac.key"
RESERVED_NEAR_DUP_HMAC_KEY_ID = "RESERVED_NEAR_DUP_HMAC_KEY_ID_PLACEHOLDER"
# S-SHORTREF: refuse N refs with fewer than 16 unique shingles. Mill's builder
# also enforces nchar >= 20 OR |B| >= 16 at build time; the public file has no nchar.
MIN_REF_SHINGLES = 16
_FP_LENGTH_KEY_FOLDED = frozenset(
    {
        "nchar",
        "l",
        "length",
        "nchars",
        "n_char",
        "n_chars",
        "nlen",
        "n_len",
        "nbytes",
        "n_bytes",
        "token_count",
        "tokencount",
        "shingle_count",
        "shinglecount",
        "ref_len",
        "reflen",
        "b_size",
        "bsize",
    }
)
_PLACEHOLDER_MARKERS = (
    "PLACEHOLDER",
    "NOT_A_LIVE_ROW",
    "RESERVED_EVAL_PARTITION_PLACEHOLDER_NOT_A_LIVE_ROW",
    "RESERVED_NEAR_DUP_FINGERPRINTS_PLACEHOLDER_NOT_A_LIVE_ROW",
)
_FP_PLACEHOLDER_LINES = frozenset(
    {
        '{"id":"reserved-near-dup-fps-placeholder","placeholder":"RESERVED_NEAR_DUP_FINGERPRINTS_PLACEHOLDER_NOT_A_LIVE_ROW"}',
        "RESERVED_NEAR_DUP_FINGERPRINTS_PLACEHOLDER_NOT_A_LIVE_ROW",
    }
)
_HMAC_KEY_BYTES: bytes | None = None
_HMAC_KEY_ID_LOADED: str | None = None
# Strip format/combining marks and non-whitespace controls. Keep \t \n \r
# so they collapse as whitespace (``$\\tls`` → ``$ ls``). Keep C0 separators
# ``\x1c``-``\x1e`` so they remain line terminators instead of disappearing.
_SHAPE_STRIP_CATS = frozenset({"Cf", "Mn", "Me"})
_SHAPE_KEEP_CC = frozenset("\t\n\r\x0b\x0c\u0085\x1c\x1d\x1e")
_SHAPE_LINE_TERMINATORS = frozenset("\n\r\u2028\u2029\u0085\x0b\x0c\x1c\x1d\x1e")
_SHAPE_BLANK_CHARS = frozenset("\u3164\u115f\u1160\uffa0\u2800")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")
_HEX_ESCAPE_RE = re.compile(r"\\x([0-9a-fA-F]{2})")
_PERCENT_ESCAPE_RE = re.compile(r"%([0-9a-fA-F]{2})")
_SHAPE_COMMAND_WORDS = frozenset(
    {
        "ls",
        "cat",
        "rm",
        "curl",
        "wget",
        "bash",
        "sh",
        "zsh",
        "dash",
        "python",
        "python3",
        "sudo",
        "chmod",
        "chown",
        "dd",
        "nc",
        "ncat",
        "exec",
        "eval",
        "kill",
        "pkill",
        "apt",
        "yum",
        "dnf",
        "pip",
        "npm",
        "find",
        "xargs",
        "tee",
        "touch",
        "mv",
        "cp",
        "ln",
        "head",
        "tail",
        "less",
        "more",
        "vi",
        "vim",
        "nano",
        "ssh",
        "scp",
        "rsync",
        "mount",
        "umount",
        "systemctl",
        "service",
        "docker",
        "kubectl",
        "perl",
        "node",
        "git",
        "env",
        "id",
        "echo",
        "ruby",
        "php",
        "lua",
    }
)
_CYRILLIC_LATIN = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "і": "i",
        "ј": "j",
        "ѕ": "s",
        "һ": "h",
        "г": "r",
        "м": "m",
        "т": "t",
        "к": "k",
        "н": "h",
        "в": "b",
        "А": "A",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "У": "Y",
        "Х": "X",
        "Г": "R",
        "М": "M",
        "Т": "T",
        "К": "K",
        "Н": "H",
        "В": "B",
        "α": "a",
        "Α": "A",
        "β": "b",
        "Β": "B",
        "ε": "e",
        "Ε": "E",
        "ι": "i",
        "Ι": "I",
        "κ": "k",
        "Κ": "K",
        "ν": "v",
        "Ν": "N",
        "ο": "o",
        "Ο": "O",
        "ρ": "p",
        "Ρ": "P",
        "τ": "t",
        "Τ": "T",
        "υ": "u",
        "Υ": "Y",
        "χ": "x",
        "Χ": "X",
        "η": "n",
        "Η": "H",
        "μ": "m",
        "Μ": "M",
        "σ": "s",
        "ς": "s",
        "Σ": "S",
        "γ": "y",
        "ω": "w",
        "Ω": "W",
    }
)
TRAINER_PATH_FILES: dict[str, str] = {
    "pack": PACK_FILE,
    "train": TRAIN_FILE,
    "holdout": HOLDOUT_FILE,
    "manifest": MANIFEST_FILE,
}
PATH_KEY_BY_SHA = {
    "sha256_pack": "pack",
    "sha256_train": "train",
    "sha256_holdout": "holdout",
}
INTEGRITY_EVIDENCE_NAME = "integrity_evidence.json"
INTEGRITY_EVIDENCE_LINE_PREFIX = "HELPER_FT_INTEGRITY_EVIDENCE"
CHECKPOINT_MATCH = "MATCH"
CHECKPOINT_REFUSED = "REFUSED"
CHECKPOINT_UNSCORED = "unscored"
STATE_LEAK_KEYS = frozenset(
    {"risk_hint", "halt_class", "provenance", "agent_config", "category"}
)
# Historical 185133 key names. The gate does **not** refuse on names alone:
# a denylist key with a constant or uncorrelated value must pass. Detection
# is pack-level value predictiveness (see collect_state_leaks).
LEAK_MIN_SUPPORT = 2
LEAK_U_THRESHOLD = 0.50
LEAK_LIFT_MARGIN = 0.20
LEAK_NEAR_PERFECT_ACC = 0.999
LEAK_B64_MIN_LEN = 8
LEAK_B64_MAX_DECODED = 256
LEAK_BOOL_TRUE = "__bool__:true"
LEAK_BOOL_FALSE = "__bool__:false"
LEAK_NULL = "__null__"
LEAK_ABSENT = "__absent__"
LEAK_KEY_COUNT_SUFFIX = ".__key_count__"
LEAK_PRESENT_SUFFIX = ".__present__"
LEAK_ID_RESIDUE_SUFFIX = ".__id_residue__"
LEAK_PAIR_MAX_PAIRS = 64
_LEAK_BOOKKEEPING_KEYS = frozenset(
    {
        "schema",
        "id",
        "questions",
        "labels",
        "source",
        "consent",
        "tier",
        "trajectory_id",
    }
)
_LEAK_PACK_JSONL = frozenset({PACK_FILE, TRAIN_FILE, HOLDOUT_FILE})
_LEAK_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_LEAK_FORMAT_CATS = frozenset({"Cc", "Cf", "Mn", "Me"})
INBOX_LATEST_TOKENS = frozenset(
    {"latest", "inbox_latest", "inbox-latest", "inbox:latest"}
)
INBOX_LATEST_PATH_MARKERS = (
    "inbox_latest",
    "inbox-latest",
    "inbox:latest",
    "20260919-093515-host-meta",
)
LIVE_INBOX_LATEST_DIR = "runs/inbox/20260919-093515-host-meta"
_LATEST_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# (manifest sha field, on-disk file, MANIFEST row field, pin row field)
ARTIFACTS: tuple[tuple[str, str, str, str], ...] = (
    ("sha256_pack", PACK_FILE, "rows", "rows_total"),
    ("sha256_train", TRAIN_FILE, "train_rows", "rows_train"),
    ("sha256_holdout", HOLDOUT_FILE, "holdout_rows", "rows_holdout"),
)

_FORBIDDEN_SKIP_ENV = (
    "DOTTIE_SKIP_HELPER_FT_GATE",
    "HELPER_FT_SKIP_INTEGRITY",
    "SKIP_INTEGRITY",
)
_FORBIDDEN_PIN_ENV = (
    "CAM_PIN",
    "HELPER_FT_CAM_PIN",
    "DOTTIE_CAM_PIN",
    "SWARM_HQ_PIN",
)
_FORBIDDEN_PIN_FILES = (
    "cam-pin.json",
    "cam_pin.json",
    "pin.json",
)

StartTraining = Callable[[Path, dict[str, Any], Path], Any]
KickoffFn = Callable[[dict[str, Any]], Any]


class _LinuxStatfs(ctypes.Structure):
    """glibc ``struct statfs`` on Linux; ``f_type`` is the only field we use."""

    _fields_ = [
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    ]


class KickRefused(Exception):
    """HELPER FT may not start. ``field``, ``expected``, and ``actual`` are named."""

    def __init__(self, field: str, expected: object, actual: object) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"HELPER FT refused: {field}: expected {expected} actual {actual}"
        )


def _refuse(field: str, expected: object, actual: object) -> NoReturn:
    raise KickRefused(field, expected, actual)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_CLEANUP_PATHS: list[Path] = []
_CLEANUP_FDS: list[int] = []
_COPY_DIR_FD: int | None = None
_CLEANUP_INSTALLED = False
_PREV_SIGTERM: Any = None


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _cleanup_run_privates() -> None:
    while _CLEANUP_FDS:
        _close_quietly(_CLEANUP_FDS.pop())
    while _CLEANUP_PATHS:
        path = _CLEANUP_PATHS.pop()
        try:
            _force_remove(path)
        except Exception:
            pass


def _register_run_private_cleanup(path: Path) -> None:
    _CLEANUP_PATHS.append(Path(path))
    _install_cleanup_handlers()


def _register_held_fd(fd: int) -> int:
    _CLEANUP_FDS.append(fd)
    return fd


def _sigterm_cleanup(signum: int, frame: Any) -> None:
    _cleanup_run_privates()
    previous = _PREV_SIGTERM
    if callable(previous) and previous not in (signal.SIG_DFL, signal.SIG_IGN):
        previous(signum, frame)
        return
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _install_cleanup_handlers() -> None:
    global _CLEANUP_INSTALLED, _PREV_SIGTERM
    if _CLEANUP_INSTALLED:
        return
    atexit.register(_cleanup_run_privates)
    try:
        _PREV_SIGTERM = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _sigterm_cleanup)
    except (OSError, ValueError):
        _PREV_SIGTERM = None
    _CLEANUP_INSTALLED = True


def is_proc_self_fd_path(path: object) -> bool:
    if type(path) is not str or not path:
        return False
    if not path.startswith(PROC_SELF_FD_PREFIX):
        return False
    tail = path[len(PROC_SELF_FD_PREFIX) :]
    return tail.isdigit()


def _dup_proc_self_fd(path: str) -> int:
    if not is_proc_self_fd_path(path):
        _refuse("paths", PROC_SELF_FD_PREFIX, path)
    try:
        return os.dup(int(path[len(PROC_SELF_FD_PREFIX) :]))
    except OSError as exc:
        _refuse("paths", "held fd", f"OSError:{exc.errno}")


def _dir_open_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_dir_nofollow(path: str, *, dir_fd: int | None = None) -> int:
    flags = _dir_open_flags()
    try:
        if dir_fd is None:
            return os.open(path, flags)
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError as exc:
        if getattr(exc, "errno", None) in (errno.ELOOP, getattr(errno, "EPERM", None)):
            _refuse("run_private_root", "real directory", "symlink")
        _refuse("run_private_root", "walkable directory", f"OSError:{exc.errno}")


def _require_dir_mode(st: os.stat_result, field: str) -> None:
    if stat.S_ISLNK(st.st_mode):
        _refuse(field, "real directory", "symlink")
    if not stat.S_ISDIR(st.st_mode):
        _refuse(field, "directory", "not a directory")
    go_write = bool(st.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    sticky = bool(st.st_mode & stat.S_ISVTX)
    if go_write and not sticky:
        _refuse(field, "0700 or sticky-root", oct(stat.S_IMODE(st.st_mode)))


def _walk_ancestors_dirfds(path: Path) -> None:
    """O_DIRECTORY|O_NOFOLLOW walk from ``/``. Sticky-root may be group/other-writable."""
    abs_path = Path(os.path.abspath(path))
    parts = abs_path.parts
    if not parts or parts[0] != "/":
        _refuse("run_private_root", "absolute path", str(path))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        _require_dir_mode(os.fstat(fd), "run_private_root")
        for part in parts[1:]:
            nxt = _open_dir_nofollow(part, dir_fd=fd)
            _close_quietly(fd)
            fd = nxt
            _require_dir_mode(os.fstat(fd), "run_private_root")
    finally:
        _close_quietly(fd)


def _dirfd_contained_in(root: Path, path: Path) -> bool:
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    try:
        Path(path_real).relative_to(root_real)
    except ValueError:
        return False
    if path_real == root_real:
        return False
    try:
        root_fd = _open_dir_nofollow(str(root))
    except KickRefused:
        return False
    try:
        root_st = os.fstat(root_fd)
        current = Path(path_real)
        while True:
            try:
                cur_fd = _open_dir_nofollow(str(current))
            except KickRefused:
                return False
            try:
                cur_st = os.fstat(cur_fd)
            finally:
                _close_quietly(cur_fd)
            if (cur_st.st_dev, cur_st.st_ino) == (root_st.st_dev, root_st.st_ino):
                return True
            parent = current.parent
            if parent == current:
                return False
            current = parent
    finally:
        _close_quietly(root_fd)


def _tmpfs_free_bytes(path: Path) -> int:
    try:
        st = os.statvfs(path)
    except OSError as exc:
        _refuse("run_private.capacity", "statvfs", f"OSError:{exc.errno}")
    return int(st.f_bavail) * int(st.f_frsize or st.f_bsize or 1)


def _require_run_private_capacity(root: Path, nbytes: int) -> None:
    if nbytes <= 0:
        return
    free = _tmpfs_free_bytes(root)
    if nbytes > free:
        _refuse(
            "run_private.capacity",
            f"free={free} recommended={FORGE_RUN_PRIVATE_RECOMMENDED_BYTES}",
            f"need={nbytes}",
        )


def create_forge_run_private_root() -> Path:
    """Server-side helper: create ``/run/forge-runner/private`` 0700 on tmpfs.

    The child ``kick()`` path does **not** call this when the default is
    missing — that stays fail-closed (``run_private_root`` / ``missing``).
    Forge-runner must mount the tmpfs large enough for real packs
    (``FORGE_RUN_PRIVATE_RECOMMENDED_BYTES`` = 256 MiB). r5's 16 MiB mount
    only fits dual copies of a tiny pack.
    """
    path = Path(DEFAULT_FORGE_RUN_PRIVATE_ROOT)
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        path.mkdir(mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError as exc:
        _refuse("run_private_root", DEFAULT_FORGE_RUN_PRIVATE_ROOT, f"OSError:{exc.errno}")
    return _require_run_private_root()


def _memfd_create(name: str) -> int:
    if not hasattr(os, "memfd_create"):
        _refuse("trainer.fd", "memfd_create", "missing")
    try:
        return os.memfd_create(name, MFD_CLOEXEC | MFD_ALLOW_SEALING)
    except OSError as exc:
        _refuse("trainer.fd", "memfd_create", f"OSError:{exc.errno}")


def _write_all(fd: int, buf: bytes, field: str) -> None:
    view = memoryview(buf)
    offset = 0
    try:
        while offset < len(buf):
            offset += os.write(fd, view[offset:])
    except OSError as exc:
        _refuse(field, "writable memfd", f"OSError:{exc.errno}")


def _seal_memfd(fd: int, field: str) -> None:
    try:
        fcntl.fcntl(fd, F_ADD_SEALS, MEMFD_SEALS)
    except OSError as exc:
        _refuse(field, "F_SEAL_WRITE|F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_SEAL", f"OSError:{exc.errno}")


def seal_verified_buffers(verified: Mapping[str, bytes]) -> dict[str, int]:
    """Copy verified bytes into sealed memfds. Returns path-key -> fd."""
    fds: dict[str, int] = {}
    try:
        for key, buf in verified.items():
            field = SHA_FIELD_BY_PATH_KEY.get(key, key)
            fd = _register_held_fd(_memfd_create(f"helper-ft-{key}"))
            _write_all(fd, buf, field)
            try:
                os.lseek(fd, 0, os.SEEK_SET)
            except OSError as exc:
                _refuse(field, "seekable memfd", f"OSError:{exc.errno}")
            _seal_memfd(fd, field)
            fds[key] = fd
    except KickRefused:
        for fd in fds.values():
            _close_quietly(fd)
        raise
    return fds


def trainer_fd_paths(fds: Mapping[str, int]) -> dict[str, str]:
    return {key: f"{PROC_SELF_FD_PREFIX}{fd}" for key, fd in fds.items()}


def trainer_local_fd_paths(fds: Mapping[str, int]) -> dict[str, str]:
    """Same-process fd names. Never ``/proc/self/fd/N`` (that name is process-local)."""
    return {key: f"/dev/fd/{int(fd)}" for key, fd in fds.items()}


def _hash_held_fd(fd: int, field: str) -> str:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError as exc:
        _refuse(field, "seekable fd", f"OSError:{exc.errno}")
    digest = hashlib.sha256()
    try:
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            digest.update(block)
    except OSError as exc:
        _refuse(field, "readable fd", f"OSError:{exc.errno}")
    try:
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError as exc:
        _refuse(field, "seekable fd", f"OSError:{exc.errno}")
    return digest.hexdigest()


def rehash_held_fds(
    fds: Mapping[str, int],
    *,
    pin: Mapping[str, Any],
    manifest_shas: Mapping[str, str],
    host: str,
    refuse_on_mismatch: bool = True,
) -> dict[str, Any]:
    """Informational re-hash of the same fds handed to the trainer. Never reopens paths."""
    post: dict[str, str] = {}
    record: dict[str, Any] = {
        "status": CHECKPOINT_MATCH,
        "host": host,
        "paths": trainer_fd_paths(fds),
        "computed_shas": post,
        "pin_shas": {
            "sha256_pack": pin["sha256_pack"],
            "sha256_train": pin["sha256_train"],
            "sha256_holdout": pin["sha256_holdout"],
        },
        "manifest_shas": dict(manifest_shas),
        "checked_at": _utc_now(),
        "match": True,
        "informational": True,
    }
    try:
        for sha_field, path_key in PATH_KEY_BY_SHA.items():
            fd = fds.get(path_key)
            if fd is None:
                _refuse(sha_field, "held fd", "missing")
            actual = _hash_held_fd(int(fd), sha_field)
            post[sha_field] = actual
            if refuse_on_mismatch:
                pin_sha = pin[sha_field]
                man_sha = manifest_shas[sha_field]
                if actual != pin_sha:
                    _refuse(sha_field, pin_sha, actual)
                if actual != man_sha:
                    _refuse(sha_field, man_sha, actual)
    except KickRefused as exc:
        record["status"] = CHECKPOINT_REFUSED
        record["match"] = False
        record["field"] = exc.field
        record["expected"] = exc.expected
        record["actual"] = exc.actual
        if refuse_on_mismatch:
            raise
    record["computed_shas"] = post
    record["checked_at"] = _utc_now()
    return record


def _path_matches_trainer_fd(named: object, fd_paths: Mapping[str, str]) -> str | None:
    if named is None:
        return None
    try:
        text = os.fsdecode(named) if isinstance(named, (bytes, bytearray)) else str(named)
    except (TypeError, ValueError):
        return None
    if not text:
        return None
    try:
        real = os.path.realpath(text)
    except OSError:
        real = text
    for key, fdpath in fd_paths.items():
        if text == fdpath or real == fdpath:
            return key
        try:
            if os.path.realpath(fdpath) in (text, real):
                return key
        except OSError:
            continue
    return None


@contextmanager
def guard_trainer_fd_writes(fd_paths: Mapping[str, str], pin: Mapping[str, Any]) -> Iterator[None]:
    """Refuse a writable reopen of a sealed trainer fd, with the matching sha field."""
    real_os_open = os.open
    real_builtin_open = builtins.open
    real_io_open = io.open

    def _field_for(named: object) -> str | None:
        key = _path_matches_trainer_fd(named, fd_paths)
        if key is None:
            return None
        return SHA_FIELD_BY_PATH_KEY.get(key, key)

    def _refuse_write(named: object) -> None:
        field = _field_for(named)
        if field is None:
            return
        expected = pin.get(field) if field in pin else "sealed fd"
        _refuse(field, expected, "writable reopen after verify")

    def _os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        acc = flags & getattr(os, "O_ACCMODE", 0o3)
        if acc != os.O_RDONLY:
            _refuse_write(path)
        return real_os_open(path, flags, *args, **kwargs)

    def _file_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        mode_s = str(mode)
        if any(flag in mode_s for flag in ("w", "a", "x", "+")):
            _refuse_write(file)
        return real_io_open(file, mode, *args, **kwargs)

    os.open = _os_open  # type: ignore[method-assign]
    builtins.open = _file_open  # type: ignore[assignment]
    io.open = _file_open  # type: ignore[assignment]
    try:
        yield
    finally:
        os.open = real_os_open  # type: ignore[method-assign]
        builtins.open = real_builtin_open  # type: ignore[assignment]
        io.open = real_io_open  # type: ignore[assignment]


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"helper-ft-{stamp}-{uuid.uuid4().hex[:8]}"


def _running_script() -> Path:
    return Path(__file__).resolve()


def discover_pinned_copy_root(script: Path | None = None) -> Path | None:
    """PINS.json lives four directories above kick_helper_ft.py. No git."""
    path = Path(script) if script is not None else _running_script()
    try:
        root = path.resolve().parents[PINNED_COPY_DEPTH]
    except IndexError:
        return None
    pins = root / PINS_JSON_NAME
    if pins.is_file():
        return root
    return None


def canonical_pins_map_json(payload: Mapping[str, Any]) -> bytes:
    """sha256 of this blob is the map digest. Sorted keys, compact separators."""
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True
    ).encode("utf-8")


def _no_duplicate_pins_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse(PINS_JSON_NAME, "unique keys", f"duplicate {key}")
        seen[key] = value
    return seen


def _read_capped_file(path: Path, *, field: str, max_bytes: int) -> bytes:
    try:
        fd = os.open(path, _open_flags_read())
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    try:
        raw = b""
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            raw += block
            if len(raw) > max_bytes:
                _refuse(field, f"at most {max_bytes} bytes", len(raw))
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    return raw


def load_pinned_copy_mode(script: Path | None = None) -> dict[str, Any] | None:
    """If PINS.json is present, verify the staged copy and skip every git lookup.

    Layout (copy root = four parents of kick_helper_ft.py)::

        PINS.json
        apps/dottie-os/scripts/lab/*.py
        apps/dottie-os/trust/cam_pin_ed25519.pub
        apps/dottie-os/trust/cam_pin_key_id

    ``PINS.json`` is ``{"head": <40-hex>, "files": {<repo-rel-path>: <sha256>}}``.
    Required files are hashed at those exact relative paths. A basename-only
    pin is a missing entry.
    """
    path = Path(script) if script is not None else _running_script()
    root = discover_pinned_copy_root(path)
    if root is None:
        return None
    pins_path = root / PINS_JSON_NAME
    try:
        pins_stat = os.lstat(pins_path)
    except OSError as exc:
        _refuse(PINS_JSON_NAME, "readable regular file", f"OSError:{exc.errno}")
    if stat.S_ISLNK(pins_stat.st_mode):
        _refuse(PINS_JSON_NAME, "regular file", "symlink")
    if pins_stat.st_mode & 0o222:
        _refuse(PINS_JSON_NAME, "mode 0400", oct(pins_stat.st_mode & 0o777))
    raw = _read_capped_file(pins_path, field=PINS_JSON_NAME, max_bytes=PINS_JSON_MAX_BYTES)
    file_sha = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_pins_keys)
    except UnicodeDecodeError:
        _refuse(PINS_JSON_NAME, "utf-8 JSON", "invalid encoding")
    except ValueError:
        _refuse(PINS_JSON_NAME, "JSON object", "invalid JSON")
    if not isinstance(parsed, dict):
        _refuse(PINS_JSON_NAME, '{"head","files"}', type(parsed).__name__)
    extra = set(parsed) - {"head", "files"}
    if extra or "head" not in parsed or "files" not in parsed:
        _refuse(PINS_JSON_NAME, '{"head","files"}', sorted(parsed))
    head = _require_git_commit_hex("head", parsed["head"])
    files_raw = parsed["files"]
    if not isinstance(files_raw, dict) or not files_raw:
        _refuse(
            "files",
            "JSON object",
            type(files_raw).__name__ if not isinstance(files_raw, dict) else "empty",
        )
    files: dict[str, str] = {}
    for key, value in files_raw.items():
        rel = _require_relative_pin_path("files", key)
        files[rel] = _require_sha256_hex(f"files.{rel}", value)
    kick_live = path.resolve()
    spec_live = (kick_live.parent / "cam_pin_spec.py").resolve()
    uuid_live = (kick_live.parent / "content_uuid.py").resolve()
    kickoff_live = (kick_live.parent / "helper_ft_kickoff.py").resolve()
    expected_kick = (root / PINNED_COPY_KICK_REL).resolve()
    expected_spec = (root / PINNED_COPY_SPEC_REL).resolve()
    expected_uuid = (root / PINNED_COPY_UUID_REL).resolve()
    expected_kickoff = (root / PINNED_COPY_KICKOFF_REL).resolve()
    if kick_live != expected_kick:
        _refuse(PINNED_COPY_KICK_REL, str(expected_kick), str(kick_live))
    if spec_live != expected_spec:
        _refuse(PINNED_COPY_SPEC_REL, str(expected_spec), str(spec_live))
    if uuid_live != expected_uuid:
        _refuse(PINNED_COPY_UUID_REL, str(expected_uuid), str(uuid_live))
    if kickoff_live != expected_kickoff:
        _refuse(PINNED_COPY_KICKOFF_REL, str(expected_kickoff), str(kickoff_live))
    live_by_rel = {rel: (root / rel).resolve() for rel in PINNED_COPY_REQUIRED_RELS}
    for rel in PINNED_COPY_REQUIRED_RELS:
        if rel not in files:
            _refuse("files", f"pin covering {rel}", "missing")
        target = live_by_rel[rel]
        if not target.is_file():
            _refuse(rel, "readable regular file", "missing")
        actual = sha256_file(target)
        if files[rel] != actual:
            _refuse(f"files.{rel}", actual, files[rel])
    for rel, expected in files.items():
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            _refuse(f"files.{rel}", f"under {root}", str(target))
        if not target.is_file():
            _refuse(rel, "readable regular file", "missing")
        actual = sha256_file(target)
        if expected != actual:
            _refuse(f"files.{rel}", actual, expected)
    payload = {"files": files, "head": head}
    map_sha = hashlib.sha256(canonical_pins_map_json(payload)).hexdigest()
    trust_blobs = {rel: files[rel] for rel in PINNED_COPY_REQUIRED_RELS}
    trust_blobs["HEAD"] = head
    return {
        "root": root,
        "pins_path": pins_path,
        "head": head,
        "files": files,
        "map_sha256": map_sha,
        "file_sha256": file_sha,
        "trust_blobs": trust_blobs,
        "reason": PINNED_COPY_REASON,
    }


def _script_git_sha() -> str | None:
    if discover_pinned_copy_root() is not None:
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else None


def _script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


def _require_git_commit_hex(field: str, value: object) -> str:
    if type(value) is not str or len(value) != GIT_SHA_LEN or any(ch not in _HEX for ch in value):
        _refuse(field, "40-char lowercase hex", value)
    return value


def _require_relative_pin_path(field: str, value: object) -> str:
    if type(value) is not str or not value or value.startswith("/") or "\\" in value:
        _refuse(field, "relative POSIX path", value)
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        _refuse(field, "relative POSIX path", value)
    return value


def _script_repo_root(script: Path | None = None) -> Path:
    path = Path(script) if script is not None else _running_script()
    return path.resolve().parents[PINNED_COPY_DEPTH]


def _entrypoint_live_files() -> dict[str, Path]:
    root = _script_repo_root()
    return {rel: (root / rel).resolve() for rel in ENTRYPOINT_PIN_RELS}


def load_entrypoint_pins(*, git_sha: str | None) -> tuple[dict[str, str], str]:
    """Load runner pin map + source commit. Null git sha is allowed only here.

    ``FORGE_ENTRYPOINT_PINS`` is a JSON object mapping **exact** repo-relative
    paths to sha256 hex. Basename keys are a missing entry. Required keys
    are the pinned-copy rels (kick, cam_pin_spec, content_uuid, trust pub,
    trust key id, reserved content-uuid list). ``FORGE_PINS_SOURCE_COMMIT`` is the 40-hex commit those
    pins were hashed from and, when ``git_sha`` is present, must equal it.
    A missing ``script_git_sha`` (private verified copy) is accepted only
    when both env vars are present and well formed. Missing or malformed
    pins refuse even when ``git_sha`` is present.
    """
    if git_sha is not None and (
        type(git_sha) is not str
        or len(git_sha) != GIT_SHA_LEN
        or any(ch not in _HEX for ch in git_sha)
    ):
        _refuse("script_git_sha", "40-char lowercase hex or null", git_sha)
    pins_raw = os.environ.get(FORGE_ENTRYPOINT_PINS_ENV)
    commit_raw = os.environ.get(FORGE_PINS_SOURCE_COMMIT_ENV)
    if not pins_raw:
        _refuse("entrypoint_pins", "JSON map from FORGE_ENTRYPOINT_PINS", "missing")
    if not commit_raw:
        _refuse(
            "pins_source_commit",
            "40-char lowercase hex from FORGE_PINS_SOURCE_COMMIT",
            "missing",
        )
    commit = _require_git_commit_hex("pins_source_commit", commit_raw)
    try:
        parsed = json.loads(pins_raw)
    except ValueError:
        _refuse("entrypoint_pins", "JSON object", "invalid JSON")
    if not isinstance(parsed, dict) or not parsed:
        _refuse(
            "entrypoint_pins",
            "JSON object",
            type(parsed).__name__ if not isinstance(parsed, dict) else "empty",
        )
    pins: dict[str, str] = {}
    for key, value in parsed.items():
        rel = _require_relative_pin_path("entrypoint_pins", key)
        digest = _require_sha256_hex(f"entrypoint_pins.{rel}", value)
        pins[rel] = digest
        if Path(rel).name == rel:
            _refuse("entrypoint_pins", "exact repo-relative path", rel)
    live = _entrypoint_live_files()
    for rel in ENTRYPOINT_PIN_RELS:
        if rel not in pins:
            _refuse("entrypoint_pins", f"pin covering {rel}", "missing")
        target = live[rel]
        if not target.is_file():
            _refuse(rel, "readable regular file", "missing")
        actual = sha256_file(target)
        if pins[rel] != actual:
            _refuse(f"entrypoint_pins.{rel}", actual, pins[rel])
    if git_sha is not None and commit != git_sha:
        _refuse("pins_source_commit", git_sha, commit)
    return pins, commit


def _entrypoint_event_fields(evidence: Mapping[str, Any]) -> dict[str, Any]:
    pins = evidence.get("entrypoint_pins")
    commit = evidence.get("pins_source_commit")
    if not isinstance(pins, dict) or not pins:
        _refuse("entrypoint_pins", "recorded pin map", "missing")
    if type(commit) is not str:
        _refuse("pins_source_commit", "40-char lowercase hex", commit)
    fields: dict[str, Any] = {
        "entrypoint_pins": dict(pins),
        "pins_source_commit": commit,
    }
    if evidence.get("script_git_sha_reason") == PINNED_COPY_REASON:
        for key in (
            "head",
            "pins_map_sha256",
            "pins_file_sha256",
            "pinned_copy_root",
            "script_git_sha_reason",
        ):
            value = evidence.get(key)
            if value is None:
                _refuse(key, "pinned-copy evidence", "missing")
            fields[key] = value
        fields["script_git_sha"] = None
    return fields


def _open_flags_read() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_flags_write() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _unescape_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _parse_mountinfo() -> list[dict[str, Any]]:
    try:
        raw = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except OSError as exc:
        _refuse("run_private_root", "readable /proc/self/mountinfo", f"OSError:{exc.errno}")
    mounts: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        left_parts = left.split()
        right_parts = right.split()
        if len(left_parts) < 5 or not right_parts:
            continue
        maj_min = left_parts[2].split(":")
        if len(maj_min) != 2:
            continue
        try:
            dev = os.makedev(int(maj_min[0]), int(maj_min[1]))
        except (TypeError, ValueError, OverflowError):
            continue
        mounts.append(
            {
                "dev": dev,
                "root": _unescape_mount_field(left_parts[3]),
                "mount_point": _unescape_mount_field(left_parts[4]),
                "fstype": right_parts[0],
            }
        )
    if not mounts:
        _refuse("run_private_root", "mountinfo entries", "empty")
    return mounts


def _covering_mount(path: Path, mounts: list[dict[str, Any]]) -> dict[str, Any]:
    text = os.path.realpath(path)
    best: dict[str, Any] | None = None
    best_len = -1
    for mount in mounts:
        mp = mount["mount_point"]
        if text == mp or text.startswith(mp.rstrip("/") + "/") or mp == "/":
            if len(mp) > best_len:
                best = mount
                best_len = len(mp)
    if best is None:
        _refuse("run_private_root", "mounted path", text)
    return best


def _bind_mount_devs(mounts: list[dict[str, Any]]) -> set[int]:
    """st_dev of subtree binds (mountinfo root != '/'). Same as server PINNED_ROOT."""
    return {int(mount["dev"]) for mount in mounts if mount["root"] != "/"}


def _statfs_f_type(path: Path) -> int:
    libname = ctypes.util.find_library("c") or "libc.so.6"
    libc = ctypes.CDLL(libname, use_errno=True)
    libc.statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(_LinuxStatfs)]
    libc.statfs.restype = ctypes.c_int
    buf = _LinuxStatfs()
    rc = libc.statfs(os.fsencode(path), ctypes.byref(buf))
    if rc != 0:
        err = ctypes.get_errno()
        _refuse("run_private_root", "tmpfs statfs", f"OSError:{err}")
    return int(buf.f_type)


def _run_private_root_path() -> Path:
    raw = os.environ.get(FORGE_RUN_PRIVATE_ROOT_ENV, DEFAULT_FORGE_RUN_PRIVATE_ROOT)
    if type(raw) is not str or not raw or raw != raw.strip() or not raw.startswith("/"):
        _refuse("run_private_root", "absolute path", raw)
    return Path(raw)


def _require_run_private_root() -> Path:
    """tmpfs, euid-owned, 0700, not a bind-mount st_dev. Fail closed if missing."""
    if os.name != "posix":
        _refuse("run_private_root", "posix tmpfs", os.name)
    root = _run_private_root_path()
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        _refuse("run_private_root", DEFAULT_FORGE_RUN_PRIVATE_ROOT, "missing")
    except OSError as exc:
        _refuse("run_private_root", "readable directory", f"OSError:{exc.errno}")
    if stat.S_ISLNK(info.st_mode):
        _refuse("run_private_root", "real directory", "symlink")
    if not stat.S_ISDIR(info.st_mode):
        _refuse("run_private_root", "directory", "not a directory")
    if info.st_uid != os.geteuid():
        _refuse("run_private_root", f"uid {os.geteuid()}", info.st_uid)
    if stat.S_IMODE(info.st_mode) != 0o700:
        _refuse("run_private_root", "0700", oct(stat.S_IMODE(info.st_mode)))
    _walk_ancestors_dirfds(root)
    mounts = _parse_mountinfo()
    covering = _covering_mount(root, mounts)
    if covering["fstype"] != "tmpfs":
        _refuse("run_private_root", "tmpfs", covering["fstype"])
    if covering["root"] != "/":
        _refuse("run_private_root", "not bind-mount", covering["root"])
    f_type = _statfs_f_type(root)
    if f_type != TMPFS_MAGIC:
        _refuse("run_private_root", hex(TMPFS_MAGIC), hex(f_type))
    bind_devs = _bind_mount_devs(mounts)
    if info.st_dev in bind_devs:
        _refuse("run_private_root", "not bind-mount st_dev", info.st_dev)
    if covering["dev"] in bind_devs:
        _refuse("run_private_root", "not bind-mount st_dev", covering["dev"])
    return root


def hold_run_private_root() -> tuple[Path, int, os.stat_result]:
    """Open the private root with O_DIRECTORY|O_NOFOLLOW and keep that dir-fd."""
    root = _require_run_private_root()
    fd = _open_dir_nofollow(str(root))
    st = os.fstat(fd)
    return root, fd, st


def _require_run_private_dir(run_private: Path) -> Path:
    root, root_fd, root_st = hold_run_private_root()
    try:
        path = Path(run_private)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            _refuse("run_private_dir", "present", "missing")
        except OSError as exc:
            _refuse("run_private_dir", "readable directory", f"OSError:{exc.errno}")
        if stat.S_ISLNK(info.st_mode):
            _refuse("run_private_dir", "real directory", "symlink")
        if not stat.S_ISDIR(info.st_mode):
            _refuse("run_private_dir", "directory", "not a directory")
        if info.st_uid != os.geteuid():
            _refuse("run_private_dir", f"uid {os.geteuid()}", info.st_uid)
        if stat.S_IMODE(info.st_mode) != 0o700:
            _refuse("run_private_dir", "0700", oct(stat.S_IMODE(info.st_mode)))
        if info.st_dev != root_st.st_dev:
            _refuse("run_private_dir", root_st.st_dev, info.st_dev)
        if not _dirfd_contained_in(root, path):
            _refuse("run_private_dir", f"under {root}", os.path.realpath(path))
        _walk_ancestors_dirfds(path)
        return path
    finally:
        _close_quietly(root_fd)


def _make_run_private_dir() -> Path:
    root, root_fd, _root_st = hold_run_private_root()
    try:
        path: Path | None = None
        for _attempt in range(32):
            name = f"inputs-{uuid.uuid4().hex[:12]}"
            try:
                os.mkdir(name, 0o700, dir_fd=root_fd)
            except FileExistsError:
                continue
            except OSError as exc:
                _refuse(
                    "run_private_dir",
                    "exclusive tmp under run_private_root",
                    f"OSError:{exc.errno}",
                )
            path = root / name
            break
        if path is None:
            _refuse("run_private_dir", "exclusive tmp under run_private_root", "name collision")
        try:
            os.chmod(path, 0o700)
        except OSError as exc:
            _refuse("run_private_dir", "0700", f"OSError:{exc.errno}")
        return _require_run_private_dir(path)
    finally:
        _close_quietly(root_fd)


def _read_fd_bytes(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        block = os.read(fd, CHUNK)
        if not block:
            break
        chunks.append(block)
    return b"".join(chunks)


def _read_fd_bytes_capped(fd: int, field: str, max_bytes: int) -> bytes:
    raw = b""
    while True:
        block = os.read(fd, CHUNK)
        if not block:
            break
        raw += block
        if len(raw) > max_bytes:
            _refuse(field, f"<={max_bytes} bytes", len(raw))
    return raw


def _fstat_trainer_file(fd: int, field: str, root_dev: int) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        _refuse(field, "regular file", "non-regular")
    if info.st_nlink != 1:
        _refuse(field, "nlink==1", info.st_nlink)
    if info.st_uid != os.geteuid():
        _refuse(field, f"uid {os.geteuid()}", info.st_uid)
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        _refuse(field, "no group/other write", oct(stat.S_IMODE(info.st_mode)))
    if info.st_dev != root_dev:
        _refuse(field, root_dev, info.st_dev)
    return info


def _open_trainer_input_fd(named: str, field: str) -> int:
    if is_proc_self_fd_path(named):
        return _dup_proc_self_fd(named)
    try:
        return os.open(named, _open_flags_read())
    except OSError as exc:
        if getattr(exc, "errno", None) in (errno.ELOOP, getattr(errno, "EPERM", None)):
            _refuse(field, "regular file", "symlink")
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")


def _open_and_verify_trainer_inputs(evidence: Mapping[str, Any]) -> dict[str, bytes]:
    """O_NOFOLLOW open, fstat, hash that fd, constant-time compare to signed pin.

    Returns the bytes read from those fds. The trainer must use these bytes
    (or a sealed memfd / held fd of them) and never reopen a staging path.
    """
    pin = evidence.get("pin")
    if not isinstance(pin, Mapping):
        _refuse("pin", "present", "missing")
    paths = evidence.get("paths")
    if not isinstance(paths, Mapping):
        _refuse("paths", "present", "missing")
    root = _require_run_private_root()
    try:
        root_st = os.lstat(root)
    except OSError as exc:
        _refuse("run_private_root", "readable directory", f"OSError:{exc.errno}")
    root_dev = int(root_st.st_dev)
    verified: dict[str, bytes] = {}
    for sha_field, path_key in PATH_KEY_BY_SHA.items():
        expected = pin.get(sha_field)
        if type(expected) is not str or len(expected) != SHA256_LEN:
            _refuse(sha_field, "64-char lowercase hex", expected)
        named = paths.get(path_key)
        if type(named) is not str or not named:
            _refuse(f"paths.{path_key}", "present", "missing")
        fd = _open_trainer_input_fd(named, sha_field)
        try:
            if not is_proc_self_fd_path(named):
                _fstat_trainer_file(fd, sha_field, root_dev)
            else:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    _refuse(sha_field, "regular file", "non-regular")
            buf = _read_fd_bytes(fd)
            actual = hashlib.sha256(buf).hexdigest()
            if not hmac.compare_digest(actual, expected):
                _refuse(sha_field, expected, actual)
            verified[path_key] = buf
        except KickRefused:
            raise
        except OSError as exc:
            _refuse(sha_field, "readable regular file", f"OSError:{exc.errno}")
        finally:
            os.close(fd)
    return verified


def _verify_manifest_copy(run_private: Path, expected_sha: str) -> bytes:
    """Re-verify MANIFEST bytes at point of use against the digest taken at copy."""
    named = str((Path(run_private) / MANIFEST_FILE))
    root = _require_run_private_root()
    try:
        root_dev = int(os.lstat(root).st_dev)
    except OSError as exc:
        _refuse("run_private_root", "readable directory", f"OSError:{exc.errno}")
    fd = _open_trainer_input_fd(named, MANIFEST_FILE)
    try:
        _fstat_trainer_file(fd, MANIFEST_FILE, root_dev)
        buf = _read_fd_bytes(fd)
        actual = hashlib.sha256(buf).hexdigest()
        if not hmac.compare_digest(actual, expected_sha):
            _refuse(MANIFEST_FILE, expected_sha, actual)
        return buf
    except KickRefused:
        raise
    except OSError as exc:
        _refuse(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)


def sha256_file(path: Path, chunk: int = CHUNK) -> str:
    """Streaming SHA-256 of file bytes. Never hashes a hardcoded string."""
    digest = hashlib.sha256()
    try:
        fd = os.open(path, _open_flags_read())
    except OSError as exc:
        _refuse(path.name, "readable regular file", f"OSError:{exc.errno}")
    try:
        while True:
            block = os.read(fd, chunk)
            if not block:
                break
            digest.update(block)
    except OSError as exc:
        _refuse(path.name, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    return digest.hexdigest()


def count_rows(path: Path) -> int:
    try:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except UnicodeDecodeError:
        _refuse(path.name, "utf-8 text", "invalid encoding")
    except OSError as exc:
        _refuse(path.name, "readable text file", f"OSError:{exc.errno}")


def _require_sha256_hex(field: str, value: object) -> str:
    try:
        return cam_pin_spec.require_sha256_hex(field, value)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


def _require_int(field: str, value: object) -> int:
    try:
        return cam_pin_spec.require_int(field, value)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)
        raise AssertionError("unreachable") from exc


def _refuse_skip_env() -> None:
    for name in _FORBIDDEN_SKIP_ENV:
        value = os.environ.get(name)
        if value:
            _refuse(name, "unset", value)


def _refuse_pin_env() -> None:
    """A pin env var is a paste path. Refuse before hashing or kickoff."""
    for name in _FORBIDDEN_PIN_ENV:
        if os.environ.get(name):
            _refuse(name, "unset", "set")


def _refuse_local_pin_files(pack_root: Path) -> None:
    """A local pin file is a paste path. Refuse before hashing or kickoff."""
    for filename in _FORBIDDEN_PIN_FILES:
        path = pack_root / filename
        try:
            present = os.path.lexists(path)
        except OSError as exc:
            _refuse(filename, "absent", f"OSError:{exc.errno}")
        if present:
            _refuse(filename, "absent", "local pin file")


def _resolve_pack_dir(pack_dir: Path) -> Path:
    try:
        if pack_dir.is_symlink():
            _refuse("--pack", "real directory", "symlink")
        if not pack_dir.exists():
            _refuse("--pack", "present", "missing")
        if not pack_dir.is_dir():
            _refuse("--pack", "directory", "not a directory")
        return Path(os.path.realpath(pack_dir))
    except OSError as exc:
        _refuse("--pack", "readable directory", f"OSError:{exc.errno}")


def _contained_in(root: Path, path: Path) -> bool:
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    try:
        Path(path_real).relative_to(root_real)
    except ValueError:
        return False
    return True


def _regular_file_in_pack(pack_root: Path, filename: str) -> Path:
    """Refuse nested names, symlinks, non-regular files, and escapes."""
    if Path(filename).name != filename or not filename or filename in (".", ".."):
        _refuse(filename, "basename inside pack dir", filename)
    raw = pack_root / filename
    try:
        info = os.lstat(raw)
    except FileNotFoundError:
        _refuse(filename, "present", "missing")
    except OSError as exc:
        _refuse(filename, "readable regular file", f"OSError:{exc.errno}")
    if stat.S_ISLNK(info.st_mode):
        _refuse(filename, "regular file", "symlink")
    if not stat.S_ISREG(info.st_mode):
        _refuse(filename, "regular file", "non-regular")
    if not _contained_in(pack_root, raw):
        _refuse(filename, f"inside {os.path.realpath(pack_root)}", os.path.realpath(raw))
    return raw


def _read_file_buffer(src: Path, field: str) -> bytes:
    """Read the whole regular file through one held fd. No path reopen."""
    try:
        fd = os.open(src, _open_flags_read())
    except OSError as exc:
        if getattr(exc, "errno", None) in (errno.ELOOP, getattr(errno, "EPERM", None)):
            _refuse(field, "regular file", "symlink")
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _refuse(field, "regular file", "non-regular")
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
        raise AssertionError("unreachable")
    finally:
        os.close(fd)


def _write_buffer_exclusive(dest: Path, buf: bytes, field: str) -> None:
    """Write ``buf`` through O_CREAT|O_EXCL, fsync, fchmod 0400. Same bytes hashed."""
    dest = Path(dest)
    dir_fd = _COPY_DIR_FD
    if dir_fd is not None:
        _write_buffer_exclusive_at(dir_fd, dest.name, buf, field)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_fd = os.open(dest, _open_flags_write(), 0o600)
    except OSError as exc:
        _refuse(field, "exclusive writable copy", f"OSError:{exc.errno}")
    try:
        _write_all(out_fd, buf, field)
        if hasattr(os, "fsync"):
            os.fsync(out_fd)
        if os.name == "posix" and hasattr(os, "fchmod"):
            os.fchmod(out_fd, 0o400)
        else:
            os.chmod(dest, 0o400)
        written = os.fstat(out_fd)
        try:
            named = os.lstat(dest)
        except OSError as exc:
            _refuse(field, "same inode", f"OSError:{exc.errno}")
        if (written.st_dev, written.st_ino) != (named.st_dev, named.st_ino):
            _refuse(field, "same inode", "path swapped")
    except OSError as exc:
        _refuse(field, "writable copy", f"OSError:{exc.errno}")
    finally:
        os.close(out_fd)


def _write_buffer_exclusive_at(dir_fd: int, name: str, buf: bytes, field: str) -> None:
    """openat(dir_fd, name, O_CREAT|O_EXCL) so a swapped parent cannot redirect the copy."""
    if Path(name).name != name or name in (".", "..") or not name:
        _refuse(field, "basename", name)
    try:
        out_fd = os.open(name, _open_flags_write(), 0o600, dir_fd=dir_fd)
    except OSError as exc:
        _refuse(field, "exclusive writable copy", f"OSError:{exc.errno}")
    try:
        _write_all(out_fd, buf, field)
        if hasattr(os, "fsync"):
            os.fsync(out_fd)
        if os.name == "posix" and hasattr(os, "fchmod"):
            os.fchmod(out_fd, 0o400)
        written = os.fstat(out_fd)
        try:
            named = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as exc:
            _refuse(field, "same inode", f"OSError:{exc.errno}")
        if (written.st_dev, written.st_ino) != (named.st_dev, named.st_ino):
            _refuse(field, "same inode", "path swapped")
    except OSError as exc:
        _refuse(field, "writable copy", f"OSError:{exc.errno}")
    finally:
        os.close(out_fd)


def _copy_and_hash(src: Path, dest: Path, field: str) -> str:
    """Read into a buffer, hash that buffer, write the same buffer to a private copy.

    The trainer must read only the private copy. Hashing a stream while writing
    and then reopening a shared path leaves a TOCTOU window (B-RACE).
    Writes go through the held root dir-fd when one is installed.
    """
    buf = _read_file_buffer(src, field)
    digest = hashlib.sha256(buf).hexdigest()
    _write_buffer_exclusive(dest, buf, field)
    return digest


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse(MANIFEST_FILE, "unique keys", f"duplicate {key}")
        seen[key] = value
    return seen


def _no_duplicate_hq_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse("cam-pin", "unique keys", f"duplicate {key}")
        seen[key] = value
    return seen


def _read_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest_path = _regular_file_in_pack(pack_dir, MANIFEST_FILE)
    try:
        fd = os.open(manifest_path, _open_flags_read())
    except OSError as exc:
        _refuse(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
    except OSError as exc:
        _refuse(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _refuse(MANIFEST_FILE, "utf-8 text", "invalid encoding")
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except KickRefused:
        raise
    except ValueError as exc:
        _refuse(MANIFEST_FILE, "valid JSON object", f"invalid JSON ({exc})")
    if not isinstance(payload, dict):
        _refuse(MANIFEST_FILE, "valid JSON object", type(payload).__name__)
    return payload


def _require_cam_pin(record: object, pack_id: str, *, run_id: str | None = None) -> dict[str, Any]:
    """Bind the verified Cam-signed v2 pin to this pack_id and run_id."""
    if not isinstance(record, dict) or not record:
        _refuse("cam-pin", "present", "missing")
    try:
        parsed = cam_pin_spec.parse_kick_pin_payload(record, run_id=run_id)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)
    pin_pack = parsed.get("pack_id")
    if type(pin_pack) is not str or not pin_pack:
        _refuse("cam-pin.pack_id", "present", "missing")
    if pin_pack != pack_id:
        _refuse("cam-pin.pack_id", pack_id, pin_pack)
    if run_id is not None and parsed.get("run_id") != run_id:
        _refuse("cam-pin.binding.run_id", parsed.get("run_id"), run_id)
    pin: dict[str, Any] = {
        "format": cam_pin_spec.PIN_FORMAT_V2,
        "pack_id": pack_id,
        "run_id": parsed["run_id"],
        "lease_owner": parsed["lease_owner"],
        "source": PIN_SOURCE,
        "key_id": parsed.get("key_id"),
        "binding": dict(parsed["binding"]),
        "issued_at": parsed.get("issued_at"),
        "not_before": parsed.get("not_before"),
        "not_after": parsed.get("not_after"),
        "nonce": parsed.get("nonce"),
        "code_pins": dict(parsed["code_pins"]),
        "git_commit": parsed.get("git_commit"),
        "head": parsed.get("head"),
        "expires_at": parsed.get("expires_at"),
        "reserved_content_uuids_sha256": parsed.get("reserved_content_uuids_sha256"),
        "reserved_content_uuids_min_rows": parsed.get("reserved_content_uuids_min_rows"),
        "sha256_manifest": parsed.get("sha256_manifest"),
        "near_dup_tokenizer_version": parsed.get("near_dup_tokenizer_version"),
        "near_dup_tokenizer_sha256": parsed.get("near_dup_tokenizer_sha256"),
        "rows_total": parsed.get("rows_total"),
        "rows_train": parsed.get("rows_train"),
        "rows_holdout": parsed.get("rows_holdout"),
        "recordedAt": parsed.get("recordedAt"),
        "kid": parsed.get("kid"),
        "cam_key_id": parsed.get("cam_key_id"),
        "cam_sig": parsed.get("cam_sig"),
    }
    if "recordedBy" in parsed:
        pin["recordedBy"] = parsed["recordedBy"]
    if "stampVerified" in parsed:
        pin["stampVerified"] = parsed["stampVerified"]
    if "pack_matches" in parsed:
        pin["pack_matches"] = parsed["pack_matches"]
    for sha_field, _filename, _manifest_rows, pin_rows in ARTIFACTS:
        pin[sha_field] = _require_sha256_hex(f"cam-pin.{sha_field}", parsed.get(sha_field))
        pin[pin_rows] = _require_int(f"cam-pin.{pin_rows}", parsed.get(pin_rows))
    return pin


def _parse_hq_pin_payload(payload: object) -> dict[str, Any]:
    try:
        return cam_pin_spec.parse_hq_pin_payload(payload)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


def _pin_ref_is_held_fd(pin_ref: object) -> bool:
    if type(pin_ref) is int:
        return True
    return type(pin_ref) is str and is_proc_self_fd_path(pin_ref)


def _read_staged_v2_pin_bytes(pin_ref: object) -> bytes:
    """Read the staged v2 pin once. Never fetch. Caller parses and re-uses these bytes."""
    if pin_ref is None or pin_ref == "":
        _refuse("cam-pin", "staged v2 pin fd or path under run_private_root", "missing")
    raw: bytes
    if _pin_ref_is_held_fd(pin_ref):
        named = str(pin_ref) if type(pin_ref) is not int else f"{PROC_SELF_FD_PREFIX}{pin_ref}"
        fd = int(pin_ref) if type(pin_ref) is int else _dup_proc_self_fd(named)
        close_fd = type(pin_ref) is not int
        try:
            raw = _read_fd_bytes_capped(fd, "cam-pin", cam_pin_spec.MAX_PIN_BYTES)
        except OSError as exc:
            _refuse("cam-pin", "readable staged pin fd", f"OSError:{exc.errno}")
        finally:
            if close_fd:
                _close_quietly(fd)
    else:
        path = Path(str(pin_ref))
        root = _require_run_private_root()
        try:
            resolved = Path(os.path.realpath(path))
            resolved.relative_to(Path(os.path.realpath(root)))
        except (OSError, ValueError):
            _refuse("cam-pin.path", f"under {root}", str(pin_ref))
        fd = _open_trainer_input_fd(str(resolved), "cam-pin")
        try:
            root_dev = int(os.lstat(root).st_dev)
            _fstat_trainer_file(fd, "cam-pin", root_dev)
            raw = _read_fd_bytes_capped(fd, "cam-pin", cam_pin_spec.MAX_PIN_BYTES)
        except KickRefused:
            raise
        except OSError as exc:
            _refuse("cam-pin", "readable staged pin", f"OSError:{exc.errno}")
        finally:
            os.close(fd)
    return raw


def load_staged_v2_pin(pin_ref: object, *, run_id: str | None = None) -> dict[str, Any]:
    """Verify the staged v2 pin (held fd or path under the private root). Never fetch."""
    raw = _read_staged_v2_pin_bytes(pin_ref)
    parsed, _payload = _parse_staged_v2_pin_bytes(raw, run_id=run_id)
    return parsed


def _parse_staged_v2_pin_bytes(
    raw: bytes, *, run_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("cam-pin", "utf-8 JSON", "invalid encoding")
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_hq_keys)
    except KickRefused:
        raise
    except ValueError:
        _refuse("cam-pin", "JSON object", "invalid JSON")
    if not isinstance(payload, dict):
        _refuse("cam-pin", "JSON object", type(payload).__name__)
    try:
        parsed = cam_pin_spec.parse_kick_pin_payload(payload, run_id=run_id)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)
    return parsed, payload


def _stage_verified_pin_bytes(run_private: Path, pin_bytes: bytes) -> None:
    """Write the already-verified pin into run_private/cam-pin-v2.json. No body pin_path."""
    if type(pin_bytes) is not bytes or not pin_bytes:
        _refuse("cam-pin", "staged v2 pin bytes", "missing")
    if len(pin_bytes) > cam_pin_spec.MAX_PIN_BYTES:
        _refuse("cam-pin", f"<={cam_pin_spec.MAX_PIN_BYTES} bytes", len(pin_bytes))
    dest = Path(run_private) / STAGED_PIN_NAME
    _write_buffer_exclusive(dest, pin_bytes, "cam-pin")


def _line_identities(path: Path, field: str) -> tuple[list[str], list[str]]:
    hashes: list[str] = []
    ids: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                hashes.append(hashlib.sha256(line.encode("utf-8")).hexdigest())
                try:
                    obj = json.loads(line)
                except ValueError:
                    _refuse(field, "jsonl row", "invalid JSON")
                if isinstance(obj, dict):
                    tid = obj.get("trajectory_id", obj.get("id"))
                    if isinstance(tid, str) and tid:
                        ids.append(tid)
    except UnicodeDecodeError:
        _refuse(field, "utf-8 text", "invalid encoding")
    except OSError as exc:
        _refuse(field, "readable text file", f"OSError:{exc.errno}")
    return hashes, ids


def _split_soundness(run_private: Path, computed_shas: Mapping[str, str]) -> None:
    if computed_shas["sha256_train"] == computed_shas["sha256_holdout"]:
        _refuse("split", "train and holdout distinct", "identical")
    pack_h, pack_ids = _line_identities(run_private / PACK_FILE, PACK_FILE)
    train_h, train_ids = _line_identities(run_private / TRAIN_FILE, TRAIN_FILE)
    hold_h, hold_ids = _line_identities(run_private / HOLDOUT_FILE, HOLDOUT_FILE)
    leaked_hash = set(train_h) & set(hold_h)
    if leaked_hash:
        _refuse("split", "holdout disjoint from train", f"row-hash leak n={len(leaked_hash)}")
    leaked_id = set(train_ids) & set(hold_ids)
    if leaked_id:
        sample = ",".join(sorted(leaked_id)[:3])
        _refuse("split", "holdout disjoint from train", f"trajectory_id leak {sample}")
    if Counter(pack_h) != Counter(train_h) + Counter(hold_h):
        _refuse("split", "pack == train ∪ holdout", "row-set mismatch")
    train_rows = _load_jsonl_rows(str(run_private / TRAIN_FILE))
    hold_rows = _load_jsonl_rows(str(run_private / HOLDOUT_FILE))
    train_keys: dict[str, set[str]] = {"record_id": set(), "trajectory_id": set()}
    hold_keys: dict[str, set[str]] = {"record_id": set(), "trajectory_id": set()}
    for row in train_rows:
        item = _group_key_split_value(row)
        if item is not None:
            train_keys[item[0]].add(item[1])
    for row in hold_rows:
        item = _group_key_split_value(row)
        if item is not None:
            hold_keys[item[0]].add(item[1])
    leaked_rid = train_keys["record_id"] & hold_keys["record_id"]
    if leaked_rid:
        sample = ",".join(sorted(leaked_rid)[:3])
        _refuse("split", "holdout disjoint from train", f"record_id leak {sample}")
    leaked_tid = train_keys["trajectory_id"] & hold_keys["trajectory_id"]
    if leaked_tid:
        sample = ",".join(sorted(leaked_tid)[:3])
        _refuse("split", "holdout disjoint from train", f"trajectory_id leak {sample}")


def trainer_input_paths(run_private: Path) -> dict[str, str]:
    """Resolved absolute run-dir copy paths (staging only). Trainer argv uses held fds."""
    root = Path(run_private).resolve()
    return {key: str((root / name).resolve()) for key, name in TRAINER_PATH_FILES.items()}


def build_trainer_argv(paths: Mapping[str, str]) -> list[str]:
    return [
        "--pack",
        paths["pack"],
        "--train",
        paths["train"],
        "--holdout",
        paths["holdout"],
        "--manifest",
        paths["manifest"],
    ]


def is_smoke_mode(body: Mapping[str, Any] | None, *, smoke: bool = False) -> bool:
    if smoke:
        return True
    if not isinstance(body, Mapping):
        return False
    if body.get("smoke") is True:
        return True
    return body.get("mode") == "helper-ft-smoke"


def _is_not_for_train_value(value: object) -> bool:
    return value is True or value == 1 or value == "true"


def _iter_jsonl_objects(path: Path, field: str):
    try:
        buf = path.read_bytes()
    except OSError as exc:
        _refuse(field, "readable text file", f"OSError:{exc.errno}")
    try:
        text = content_uuid.decode_json_bytes(buf)
    except content_uuid.ContentUuidError as exc:
        _refuse(exc.field, exc.expected, f"{field}: {exc}")
    except RecursionError:
        _refuse("content_uuid.too_deep", f"depth <= {content_uuid.MAX_DEPTH}", f"{field}: RecursionError")
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = content_uuid.strict_json_loads(line)
        except content_uuid.ContentUuidError as exc:
            _refuse(exc.field, exc.expected, f"{field}: {exc}")
        except RecursionError:
            _refuse(
                "content_uuid.too_deep",
                f"depth <= {content_uuid.MAX_DEPTH}",
                f"{field}: RecursionError",
            )
        except ValueError:
            _refuse(field, "jsonl row", "invalid JSON")
        if isinstance(obj, dict):
            yield obj


def _row_id(obj: Mapping[str, Any]) -> str:
    for key in ("id", "trajectory_id"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return "?"


def collect_not_for_train(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
) -> list[str]:
    hits: list[str] = []
    if _is_not_for_train_value(manifest.get("not_for_train")):
        hits.append("MANIFEST.not_for_train")
    for key in ("pack", "train", "holdout"):
        raw = recorded_paths.get(key)
        if type(raw) is not str or not raw:
            continue
        path = Path(raw)
        field = path.name
        for obj in _iter_jsonl_objects(path, field):
            if _is_not_for_train_value(obj.get("not_for_train")):
                hits.append(f"{field}:{_row_id(obj)}.not_for_train")
    return hits


def normalize_leak_key(key: object) -> str:
    """NFKC, strip format/combining marks, casefold, drop spaces and `_-.`."""
    text = unicodedata.normalize("NFKC", str(key))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _LEAK_FORMAT_CATS)
    return re.sub(r"[\s_\-.]+", "", text.casefold())


def _is_message_key(key: object) -> bool:
    return normalize_leak_key(key) == "message"


def _is_user_role(role: object) -> bool:
    return isinstance(role, str) and normalize_leak_key(role) == "user"


def _is_chat_message(value: Mapping[str, Any]) -> bool:
    role = value.get("role")
    if not isinstance(role, str) or not role.strip():
        return False
    return "content" in value or "tool_calls" in value or "parts" in value


def _is_leak_synthetic_path(path: str) -> bool:
    """Presence, key-count, id-residue, and pairwise features are categorical."""
    return (
        path == "__key_count__"
        or path.endswith(LEAK_KEY_COUNT_SUFFIX)
        or path.endswith(LEAK_PRESENT_SUFFIX)
        or path.endswith(LEAK_ID_RESIDUE_SUFFIX)
        or "|" in path
        or "^" in path
    )


def _leak_entropy(counts: Mapping[object, int], n: int) -> float:
    if n <= 0:
        return 0.0
    total = 0.0
    for count in counts.values():
        if count:
            p = count / n
            total -= p * math.log2(p)
    return total


def _theil_u(values: list[object], golds: list[object]) -> float:
    """Uncertainty coefficient U(gold|field) = MI(field; gold) / H(gold)."""
    n = len(values)
    if n == 0:
        return 0.0
    h_gold = _leak_entropy(Counter(golds), n)
    if h_gold == 0.0:
        return 0.0
    by_value: dict[object, list[object]] = defaultdict(list)
    for value, gold in zip(values, golds):
        by_value[value].append(gold)
    h_cond = 0.0
    for group in by_value.values():
        h_cond += (len(group) / n) * _leak_entropy(Counter(group), len(group))
    return (h_gold - h_cond) / h_gold


def _conditional_accuracy(
    values: list[object],
    golds: list[object],
    *,
    min_support: int = LEAK_MIN_SUPPORT,
) -> tuple[float, int, float]:
    """Per-value majority classifier on values with support >= min_support.

    Returns (accuracy, n_supported, majority_baseline_on_supported).
    """
    by_value: dict[object, list[object]] = defaultdict(list)
    for value, gold in zip(values, golds):
        by_value[value].append(gold)
    correct = 0
    supported: list[object] = []
    for group in by_value.values():
        if len(group) < min_support:
            continue
        supported.extend(group)
        predicted = Counter(group).most_common(1)[0][0]
        correct += sum(1 for gold in group if gold == predicted)
    if not supported:
        return 0.0, 0, 0.0
    baseline = Counter(supported).most_common(1)[0][1] / len(supported)
    return correct / len(supported), len(supported), baseline


_ID_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _strip_unique_affix(values: list[str]) -> list[str] | None:
    min_len = min((len(value) for value in values), default=0)
    if min_len < 2:
        return None
    n = len(values)
    for strip in range(1, min_len):
        prefixes = [value[:-strip] for value in values]
        n_unique = len(set(prefixes))
        if 1 < n_unique < n:
            return prefixes
    for strip in range(1, min_len):
        suffixes = [value[strip:] for value in values]
        n_unique = len(set(suffixes))
        if 1 < n_unique < n:
            return suffixes
    return None


def _unique_id_residues(col: list[object]) -> list[object] | None:
    """Strip unique prefix/suffix tokens from a unique-per-row string column."""
    if any(not isinstance(value, str) for value in col):
        return None
    texts = [str(value) for value in col]
    if len(set(texts)) < len(texts):
        return None
    tokenized = [_ID_SPLIT_RE.split(text) for text in texts]
    counts: Counter[str] = Counter()
    for tokens in tokenized:
        for token in tokens:
            if token:
                counts[token.casefold()] += 1
    residues: list[object] = []
    for tokens in tokenized:
        kept = [token.casefold() for token in tokens if token and counts[token.casefold()] > 1]
        residues.append("|".join(kept) if kept else LEAK_ABSENT)
    if len(set(residues)) <= 1 or len(set(residues)) >= len(residues):
        stripped = _strip_unique_affix(texts)
        if stripped is None:
            return None
        residues = list(stripped)
    if len(set(residues)) <= 1 or len(set(residues)) >= len(residues):
        return None
    return residues


def _binary_bits(col: list[object]) -> list[int] | None:
    unique = sorted({value for value in col}, key=lambda item: str(item))
    if len(unique) != 2:
        return None
    mapping = {unique[0]: 0, unique[1]: 1}
    return [mapping[value] for value in col]


def _score_choice_column(
    path: str,
    col: list[object],
    choices: list[str | None],
    found: list[str],
    seen: set[str],
) -> bool:
    choice_pairs = [
        (value, gold) for value, gold in zip(col, choices) if gold is not None
    ]
    if not choice_pairs:
        return False
    values, golds = [pair[0] for pair in choice_pairs], [pair[1] for pair in choice_pairs]
    if not _field_predicts_gold(values, golds):
        return False
    if path not in seen:
        seen.add(path)
        found.append(path)
    return len(found) >= 10


def _add_id_residue_columns(columns: dict[str, list[object | None]]) -> None:
    for path, col in list(columns.items()):
        if _is_leak_synthetic_path(path):
            continue
        residues = _unique_id_residues(list(col))
        if residues is not None:
            columns[path + LEAK_ID_RESIDUE_SUFFIX] = residues


def _add_pairwise_columns(
    columns: dict[str, list[object | None]],
    choices: list[str | None],
) -> None:
    binary_paths: list[str] = []
    for path, col in columns.items():
        if _is_leak_synthetic_path(path):
            continue
        supported = [value for value, gold in zip(col, choices) if gold is not None]
        if len(set(supported)) == 2:
            binary_paths.append(path)
    binary_paths.sort()
    added = 0
    for idx, left in enumerate(binary_paths):
        left_bits = _binary_bits(list(columns[left]))
        if left_bits is None:
            continue
        for right in binary_paths[idx + 1 :]:
            if added >= LEAK_PAIR_MAX_PAIRS:
                return
            right_bits = _binary_bits(list(columns[right]))
            if right_bits is None:
                continue
            concat = [f"{a}\x1f{b}" for a, b in zip(columns[left], columns[right])]
            xor_col: list[object | None] = [
                f"__xor__:{a ^ b}" for a, b in zip(left_bits, right_bits)
            ]
            columns[f"{left}|{right}"] = concat
            columns[f"{left}^{right}"] = xor_col
            added += 1


def _field_predicts_gold(values: list[object], golds: list[object]) -> bool:
    """True when repeated field values predict gold above the majority baseline.

    Thresholds (not per-fixture):
    - Skip constants (1 distinct value) and unique-per-row fields (cardinality
      == n). Those can be ids or a non-predictive flag; unique values can
      memorize any labeling.
    - MIN_SUPPORT=2: a value must appear at least twice before it counts as a
      repeated predictor. Small-n packs therefore fail closed only when a
      repeated value is a pure (or near-pure) gold slice.
    - Fail-closed: conditional accuracy >= LEAK_NEAR_PERFECT_ACC on the
      supported rows (perfect / near-perfect copies, including n=3 A,A,B).
    - Partial leaks: Theil's U(gold|field) >= 0.50 (field explains at least
      half of gold entropy) AND accuracy is at least 20pp above the
      majority-class baseline. That catches a field that matches gold on
      most but not all rows without flagging mixed ``status: execute``
      cycling or ordinary lang/tool constants.
    """
    n = len(values)
    if n < LEAK_MIN_SUPPORT:
        return False
    if len(set(golds)) <= 1:
        # A constant gold cannot be leaked; any co-occurring field would
        # look like a perfect predictor.
        return False
    n_unique = len(set(values))
    if n_unique <= 1 or n_unique >= n:
        return False
    accuracy, supported, baseline = _conditional_accuracy(values, golds)
    if supported < LEAK_MIN_SUPPORT:
        return False
    if accuracy >= LEAK_NEAR_PERFECT_ACC:
        return True
    u_score = _theil_u(values, golds)
    return u_score >= LEAK_U_THRESHOLD and accuracy >= baseline + LEAK_LIFT_MARGIN


def _row_gold_choice(row: Mapping[str, Any]) -> str | None:
    labels = row.get("labels")
    if not isinstance(labels, Mapping):
        return None
    action = labels.get("action")
    if isinstance(action, Mapping):
        choice = action.get("choice")
        if type(choice) is str and choice:
            return choice
    domain = labels.get("domain")
    if isinstance(domain, Mapping):
        choice = domain.get("choice")
        if type(choice) is str and choice:
            return choice
    return None


def _row_gold_noul(row: Mapping[str, Any]) -> float | None:
    labels = row.get("labels")
    if not isinstance(labels, Mapping):
        return None
    safe = labels.get("safe")
    if not isinstance(safe, Mapping):
        return None
    noul = safe.get("noul")
    if isinstance(noul, (int, float)) and type(noul) is not bool:
        return round(float(noul), 6)
    return None


def _canonical_leak_value(value: object) -> object:
    if type(value) is bool:
        return LEAK_BOOL_TRUE if value else LEAK_BOOL_FALSE
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if value is None:
        return LEAK_NULL
    return str(value)


def _json_blobs(text: str) -> list[object]:
    blobs: list[object] = []
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if ch in "{[":
            try:
                obj, end = decoder.raw_decode(text, idx)
            except ValueError:
                idx += 1
                continue
            blobs.append(obj)
            idx = end
            continue
        idx += 1
    return blobs


def _maybe_b64_text(text: str) -> str | None:
    blob = text.strip()
    if len(blob) < LEAK_B64_MIN_LEN or len(blob) % 4:
        return None
    if not _LEAK_B64_RE.fullmatch(blob):
        return None
    try:
        raw = base64.b64decode(blob, validate=True)
        decoded = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not decoded or decoded == text or len(decoded) > LEAK_B64_MAX_DECODED:
        return None
    return decoded


def _walk_leak_value(
    value: object,
    path: str,
    into: dict[str, object],
    *,
    from_message: bool,
) -> None:
    if isinstance(value, Mapping):
        if _is_chat_message(value):
            is_user = _is_user_role(value.get("role"))
            for key, child in value.items():
                if normalize_leak_key(key) == "role":
                    continue
                child_path = f"{path}.{key}" if path else str(key)
                _walk_leak_value(
                    child,
                    child_path,
                    into,
                    from_message=from_message and is_user,
                )
            return
        if not from_message:
            count_path = f"{path}{LEAK_KEY_COUNT_SUFFIX}" if path else "__key_count__"
            into[count_path] = len(value)
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            child_is_message = from_message or _is_message_key(key)
            _walk_leak_value(child, child_path, into, from_message=child_is_message)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            _walk_leak_value(child, f"{path}[{idx}]", into, from_message=from_message)
        return
    if isinstance(value, str):
        for idx, blob in enumerate(_json_blobs(value)):
            _walk_leak_value(
                blob, f"{path}.<json{idx}>", into, from_message=False
            )
        decoded = _maybe_b64_text(value)
        if decoded is not None:
            _walk_leak_value(decoded, f"{path}.<b64>", into, from_message=False)
        if not from_message:
            into[path] = _canonical_leak_value(value)
        return
    if from_message:
        return
    into[path] = _canonical_leak_value(value)


def _fields_from_row(row: Mapping[str, Any]) -> dict[str, object]:
    into: dict[str, object] = {}
    state = row.get("state")
    if isinstance(state, Mapping):
        into["state" + LEAK_KEY_COUNT_SUFFIX] = len(state)
        for key, child in state.items():
            if _is_message_key(key):
                _walk_leak_value(
                    child, f"state.{key}", into, from_message=True
                )
            else:
                _walk_leak_value(
                    child, f"state.{key}", into, from_message=False
                )
    scored_keys = [
        key for key in row if key != "state" and str(key) not in _LEAK_BOOKKEEPING_KEYS
    ]
    into["__key_count__"] = len(scored_keys) + (1 if isinstance(state, Mapping) else 0)
    for key in scored_keys:
        _walk_leak_value(
            row[key], str(key), into, from_message=_is_message_key(key)
        )
    return into


def _unique_pack_rows(recorded_paths: Mapping[str, str]) -> list[dict[str, Any]]:
    """Dedup by id. Prefer the pack file so train∪holdout is not double-counted."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("pack", "train", "holdout"):
        raw = recorded_paths.get(key)
        if type(raw) is not str or not raw:
            continue
        path = Path(raw)
        chunk: list[dict[str, Any]] = []
        for obj in _iter_jsonl_objects(path, path.name):
            rid = _row_id(obj)
            if rid != "?" and rid in seen:
                continue
            seen.add(rid)
            chunk.append(obj)
        if key == "pack" and chunk:
            return chunk
        rows.extend(chunk)
    return rows


def _sidecar_jsonl_paths(pack_dir: Path | str | None) -> list[Path]:
    if pack_dir is None:
        return []
    root = Path(pack_dir)
    if not root.is_dir():
        return []
    found: list[Path] = []
    try:
        for child in root.iterdir():
            if not child.is_file() or child.suffix != ".jsonl":
                continue
            if child.name in _LEAK_PACK_JSONL:
                continue
            found.append(child)
    except OSError:
        return []
    return found


def _fields_from_sidecar(path: Path) -> dict[str, dict[str, object]]:
    """Map row id -> {sidecar.<key>: value} from a companion jsonl."""
    by_id: dict[str, dict[str, object]] = {}
    for obj in _iter_jsonl_objects(path, path.name):
        rid = obj.get("id") or obj.get("trajectory_id")
        if not isinstance(rid, str) or not rid:
            continue
        slot = by_id.setdefault(rid, {})
        for key, child in obj.items():
            if key in ("id", "trajectory_id"):
                continue
            _walk_leak_value(child, f"sidecar.{key}", slot, from_message=_is_message_key(key))
    return by_id


def _load_jsonl_rows(raw: object) -> list[dict[str, Any]]:
    if type(raw) is not str or not raw:
        return []
    if is_proc_self_fd_path(raw):
        fd = _dup_proc_self_fd(raw)
        try:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                buf = _read_fd_bytes(fd)
                os.lseek(fd, 0, os.SEEK_SET)
            except OSError as exc:
                _refuse("paths", "seekable fd", f"OSError:{exc.errno}")
        finally:
            _close_quietly(fd)
        try:
            text = content_uuid.decode_json_bytes(buf)
        except content_uuid.ContentUuidError as exc:
            _refuse(exc.field, exc.expected, f"{raw}: {exc}")
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = content_uuid.strict_json_loads(line)
            except content_uuid.ContentUuidError as exc:
                _refuse(exc.field, exc.expected, f"{raw}: {exc}")
            if isinstance(obj, dict):
                rows.append(obj)
        return rows
    path = Path(raw)
    if not path.is_file():
        return []
    return list(_iter_jsonl_objects(path, path.name))


def _leak_hits_for_rows(
    rows: list[dict[str, Any]],
    sidecar_by_id: Mapping[str, Mapping[str, object]],
) -> list[str]:
    if not rows:
        return []
    columns: dict[str, list[object | None]] = defaultdict(lambda: [None] * len(rows))
    choices: list[str | None] = []
    nouls: list[float | None] = []
    for idx, row in enumerate(rows):
        choices.append(_row_gold_choice(row))
        nouls.append(_row_gold_noul(row))
        for path, token in _fields_from_row(row).items():
            columns[path][idx] = token
        extra = sidecar_by_id.get(_row_id(row))
        if extra:
            for path, token in extra.items():
                columns[path][idx] = token

    for col in columns.values():
        for idx, token in enumerate(col):
            if token is None:
                col[idx] = LEAK_ABSENT
    for path, col in list(columns.items()):
        if path.endswith(LEAK_PRESENT_SUFFIX) or path.endswith(LEAK_KEY_COUNT_SUFFIX):
            continue
        columns[path + LEAK_PRESENT_SUFFIX] = [
            LEAK_BOOL_FALSE if token == LEAK_ABSENT else LEAK_BOOL_TRUE for token in col
        ]
    _add_id_residue_columns(columns)
    _add_pairwise_columns(columns, choices)

    found: list[str] = []
    seen: set[str] = set()
    for path, col in columns.items():
        synthetic = _is_leak_synthetic_path(path)
        if _score_choice_column(path, list(col), choices, found, seen):
            return found
        if synthetic:
            continue
        noul_pairs = [
            (value, gold)
            for value, gold in zip(col, nouls)
            if isinstance(value, (int, float))
            and type(value) is not bool
            and gold is not None
        ]
        if noul_pairs:
            values, golds = [pair[0] for pair in noul_pairs], [pair[1] for pair in noul_pairs]
            if _field_predicts_gold(values, golds):
                if path not in seen:
                    seen.add(path)
                    found.append(path)
                    if len(found) >= 10:
                        return found
    return found


def collect_state_leaks(
    recorded_paths: Mapping[str, str],
    pack_dir: Path | str | None = None,
) -> list[str]:
    """Pack-level gold-label leak detector.

    A non-``message`` field leaks when its *repeated* values predict the row
    gold — ``labels.action.choice`` (L3) or ``labels.domain.choice`` (L2),
    and independently ``labels.safe.noul`` for numeric fields — across the
    pack. Key names are not a refuse rule: ``risk_hint`` with a constant
    placeholder must pass; a brand-new key whose values track gold must
    refuse. JSON objects inside strings (including a JSON tail on
    ``message``), base64-encoded labels, top-level extra keys, nested
    state, and ``*.jsonl`` sidecars in ``pack_dir`` are unwrapped and
    scored the same way. JSON ``null`` is the ``__null__`` category;
    a field missing from a row is ``__absent__`` (distinct from null).
    Every column also yields a ``.__present__`` feature, and every
    mapping yields a ``.__key_count__`` feature, so presence-only and
    key-count leaks are scored, not dropped. Train, holdout, and the
    pooled pack are scored separately; a leak on any slice refuses.

    Measure. Let U = Theil's uncertainty coefficient
    ``MI(field; gold) / H(gold)``. Conditional accuracy is the empirical
    per-value majority classifier, restricted to values with support
    ``LEAK_MIN_SUPPORT`` (2). Majority baseline is the most common gold
    among those supported rows.

    Thresholds (statistical defaults, not per-fixture tunings):
    - Constants (1 distinct value) and unique-per-row fields (cardinality
      == n) always pass. Unique fields can memorize any labeling; constants
      cannot separate classes.
    - A constant gold (one class among the rows that have the field) always
      passes: any co-occurring field would look perfect otherwise.
    - Fail closed at small n: accuracy >= ``LEAK_NEAR_PERFECT_ACC`` (0.999)
      on supported rows refuses even a 3-row A,A,B copy. A 2-row A,B copy
      is unique-per-row and passes.
    - Partial leaks: U >= ``LEAK_U_THRESHOLD`` (0.50) and accuracy at least
      ``LEAK_LIFT_MARGIN`` (0.20) above the majority baseline. Half of gold
      entropy plus 20pp lift is "matches on most rows" without flagging a
      mixed ``status`` cycle (~chance) or ordinary ``meta.tool`` / ``lang``.
    """
    sidecar_by_id: dict[str, dict[str, object]] = {}
    for sidecar in _sidecar_jsonl_paths(pack_dir):
        for rid, fields in _fields_from_sidecar(sidecar).items():
            sidecar_by_id.setdefault(rid, {}).update(fields)

    slices: list[tuple[str, list[dict[str, Any]]]] = [
        ("", _unique_pack_rows(recorded_paths)),
        ("train:", _load_jsonl_rows(recorded_paths.get("train"))),
        ("holdout:", _load_jsonl_rows(recorded_paths.get("holdout"))),
    ]
    found: list[str] = []
    seen: set[str] = set()
    for prefix, rows in slices:
        for path in _leak_hits_for_rows(rows, sidecar_by_id):
            item = f"{prefix}{path}" if prefix else path
            if item not in seen:
                seen.add(item)
                found.append(item)
                if len(found) >= 10:
                    return found
    return found


def _training_rows(recorded_paths: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = _load_jsonl_rows(recorded_paths.get("train"))
    if rows:
        return rows
    return _unique_pack_rows(recorded_paths)


def _content_uuid_collision_field(message: str) -> str:
    if message.startswith("label conflict:"):
        return "content_uuid.label_conflict"
    if message.startswith("cross-split leak:"):
        return "content_uuid.cross_split_leak"
    if message.startswith("cross-split duplicate:"):
        return "content_uuid.cross_split_duplicate"
    if message.startswith("duplicate:"):
        return "content_uuid.duplicate"
    return "content_uuid.duplicate"


def collect_content_uuid_collisions(recorded_paths: Mapping[str, str]) -> list[str]:
    """Refuse label conflicts, within-split duplicates, and cross-split duplicates."""
    train = _load_jsonl_rows(recorded_paths.get("train"))
    holdout = _load_jsonl_rows(recorded_paths.get("holdout"))
    if not train and not holdout:
        train = _unique_pack_rows(recorded_paths)
        holdout = []
    conflicts, duplicates, cross = content_uuid.find_content_uuid_collisions(
        train, holdout
    )
    return [*conflicts, *cross, *duplicates]


def collect_forged_content_uuids(recorded_paths: Mapping[str, str]) -> list[str]:
    hits: list[str] = []
    for row in _training_rows(recorded_paths):
        try:
            content_uuid.verify_content_uuid(row)
        except content_uuid.ContentUuidError as exc:
            hits.append(str(exc))
            if len(hits) >= 10:
                return hits
    return hits


def reserved_content_uuids_path() -> Path:
    """Gate-owned reserved list. Never argv or env."""
    if cam_pin_spec.PINNED_COPY_ROOT is not None:
        return Path(cam_pin_spec.PINNED_COPY_ROOT) / RESERVED_CONTENT_UUIDS_REL
    return Path(__file__).resolve().parents[2] / "trust" / RESERVED_CONTENT_UUIDS_NAME


def reserved_near_dup_fingerprints_path() -> Path:
    if cam_pin_spec.PINNED_COPY_ROOT is not None:
        return Path(cam_pin_spec.PINNED_COPY_ROOT) / RESERVED_NEAR_DUP_FPS_REL
    return Path(__file__).resolve().parents[2] / "trust" / RESERVED_NEAR_DUP_FPS_NAME


def _line_is_placeholder(text: str) -> bool:
    upper = text.upper()
    return any(marker in text or marker in upper for marker in _PLACEHOLDER_MARKERS)


def _fp_line_is_placeholder(stripped: str) -> bool:
    """Exact-line placeholder match. A substring in live JSON is not a placeholder."""
    return stripped in _FP_PLACEHOLDER_LINES


def _hmac_key_id_is_placeholder(key_id: str) -> bool:
    return (
        not key_id
        or "PLACEHOLDER" in key_id.upper()
        or key_id == RESERVED_NEAR_DUP_HMAC_KEY_ID
        and "PLACEHOLDER" in RESERVED_NEAR_DUP_HMAC_KEY_ID
    )


def reset_hmac_key_state() -> None:
    """Tests only: drop the kick-scoped HMAC key."""
    global _HMAC_KEY_BYTES, _HMAC_KEY_ID_LOADED
    _HMAC_KEY_BYTES = None
    _HMAC_KEY_ID_LOADED = None


def _hmac_digest_hex(key: bytes, shingle: str) -> str:
    return hmac.new(key, shingle.encode("utf-8"), hashlib.sha256).hexdigest()


def _looks_like_plaintext_shingle(value: object) -> bool:
    return type(value) is str and len(value) == 5 and any(ch not in _HEX for ch in value)


def _looks_like_unkeyed_digest(value: object) -> bool:
    return type(value) is str and len(value) == SHA256_LEN and all(ch in _HEX for ch in value)


def _fingerprint_length_field(obj: Mapping[str, Any]) -> str | None:
    """S-NCHAR-LEAK: public fingerprint objects must not carry nchar/L or a length field."""
    for key, value in obj.items():
        if type(key) is not str:
            continue
        folded = key.casefold()
        compact = folded.replace("_", "").replace("-", "")
        if folded in _FP_LENGTH_KEY_FOLDED or compact in _FP_LENGTH_KEY_FOLDED:
            return key
        if key in {"L", "l"}:
            return key
        if compact in {"ntokens", "size", "b"} and type(value) is int:
            return key
    return None


def _require_keyed_hasher() -> Callable[[str], str]:
    """Same keyed HMAC-SHA256 hasher for candidates and references. Never logs the key."""
    key = _HMAC_KEY_BYTES
    if key is None:
        _refuse("reserved_near_dup_hmac.hasher", "loaded keyed hasher", "missing")
    material = key

    def hasher(shingle: str) -> str:
        if type(shingle) is not str:
            _refuse("reserved_near_dup_hmac.hasher", "str shingle", type(shingle).__name__)
        return hmac.new(material, shingle.encode("utf-8"), hashlib.sha256).hexdigest()

    return hasher


def load_reserved_near_dup_hmac_key(path: object, expected_key_id: object) -> bytes:
    """Read the HMAC key at kick time. Never logs key bytes; never from the request body."""
    global _HMAC_KEY_BYTES, _HMAC_KEY_ID_LOADED
    if type(expected_key_id) is not str or not expected_key_id:
        _refuse("reserved_near_dup_hmac.key_id", "committed key id", "missing")
    if _hmac_key_id_is_placeholder(expected_key_id):
        _refuse("reserved_near_dup_hmac.key_id", "committed key id", "placeholder")
    if path is None or path is _UNSET or (type(path) is not str and not isinstance(path, Path)):
        _refuse("reserved_near_dup_hmac.key", "regular file", "missing")
    named = Path(str(path))
    flags = _open_flags_read()
    try:
        fd = os.open(named, flags)
    except OSError as exc:
        _refuse("reserved_near_dup_hmac.key", "readable regular file", f"OSError:{exc.errno}")
        raise AssertionError("unreachable") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _refuse("reserved_near_dup_hmac.key", "regular file", "non-regular")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o400:
            _refuse("reserved_near_dup_hmac.key", "0400", oct(stat.S_IMODE(info.st_mode)))
        if os.name == "posix" and int(info.st_uid) != int(os.getuid()):
            _refuse("reserved_near_dup_hmac.key", "owned by gate uid", "uid mismatch")
        buf = _read_fd_bytes(fd)
    except KickRefused:
        raise
    except OSError as exc:
        _refuse("reserved_near_dup_hmac.key", "readable regular file", f"OSError:{exc.errno}")
        raise AssertionError("unreachable") from exc
    finally:
        os.close(fd)
    if not buf:
        _refuse("reserved_near_dup_hmac.key", "key material", "empty")
    nl = buf.find(b"\n")
    if nl <= 0:
        _refuse("reserved_near_dup_hmac.key_id", "key_id line", "missing")
    try:
        file_key_id = buf[:nl].decode("ascii").strip()
    except UnicodeDecodeError:
        _refuse("reserved_near_dup_hmac.key_id", "ascii key_id", "invalid encoding")
        raise AssertionError("unreachable")
    if file_key_id != expected_key_id:
        _refuse("reserved_near_dup_hmac.key_id", "committed key id", "mismatch")
    material = buf[nl + 1 :]
    if material.endswith(b"\n"):
        material = material[:-1]
    if not material:
        _refuse("reserved_near_dup_hmac.key", "key material", "empty")
    _HMAC_KEY_BYTES = material
    _HMAC_KEY_ID_LOADED = file_key_id
    return material


def load_reserved_near_dup_fingerprints(
    path: object,
    expected_sha256: object,
) -> dict[str, tuple[str, frozenset[str]]]:
    """Load sha-pinned HMAC-SHA256 N fingerprints. Plaintext shingles and unkeyed digests refuse."""
    if path is None or path is _UNSET or (type(path) is str and not path):
        return {}
    pin = _require_sha256_hex("reserved_near_dup_fingerprints.sha256", expected_sha256)
    buf = _read_file_buffer(Path(str(path)), "reserved_near_dup_fingerprints")
    actual = hashlib.sha256(buf).hexdigest()
    if actual != pin:
        _refuse("reserved_near_dup_fingerprints.sha256", pin, actual)
    try:
        text = buf.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("reserved_near_dup_fingerprints", "utf-8 text", "invalid encoding")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if lines and all(_fp_line_is_placeholder(ln) for ln in lines):
        return {}
    load_reserved_near_dup_hmac_key(
        RESERVED_NEAR_DUP_HMAC_KEY_PATH,
        RESERVED_NEAR_DUP_HMAC_KEY_ID,
    )
    found: dict[str, tuple[str, frozenset[str]]] = {}
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _fp_line_is_placeholder(stripped):
            _refuse(
                "reserved_near_dup_fingerprints",
                "live fingerprints",
                f"placeholder at line {idx}",
            )
        try:
            obj = content_uuid.strict_json_loads(stripped)
        except content_uuid.ContentUuidError as exc:
            _refuse(exc.field, exc.expected, f"reserved_near_dup_fingerprints[{idx}]: {exc}")
        if not isinstance(obj, dict):
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}]",
                "JSON object",
                type(obj).__name__,
            )
        if row_fields.extract_paths_ready():
            leak = _fingerprint_length_field(obj)
            if leak is not None:
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].{leak}",
                    "absent length field",
                    leak,
                )
        digest = obj.get("content_uuid") or obj.get("sha256")
        rid = obj.get("id") if type(obj.get("id")) is str else "n"
        if type(digest) is not str or len(digest) != SHA256_LEN:
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].content_uuid",
                "64-hex",
                "invalid",
            )
        raw_tokens = obj.get("tokens")
        if raw_tokens is not None:
            if not isinstance(raw_tokens, list):
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].tokens",
                    "HMAC-SHA256 digests",
                    type(raw_tokens).__name__,
                )
            if not raw_tokens:
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].tokens",
                    "non-empty HMAC-SHA256 digests",
                    "empty",
                )
            if any(_looks_like_plaintext_shingle(tok) for tok in raw_tokens):
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].tokens",
                    "HMAC-SHA256 digests",
                    "plaintext shingles",
                )
            if any(_looks_like_unkeyed_digest(tok) for tok in raw_tokens):
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].tokens",
                    "HMAC-SHA256 digests",
                    "unkeyed digest",
                )
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].tokens",
                "HMAC-SHA256 digests",
                "plaintext or unkeyed",
            )
        hmac_list = obj.get("hmac_sha256")
        if not isinstance(hmac_list, list) or not hmac_list:
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].hmac_sha256",
                "non-empty list of HMAC-SHA256 hex",
                "missing" if hmac_list is None else type(hmac_list).__name__ if not isinstance(hmac_list, list) else "empty",
            )
        for tok in hmac_list:
            if type(tok) is not str or len(tok) != SHA256_LEN or any(ch not in _HEX for ch in tok):
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].hmac_sha256",
                    "64-hex HMAC-SHA256",
                    "invalid",
                )
            if _looks_like_plaintext_shingle(tok):
                _refuse(
                    f"reserved_near_dup_fingerprints[{idx}].hmac_sha256",
                    "HMAC-SHA256 digests",
                    "plaintext shingles",
                )
        file_kid = obj.get("key_id")
        if type(file_kid) is not str or not file_kid:
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].key_id",
                "committed key id",
                "missing",
            )
        if file_kid != RESERVED_NEAR_DUP_HMAC_KEY_ID:
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].key_id",
                "committed key id",
                "mismatch",
            )
        tok_ver = obj.get("tokenizer_version")
        if tok_ver is None:
            tok_ver = obj.get("near_dup_tokenizer_version")
        try:
            content_uuid.require_near_dup_tokenizer_version(
                tok_ver if tok_ver is not None else content_uuid.NEAR_DUP_TOKENIZER_VERSION
            )
        except content_uuid.ContentUuidError as exc:
            _refuse(exc.field, exc.expected, exc.actual)
        if tok_ver not in (None, content_uuid.NEAR_DUP_TOKENIZER_VERSION):
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].tokenizer_version",
                content_uuid.NEAR_DUP_TOKENIZER_VERSION,
                tok_ver,
            )
        shingles = frozenset(hmac_list)
        if row_fields.extract_paths_ready() and len(shingles) < MIN_REF_SHINGLES:
            _refuse(
                f"reserved_near_dup_fingerprints[{idx}].hmac_sha256",
                f"|B|>={MIN_REF_SHINGLES}",
                "short",
            )
        found[digest] = (rid, shingles)
    return found


def _fingerprint_tokens_are_hmac(tokens: frozenset[str]) -> bool:
    if not tokens:
        return False
    return all(
        type(tok) is str and len(tok) == SHA256_LEN and all(ch in _HEX for ch in tok)
        for tok in tokens
    )


def _candidate_tokens_for_fingerprint(
    cand_tokens: frozenset[str],
    n_tokens: frozenset[str],
) -> frozenset[str]:
    """HMAC candidate shingles when N fingerprints are keyed HMAC digests."""
    keyed = _fingerprint_tokens_are_hmac(n_tokens) or row_fields.mill_v2x_ready()
    if not keyed:
        return cand_tokens
    hasher = _require_keyed_hasher()
    return frozenset(hasher(tok) for tok in cand_tokens)


class _FingerprintRef:
    """Minimal mill reference: hashed token set only. No nchar/L."""

    __slots__ = ("tokens",)

    def __init__(self, tokens: frozenset[str]) -> None:
        self.tokens = tokens


def _collect_v2x_near_dup(
    row: Mapping[str, Any],
    rid: str,
    reserved: set[str],
) -> list[tuple[str, str]]:
    """v2.x near_dup/match: NO_TEXT refuse, keyed hasher both sides, never pass on error."""
    mill = row_fields._pinned_mill()
    no_text_err = row_fields.no_text_error_types()
    hits: list[tuple[str, str]] = []
    try:
        hasher = _require_keyed_hasher()
    except KickRefused as exc:
        return [(exc.field, f"{rid}:hasher missing")]
    try:
        row_toks = mill.row_tokens(row) if callable(getattr(mill, "row_tokens", None)) else None
        if mill.is_no_text(row_toks):
            return [("reserved_eval_partition.near_dup_no_text", f"{rid}:NO_TEXT")]
        for reserved_sha in reserved:
            indexed = content_uuid.lookup_near_dup_fingerprint(reserved_sha)
            if indexed is None:
                if content_uuid.kick_near_dup_fingerprints_loaded():
                    hits.append(
                        (
                            "reserved_eval_partition.near_dup_fingerprint_missing",
                            f"{rid}:no fingerprint for {reserved_sha}",
                        )
                    )
                    break
                continue
            n_id, n_tokens = indexed
            if not isinstance(n_tokens, frozenset) or not n_tokens:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup_empty_tokens",
                        f"{rid}:empty fingerprint for {n_id}",
                    )
                )
                continue
            ref = _FingerprintRef(n_tokens)
            try:
                mill.near_dup(row, ref, hasher=hasher)
                matched = mill.match(row, ref, hasher=hasher)
            except no_text_err:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup_no_text",
                        f"{rid}:NO_TEXT",
                    )
                )
                return hits
            except Exception:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup",
                        f"{rid}:tokenizer refused",
                    )
                )
                return hits
            is_dup = False
            if type(matched) is bool:
                is_dup = matched
            elif isinstance(matched, Mapping):
                is_dup = bool(matched.get("near_dup"))
            if is_dup:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup",
                        f"{rid}:near_dup of {n_id}",
                    )
                )
                break
    except no_text_err:
        return [("reserved_eval_partition.near_dup_no_text", f"{rid}:NO_TEXT")]
    except KickRefused as exc:
        return [(exc.field, f"{rid}:hasher missing")]
    except Exception:
        return [("reserved_eval_partition.near_dup", f"{rid}:tokenizer refused")]
    return hits


def load_reserved_content_uuids(path: object, expected_sha256: object) -> set[str]:
    """Load the pinned reserved content-uuid list. Placeholder/synthetic lists refuse."""
    if path is None or path is _UNSET or (type(path) is str and not path):
        _refuse("reserved_content_uuids", "path", "missing")
    pin = _require_sha256_hex("reserved_content_uuids.sha256", expected_sha256)
    buf = _read_file_buffer(Path(str(path)), "reserved_content_uuids")
    actual = hashlib.sha256(buf).hexdigest()
    if actual != pin:
        _refuse("reserved_content_uuids.sha256", pin, actual)
    try:
        text = buf.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("reserved_content_uuids", "utf-8 text", "invalid encoding")
    if _line_is_placeholder(text):
        _refuse("reserved_content_uuids", "live 64-hex content_uuid rows", "placeholder")
    shas: set[str] = set()
    hex_only: set[str] = set()
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _line_is_placeholder(stripped):
            _refuse(
                "reserved_content_uuids",
                "live 64-hex content_uuid rows",
                f"placeholder at line {idx}",
            )
        if stripped.startswith("{"):
            _refuse(
                "reserved_content_uuids",
                "64-hex content_uuid rows",
                f"json object at line {idx}",
            )
        digest = _require_sha256_hex(f"reserved_content_uuids[{idx}]", stripped)
        shas.add(digest)
        hex_only.add(digest)
    if not shas:
        _refuse("reserved_content_uuids", "non-empty list", "empty")
    min_rows = RESERVED_CONTENT_UUIDS_MIN_ROWS
    if len(shas) < min_rows:
        _refuse("reserved_content_uuids.min_rows", min_rows, len(shas))
    sidecar = load_reserved_near_dup_fingerprints(
        reserved_near_dup_fingerprints_path(),
        RESERVED_NEAR_DUP_FPS_SHA256,
    )
    fps = dict(sidecar)
    missing = [digest for digest in hex_only if digest not in fps]
    if missing:
        _refuse(
            "reserved_eval_partition.fingerprint_missing",
            "sha-pinned fingerprint per reserved sha",
            missing[0],
        )
    content_uuid.install_kick_near_dup_fingerprints(fps)
    return shas


def _reserved_partition_cfg(
    manifest: Mapping[str, Any],
    pinned_content_shas: set[str],
) -> dict[str, Any]:
    """Gate-owned partition. MANIFEST may add residues/shas, never remove or override n."""
    modulus = RESERVED_EVAL_PARTITION["n"]
    residues = set(RESERVED_EVAL_PARTITION["residues"])
    content_shas = set(pinned_content_shas)
    extra = manifest.get("reserved_eval_partition")
    if extra is None:
        return {"n": modulus, "residues": residues, "content_shas": content_shas}
    if not isinstance(extra, Mapping):
        _refuse("reserved_eval_partition", "object", type(extra).__name__)
    if "n" in extra or "modulus" in extra:
        claimed_n = extra["n"] if "n" in extra else extra.get("modulus")
        if claimed_n != modulus:
            _refuse("reserved_eval_partition.n", modulus, claimed_n)
    raw_residues = extra.get("residues")
    if raw_residues is None:
        raw_residues = []
    if not isinstance(raw_residues, list):
        _refuse("reserved_eval_partition.residues", "list of int", type(raw_residues).__name__)
    for idx, value in enumerate(raw_residues):
        if type(value) is not int or isinstance(value, bool) or value < 0 or value >= modulus:
            _refuse(
                f"reserved_eval_partition.residues[{idx}]",
                f"int in [0, {modulus})",
                value,
            )
        residues.add(value)
    raw_shas = extra.get("content_shas", extra.get("reserved_content_shas", []))
    if raw_shas is None:
        raw_shas = []
    if not isinstance(raw_shas, list):
        _refuse("reserved_eval_partition.content_shas", "list of sha256 hex", type(raw_shas).__name__)
    for idx, value in enumerate(raw_shas):
        content_shas.add(_require_sha256_hex(f"reserved_eval_partition.content_shas[{idx}]", value))
    return {"n": modulus, "residues": residues, "content_shas": content_shas}


def _source_str_field(row: Mapping[str, Any], key: str) -> str | None:
    source = row.get("source")
    if not isinstance(source, Mapping) or key not in source:
        return None
    value = source.get(key)
    if type(value) is not str:
        return None
    return value


def _uuidless_allowlist_spec(
    row: Mapping[str, Any],
    allowlist: Mapping[tuple[str, ...], Mapping[str, object]] | None = None,
) -> Mapping[str, object] | None:
    """Return the per-entry shape spec when hf+config(+revision) match.

    ``source.hf`` alone is not enough. Keys are ``(hf, config)`` or
    ``(hf, config, revision)``. A 3-tuple requires an exact ``source.revision``.
    """
    entries = UUIDLESS_SOURCE_ALLOWLIST if allowlist is None else allowlist
    hf = _source_str_field(row, "hf")
    config = _source_str_field(row, "config")
    if hf is None or config is None:
        return None
    revision = _source_str_field(row, "revision")
    if revision is not None:
        keyed = entries.get((hf, config, revision))
        if keyed is not None:
            return keyed
    return entries.get((hf, config))


def _uuidless_source_allowed(
    row: Mapping[str, Any],
    allowlist: Mapping[tuple[str, ...], Mapping[str, object]] | None = None,
) -> bool:
    return _uuidless_allowlist_spec(row, allowlist) is not None


def _unhandled_subset(subset: str) -> NoReturn:
    raise AssertionError(f"unhandled pack subset {subset!r}")


def _row_subset(row: Mapping[str, Any]) -> str | tuple[str, str]:
    """Closed Math/Agent/Code allowlist. Missing, unknown, or case-variant → refuse.

    The ``subset`` field itself must be present and exact. hf is never a
    substitute for a missing subset.
    """
    if not isinstance(row, Mapping) or "subset" not in row:
        return ("row.subset", "missing")
    raw = row.get("subset")
    if type(raw) is not str:
        return ("row.subset", f"not str ({type(raw).__name__})")
    if not raw:
        return ("row.subset", "missing")
    if raw in PACK_SUBSETS:
        hf = _source_str_field(row, "hf")
        mapped = _HF_TO_SUBSET.get(hf) if hf is not None else None
        if mapped is not None and mapped != raw:
            return ("row.subset", f"{raw} does not match source.hf")
        return raw
    folded = raw.casefold()
    for name in PACK_SUBSETS:
        if name.casefold() == folded:
            return ("row.subset", f"case-variant {raw!r}")
    return ("row.subset", f"unknown {raw!r}")


def _nonempty_str(value: object) -> bool:
    return _canonical_group_key(value) is not None


def _fold_group_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _canonical_group_key(value: object) -> str | None:
    """NFKC, strip, casefold. Refuse whitespace-only, padded, NBSP, and case variants."""
    if type(value) is not str:
        return None
    nfkc = unicodedata.normalize("NFKC", value)
    stripped = nfkc.strip()
    if not stripped:
        return None
    if nfkc != value or stripped != nfkc:
        return None
    folded = stripped.casefold()
    if folded != stripped:
        return None
    return folded


def _group_key_mismatch(row: Mapping[str, Any]) -> tuple[str, str] | None:
    """Exactly one group key per row, chosen by subset. No 'only when present'."""
    resolved = _row_subset(row)
    if isinstance(resolved, tuple):
        return resolved
    subset = resolved
    source = row.get("source") if isinstance(row.get("source"), Mapping) else {}
    has_source_rid = isinstance(source, Mapping) and "record_id" in source
    has_top_rid = "record_id" in row
    has_tid_key = "trajectory_id" in row
    has_tid_alias = "trajectoryid" in row
    source_rid_ok = _nonempty_str(source.get("record_id")) if has_source_rid else False
    tid_ok = _nonempty_str(row.get("trajectory_id")) if has_tid_key else False
    if subset == "Math":
        if has_tid_key or has_tid_alias:
            return ("row.group_key", "Math row must not have trajectory_id")
        if has_top_rid:
            return ("row.group_key", "Math row requires source.record_id, not top-level record_id")
        if not source_rid_ok:
            return ("row.group_key", "Math row requires non-empty source.record_id")
        return None
    if subset == "Agent" or subset == "Code":
        if has_source_rid or has_top_rid:
            return ("row.group_key", f"{subset} row must not have record_id")
        if has_tid_alias:
            return ("row.group_key", f"{subset} row requires trajectory_id, not trajectoryid")
        if not tid_ok:
            return ("row.group_key", f"{subset} row requires non-empty trajectory_id")
        return None
    _unhandled_subset(subset)


def _group_key_split_value(row: Mapping[str, Any]) -> tuple[str, str] | None:
    resolved = _row_subset(row)
    if not isinstance(resolved, str):
        return None
    if resolved == "Math":
        source = row.get("source")
        if isinstance(source, Mapping):
            record_id = source.get("record_id")
            if type(record_id) is str and record_id:
                return ("record_id", _fold_group_key(record_id))
        return None
    if resolved == "Agent" or resolved == "Code":
        trajectory_id = row.get("trajectory_id")
        if type(trajectory_id) is str and trajectory_id:
            return ("trajectory_id", _fold_group_key(trajectory_id))
        return None
    _unhandled_subset(resolved)


def _forbidden_key_name(
    key: object,
    forbidden: frozenset[str],
    *,
    ban_trajectory: bool = True,
) -> bool:
    stem = normalize_leak_key(_fold_confusables(str(key)))
    if stem in forbidden:
        return True
    if ban_trajectory and "trajectory" in stem:
        return True
    if "toolcall" in stem or "tooluse" in stem or "functioncall" in stem:
        return True
    if stem == "step" or stem.startswith("step"):
        return True
    return False


def _mapping_keys(value: object) -> set[object] | None:
    if not isinstance(value, Mapping):
        return None
    return set(value)


def _shape_strip_marks(text: str) -> str:
    kept: list[str] = []
    for ch in text:
        if ch in _SHAPE_BLANK_CHARS:
            kept.append(" ")
            continue
        cat = unicodedata.category(ch)
        if cat in _SHAPE_STRIP_CATS:
            continue
        if cat == "Cc" and ch not in _SHAPE_KEEP_CC:
            continue
        kept.append(ch)
    return "".join(kept)


def _fold_confusables(text: str) -> str:
    return text.translate(_CYRILLIC_LATIN)


def _decode_shape_escapes(text: str) -> str:
    def _unescape_unicode(match: re.Match[str]) -> str:
        hex_digits = match.group(1) or match.group(2)
        return chr(int(hex_digits, 16))

    def _unescape_hex(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    text = _UNICODE_ESCAPE_RE.sub(_unescape_unicode, text)
    text = _HEX_ESCAPE_RE.sub(_unescape_hex, text)
    text = _PERCENT_ESCAPE_RE.sub(_unescape_hex, text)
    text = html.unescape(text)
    return text


def _shape_normalize_keep_lines(text: str) -> str:
    """NFKC, fold confusables, decode escapes, strip ZWSP/soft hyphen. Keep line breaks."""
    text = unicodedata.normalize("NFKC", text)
    text = _fold_confusables(text)
    text = _decode_shape_escapes(text)
    text = _shape_strip_marks(unicodedata.normalize("NFKC", text))
    return text.casefold()


def _shape_split_lines(text: str) -> list[str]:
    lines: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch in _SHAPE_LINE_TERMINATORS:
            lines.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    lines.append("".join(buf))
    return lines


def _shape_line_prompt_hit(line: str) -> bool:
    """True when a line starts with ``$ `` plus any token that is not closed LaTeX."""
    stripped = line.lstrip(" \t")
    if not stripped.startswith("$"):
        return False
    rest = stripped[1:]
    if not rest or rest[0] not in " \t":
        return False
    body = rest.lstrip(" \t")
    if not body:
        return False
    if "$" in body:
        return False
    token = body.split(None, 1)[0]
    if not token:
        return False
    return True


def _shape_scan_text(text: str) -> str:
    """Normalized collapsed text for key/pattern contains-checks (not line-start)."""
    text = _shape_normalize_keep_lines(text)
    collapsed = "".join(" " if ch in _SHAPE_LINE_TERMINATORS else ch for ch in text)
    return re.sub(r"\s+", " ", collapsed).strip()


def _shape_prompt_hit(text: str) -> bool:
    """Normalize first, then line-start ``$ `` + command word on every terminator."""
    normalized = _shape_normalize_keep_lines(text)
    return any(_shape_line_prompt_hit(line) for line in _shape_split_lines(normalized))


def _labels_value_mismatch(
    labels: Mapping[str, Any], spec: Mapping[str, object]
) -> str | None:
    labels_types = spec.get("labels_types")
    if not isinstance(labels_types, Mapping):
        return None
    score_range = spec.get("labels_score_range", (0.0, 1.0))
    lo, hi = 0.0, 1.0
    if isinstance(score_range, tuple) and len(score_range) == 2:
        lo, hi = float(score_range[0]), float(score_range[1])
    for name, expected_type in labels_types.items():
        child = labels.get(name)
        if not isinstance(child, Mapping):
            return f"labels.{name} not object"
        if child.get("type") != expected_type:
            return f"labels.{name}.type mismatch"
        if expected_type == "score":
            score = child.get("score")
            if type(score) not in (int, float) or isinstance(score, bool):
                return f"labels.{name}.score type"
            if not (lo <= float(score) <= hi):
                return f"labels.{name}.score range"
            continue
        if expected_type == "noul":
            noul = child.get("noul")
            if type(noul) is bool:
                continue
            if type(noul) in (int, float) and not isinstance(noul, bool):
                if not (0.0 <= float(noul) <= 1.0):
                    return f"labels.{name}.noul range"
                continue
            return f"labels.{name}.noul type"
    return None


def _consent_value_mismatch(
    row: Mapping[str, Any], spec: Mapping[str, object]
) -> str | None:
    if spec.get("consent_required") and "consent" not in row:
        return "missing consent"
    if "consent" not in row:
        return None
    consent = row.get("consent")
    if not isinstance(consent, Mapping):
        return "consent not object"
    if "champion" in spec.get("consent_keys", frozenset()) or "champion" in consent:
        if consent.get("champion") is not False:
            return "consent.champion must be false"
    for key in ("capture_training", "public_hf"):
        if key in consent and type(consent.get(key)) is not bool:
            return f"consent.{key} not bool"
    return None


def _uuidless_shape_mismatch(
    row: Mapping[str, Any], spec: Mapping[str, object]
) -> str | None:
    """Return a reason if the row is not this dataset's allowlisted shape."""
    top_keys = spec["top_keys"]
    extra_top = [key for key in row if key not in top_keys]
    if extra_top:
        return f"extra top key {extra_top[0]!r}"
    for required in ("source", "state", "questions", "labels"):
        if required not in row:
            return f"missing {required}"
    schema = spec.get("schema")
    if schema is not None and row.get("schema") != schema:
        return "schema mismatch"
    tier = spec.get("tier")
    if tier is not None and row.get("tier") != tier:
        return "tier mismatch"
    source_keys = _mapping_keys(row.get("source"))
    if source_keys is None:
        return "source not object"
    allowed_source = spec["source_keys"]
    extra_source = [key for key in source_keys if key not in allowed_source]
    if extra_source:
        return f"extra source key {extra_source[0]!r}"
    source_obj = row.get("source")
    if not isinstance(source_obj, Mapping):
        return "source not object"
    if "record_id" not in source_obj:
        return "source.record_id missing"
    record_id = source_obj.get("record_id")
    if type(record_id) is not str or not record_id:
        return "source.record_id not non-empty str"
    state_keys = _mapping_keys(row.get("state"))
    if state_keys is None:
        return "state not object"
    if state_keys != spec["state_keys"]:
        return "state keys mismatch"
    questions_keys = _mapping_keys(row.get("questions"))
    if questions_keys is None:
        return "questions not object"
    if questions_keys != spec["questions_keys"]:
        return "questions keys mismatch"
    labels_keys = _mapping_keys(row.get("labels"))
    if labels_keys is None:
        return "labels not object"
    if labels_keys != spec["labels_keys"]:
        return "labels keys mismatch"
    consent_mismatch = _consent_value_mismatch(row, spec)
    if consent_mismatch:
        return consent_mismatch
    if "consent" in row:
        consent_keys = _mapping_keys(row.get("consent"))
        if consent_keys is None:
            return "consent not object"
        if consent_keys != spec["consent_keys"]:
            return "consent keys mismatch"
    state = row["state"]
    if type(state.get("message")) is not str:
        return "state.message not str"
    meta = state.get("meta")
    meta_keys = _mapping_keys(meta)
    if meta_keys is None:
        return "state.meta not object"
    if meta_keys != spec["state_meta_keys"]:
        return "state.meta keys mismatch"
    if meta.get("kind") != spec["state_meta_kind"]:
        return "state.meta.kind mismatch"
    questions_fields = spec["questions_fields"]
    questions_types = spec["questions_types"]
    questions = row["questions"]
    if not isinstance(questions_fields, Mapping) or not isinstance(questions_types, Mapping):
        return "questions spec invalid"
    for name, allowed in questions_fields.items():
        child = questions.get(name)
        child_keys = _mapping_keys(child)
        if child_keys is None:
            return f"questions.{name} not object"
        if child_keys != allowed:
            return f"questions.{name} keys mismatch"
        expected_type = questions_types.get(name)
        if expected_type is not None and child.get("type") != expected_type:
            return f"questions.{name}.type mismatch"
        if isinstance(child, Mapping) and "criteria" in child:
            criteria = child.get("criteria")
            if type(criteria) is str:
                pass
            elif isinstance(criteria, list):
                if not all(type(item) is str for item in criteria):
                    return f"questions.{name}.criteria type"
            else:
                return f"questions.{name}.criteria type"
    labels_fields = spec["labels_fields"]
    labels = row["labels"]
    if not isinstance(labels_fields, Mapping):
        return "labels spec invalid"
    for name, allowed in labels_fields.items():
        child = labels.get(name)
        child_keys = _mapping_keys(child)
        if child_keys is None:
            return f"labels.{name} not object"
        if child_keys != allowed:
            return f"labels.{name} keys mismatch"
    labels_mismatch = _labels_value_mismatch(labels, spec)
    if labels_mismatch:
        return labels_mismatch
    forbidden = spec["forbidden_keys"]
    if not isinstance(forbidden, frozenset):
        return "forbidden_keys spec invalid"
    patterns = spec["forbidden_string_patterns"]
    string_res = tuple(
        re.compile(pattern, re.I) if type(pattern) is str else pattern
        for pattern in patterns
    )
    stack: list[object] = [row]
    while stack:
        cur = stack.pop()
        if isinstance(cur, Mapping):
            for key, child in cur.items():
                if _forbidden_key_name(key, forbidden):
                    return f"forbidden key {key!r}"
                if type(key) is str:
                    scanned_key = _shape_scan_text(key)
                    if _shape_prompt_hit(key):
                        return "forbidden string marker"
                    for regex in string_res:
                        if regex.search(key) or regex.search(scanned_key):
                            return "forbidden string marker"
                stack.append(child)
            continue
        if isinstance(cur, list):
            stack.extend(cur)
            continue
        if type(cur) is str:
            if _shape_prompt_hit(cur):
                return "forbidden string marker"
            scanned = _shape_scan_text(cur)
            for regex in string_res:
                if regex.search(cur) or regex.search(scanned):
                    return "forbidden string marker"
    return None


_EXECUTION_ONLY_KEYS = frozenset(
    {
        "toolname",
        "function",
        "arguments",
        "exec",
        "run",
        "subprocess",
        "sh",
        "cmd",
        "shell",
        "bash",
        "toolcall",
        "toolcalls",
        "tooluse",
        "functioncall",
        "step",
        "steps",
    }
)
# Agent rows keep ``tool=`` / ``"tool":`` schema vocabulary. Math shape
# still uses the broader ``forbidden_string_patterns`` set.
_EXECUTION_STRING_PATTERNS = (
    r"\$\(",
    r"\b(?:ba)?sh\s+-c\b",
    r"\b(?:curl|wget)\b[\s\S]{0,120}\|\s*(?:ba)?sh\b",
    r"\bbase64\b[\s\S]{0,120}\|\s*(?:ba)?sh\b",
    r"(?:```|~~~)\s*(?:ba)?sh\b",
    r"(?:```|~~~)\s*zsh\b",
    r"\bpython(?:3)?\s+-c\b",
    r"(?<!\\)\brm\s+-",
    r"`[A-Za-z][A-Za-z0-9_./-]*`",
)


def _execution_pattern_mismatch(row: Mapping[str, Any]) -> str | None:
    """Prompt + exec-key scan for rows that are not Math-allowlisted.

    Agent rows keep legitimate ``action`` / ``tool`` schema keys; Math
    shape still uses the broader ``forbidden_keys`` set.
    """
    forbidden = _EXECUTION_ONLY_KEYS
    string_res = tuple(re.compile(pattern, re.I) for pattern in _EXECUTION_STRING_PATTERNS)
    stack: list[object] = [row]
    while stack:
        cur = stack.pop()
        if isinstance(cur, Mapping):
            for key, child in cur.items():
                if _forbidden_key_name(key, forbidden, ban_trajectory=False):
                    return f"forbidden key {key!r}"
                if type(key) is str and _shape_prompt_hit(key):
                    return "forbidden string marker"
                stack.append(child)
            continue
        if isinstance(cur, list):
            stack.extend(cur)
            continue
        if type(cur) is str:
            if _shape_prompt_hit(cur):
                return "forbidden string marker"
            scanned = _shape_scan_text(cur)
            for regex in string_res:
                if regex.search(cur) or regex.search(scanned):
                    return "forbidden string marker"
    return None


class ContentUuidRowError(Exception):
    def __init__(self, field: str, expected: object, actual: object, message: str) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(message)


def _raw_source_uuid(row: Mapping[str, Any]) -> str | None:
    """Raw ``source.uuid`` with no strip. None if absent. Whitespace is malformed."""
    source = row.get("source")
    if not isinstance(source, Mapping) or "uuid" not in source:
        return None
    value = source.get("uuid")
    if value is None:
        return None
    if type(value) is not str:
        raise ContentUuidRowError(
            "reserved_eval_partition.uuid_malformed",
            "string source.uuid",
            type(value).__name__,
            f"{_row_id(row)}:source.uuid is {type(value).__name__}",
        )
    if value != value.strip():
        raise ContentUuidRowError(
            "reserved_eval_partition.uuid_malformed",
            "source.uuid without surrounding whitespace",
            repr(value),
            f"{_row_id(row)}:source.uuid has surrounding whitespace",
        )
    if not value:
        return None
    return value


def collect_reserved_partition(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
    pinned_content_shas: set[str],
) -> list[tuple[str, str]]:
    """Refuse training rows in Mill's reserved eval partition N.

    One residue helper, ``content_uuid.eval_partition_residue``:
    ``int(sha256(ascii key).hexdigest(), 16) % 10``. A row WITH
    ``source.uuid`` uses the raw uuid as the key. A row WITHOUT
    ``source.uuid`` must be allowlisted and shape-clean (else
    ``uuid_missing``) and uses the lowercase 64-hex ``content_uuid`` as
    the key. A missing uuid is never a pass. Exact-content match and
    near-dup Jaccard >= 0.5 against N apply to every row.

    The modulus and residues live in ``RESERVED_EVAL_PARTITION``; a pack
    MANIFEST cannot remove them or disagree on ``n``/``modulus``. Content
    membership uses the gate-pinned reserved-content-uuid list plus extra
    MANIFEST shas. Near-dups of N are ``reserved_eval_partition.near_dup``.
    """
    cfg = _reserved_partition_cfg(manifest, pinned_content_shas)
    hits: list[tuple[str, str]] = []
    modulus = cfg["n"]
    residues: set[int] = cfg["residues"]
    reserved: set[str] = cfg["content_shas"]
    for row in _training_rows(recorded_paths):
        rid = _row_id(row)
        try:
            verified = content_uuid.verify_content_uuid(row)
        except content_uuid.ContentUuidError as exc:
            hits.append(("content_uuid", str(exc)))
            if len(hits) >= 10:
                return hits
            continue
        try:
            uuid_text = _raw_source_uuid(row)
        except ContentUuidRowError as exc:
            hits.append((exc.field, str(exc)))
            if len(hits) >= 10:
                return hits
            continue
        spec = _uuidless_allowlist_spec(row)
        if uuid_text is not None:
            try:
                residue = content_uuid.eval_partition_residue(uuid_text)
            except UnicodeEncodeError:
                hits.append(
                    (
                        "reserved_eval_partition.uuid_malformed",
                        f"{rid}:source.uuid is not ascii",
                    )
                )
                if len(hits) >= 10:
                    return hits
                continue
            residue = residue % modulus
            folded = uuid_text.casefold()
            folded_residue = residue
            # Case-only variants of an N uuid (all-upper / all-lower) still hit.
            # Mixed-case dataset ids keep their own residue (Mill golden vectors).
            if folded != uuid_text and (uuid_text.isupper() or uuid_text.islower()):
                try:
                    folded_residue = content_uuid.eval_partition_residue(folded) % modulus
                except UnicodeEncodeError:
                    folded_residue = residue
            if residue in residues or folded_residue in residues:
                shown = residue if residue in residues else folded_residue
                hits.append(
                    (
                        "reserved_eval_partition.uuid_mod",
                        f"{rid}:uuid_mod=={shown}",
                    )
                )
        if spec is not None:
            mismatch = _uuidless_shape_mismatch(row, spec)
            if mismatch:
                field = (
                    "reserved_eval_partition.uuid_missing.shape_mismatch"
                    if uuid_text is None
                    else "reserved_eval_partition.shape_mismatch"
                )
                hits.append((field, f"{rid}:{mismatch}"))
        else:
            pattern_hit = _execution_pattern_mismatch(row)
            if pattern_hit:
                hits.append(
                    (
                        "reserved_eval_partition.shape_mismatch",
                        f"{rid}:{pattern_hit}",
                    )
                )
        if uuid_text is None:
            if spec is None:
                hits.append(
                    (
                        "reserved_eval_partition.uuid_missing",
                        f"{rid}:missing source.uuid",
                    )
                )
            else:
                if verified is None:
                    hits.append(
                        (
                            "reserved_eval_partition.content_uuid",
                            f"{rid}:missing source.content_uuid",
                        )
                    )
                if not reserved:
                    hits.append(
                        (
                            "reserved_content_uuids",
                            f"{rid}:reserved list required for uuid-less allowlisted row",
                        )
                    )
            if len(hits) >= 10:
                return hits
        try:
            content_sha = content_uuid.content_uuid(row)
        except content_uuid.ContentUuidError as exc:
            hits.append((exc.field, str(exc)))
            if len(hits) >= 10:
                return hits
            continue
        if uuid_text is None:
            cuuid_residue = content_uuid.eval_partition_residue(content_sha) % modulus
            if cuuid_residue in residues:
                hits.append(
                    (
                        "reserved_eval_partition.uuid_mod",
                        f"{rid}:content_uuid_mod=={cuuid_residue}",
                    )
                )
        if content_sha in reserved:
            hits.append(
                (
                    "reserved_eval_partition.content_uuid",
                    f"{rid}:reserved content sha {content_sha}",
                )
            )
        if row_fields.mill_v2x_ready():
            hits.extend(_collect_v2x_near_dup(row, rid, reserved))
            if len(hits) >= 10:
                return hits
            continue
        try:
            cand_tokens = content_uuid.near_dup_tokens(row)
        except content_uuid.ContentUuidError as exc:
            hits.append((exc.field, f"{rid}:{exc}"))
            if len(hits) >= 10:
                return hits
            continue
        if content_uuid._is_no_text(cand_tokens):
            hits.append(
                (
                    "reserved_eval_partition.near_dup_no_text",
                    f"{rid}:NO_TEXT",
                )
            )
            if len(hits) >= 10:
                return hits
            continue
        if not isinstance(cand_tokens, frozenset):
            hits.append(
                (
                    "near_dup_tokens",
                    f"{rid}:tokenizer did not return a token set",
                )
            )
            if len(hits) >= 10:
                return hits
            continue
        for reserved_sha in reserved:
            indexed = content_uuid.lookup_near_dup_fingerprint(reserved_sha)
            if indexed is None:
                if content_uuid.kick_near_dup_fingerprints_loaded():
                    hits.append(
                        (
                            "reserved_eval_partition.near_dup_fingerprint_missing",
                            f"{rid}:no fingerprint for {reserved_sha}",
                        )
                    )
                    break
                continue
            n_id, n_tokens = indexed
            if n_tokens is None:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup_empty_tokens",
                        f"{rid}:empty fingerprint for {n_id}",
                    )
                )
                continue
            if not isinstance(n_tokens, frozenset):
                hits.append(
                    (
                        "reserved_eval_partition.near_dup_empty_tokens",
                        f"{rid}:invalid fingerprint for {n_id}",
                    )
                )
                continue
            if len(n_tokens) == 0:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup_empty_tokens",
                        f"{rid}:empty fingerprint for {n_id}",
                    )
                )
                continue
            scored = _candidate_tokens_for_fingerprint(cand_tokens, n_tokens)
            union = scored | n_tokens
            if len(union) == 0:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup_empty_tokens",
                        f"{rid}:empty token union",
                    )
                )
                continue
            jaccard = len(scored & n_tokens) / len(union)
            if jaccard >= 0.5:
                hits.append(
                    (
                        "reserved_eval_partition.near_dup",
                        f"{rid}:near_dup of {n_id}",
                    )
                )
                break
        if len(hits) >= 10:
            return hits
    return hits


def collect_denied_field_violations(
    recorded_paths: Mapping[str, str],
) -> list[tuple[str, str]]:
    """Refuse rows whose denied fields fail the mill v2.2 schema check."""
    if not row_fields.extract_paths_ready():
        return [("extract_paths", "mill tokenizer v2.2 is not vendored")]
    rows = _load_jsonl_rows(recorded_paths.get("train"))
    rows.extend(_load_jsonl_rows(recorded_paths.get("holdout")))
    if not rows:
        rows = _unique_pack_rows(recorded_paths)
    hits: list[tuple[str, str]] = []
    for row in rows:
        try:
            denied_field_schema.check_denied_fields(row)
        except denied_field_schema.DeniedFieldError as exc:
            hits.append((exc.field, f"{_row_id(row)}:{exc.reason}"))
            if len(hits) >= 10:
                return hits
    return hits


def collect_group_key_violations(
    recorded_paths: Mapping[str, str],
) -> list[tuple[str, str]]:
    """Refuse unknown/missing/case-variant subset and wrong group keys."""
    rows = _load_jsonl_rows(recorded_paths.get("train"))
    rows.extend(_load_jsonl_rows(recorded_paths.get("holdout")))
    if not rows:
        rows = _unique_pack_rows(recorded_paths)
    hits: list[tuple[str, str]] = []
    for row in rows:
        mismatch = _group_key_mismatch(row)
        if mismatch is None:
            continue
        rid = _row_id(row)
        hits.append((mismatch[0], f"{rid}:{mismatch[1]}"))
        if len(hits) >= 10:
            return hits
    return hits


def enforce_pack_gates(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
    *,
    smoke: bool = False,
    pack_dir: Path | str | None = None,
) -> None:
    hits = collect_not_for_train(manifest, recorded_paths)
    if hits and not smoke:
        _refuse("not_for_train", False, hits[:10])
    try:
        collisions = collect_content_uuid_collisions(recorded_paths)
    except content_uuid.ContentUuidError as exc:
        _refuse(exc.field, exc.expected, [str(exc)])
    if collisions:
        field = _content_uuid_collision_field(collisions[0])
        _refuse(field, "unique content uuid per labels", collisions[:10])
    forged = collect_forged_content_uuids(recorded_paths)
    if forged:
        _refuse("content_uuid", "recomputed digest", forged[:10])
    content_uuid.reset_kick_near_dup_fingerprints()
    pinned_shas = load_reserved_content_uuids(
        reserved_content_uuids_path(),
        RESERVED_CONTENT_UUIDS_SHA256,
    )
    if not (smoke and manifest.get("not_for_train") is True):
        reserved = collect_reserved_partition(manifest, recorded_paths, pinned_shas)
        if reserved:
            field = reserved[0][0]
            _refuse(field, "outside reserved slice", [msg for _field, msg in reserved[:10]])
        group_hits = collect_group_key_violations(recorded_paths)
        if group_hits:
            field = group_hits[0][0]
            _refuse(
                field,
                "one group key per subset",
                [msg for _field, msg in group_hits[:10]],
            )
        # Denied-field schema is mill v2.2 extract_paths/check_denied.
        # Until that tokenizer is vendored, do not author a local schema.
        # collect_denied_field_violations() fail-closes if invoked.
    leaks = collect_state_leaks(recorded_paths, pack_dir=pack_dir)
    if leaks:
        _refuse("state.leak", "absent", leaks[:10])


def _path_has_latest_token(text: str) -> bool:
    """True when ``latest`` is a path component or a ``_``/``-``-delimited token."""
    compact = text.replace("\\", "/").lower().strip().replace(" ", "")
    if compact in INBOX_LATEST_TOKENS:
        return True
    for part in compact.split("/"):
        if not part:
            continue
        if part in INBOX_LATEST_TOKENS or part == "latest":
            return True
        if any(token == "latest" for token in _LATEST_SPLIT_RE.split(part) if token):
            return True
    return False


def _looks_like_inbox_latest(value: str) -> bool:
    text = value.replace("\\", "/").lower().strip()
    compact = text.replace(" ", "")
    if text in INBOX_LATEST_TOKENS or compact in INBOX_LATEST_TOKENS:
        return True
    if _path_has_latest_token(text):
        return True
    return any(marker.lower() in compact for marker in INBOX_LATEST_PATH_MARKERS)


def refuse_implicit_inbox_pack(pack_dir: Path | str) -> None:
    """CLI/kick must not resolve inbox:latest or the live default inbox dir."""
    raw = str(pack_dir)
    if _looks_like_inbox_latest(raw):
        _refuse("pack", "explicit pack path", raw)


def refuse_inbox_latest(body: Mapping[str, Any] | None) -> None:
    """Kickoff must take an explicit pack path plus a pin. No inbox:latest default."""
    if not isinstance(body, Mapping):
        return
    if "inbox_latest" in body:
        _refuse("inbox_latest", "absent", "present")
    inbox = body.get("inbox")
    if isinstance(inbox, str) and _looks_like_inbox_latest(inbox):
        _refuse("inbox", "named pack_id", inbox)
    if inbox is True:
        _refuse("inbox", "named pack_id", True)
    for key in ("run_private_dir", "pack_dir", "pack"):
        value = body.get(key)
        if isinstance(value, str) and _looks_like_inbox_latest(value):
            _refuse(key, "explicit pack path", value)
    paths = body.get("paths")
    if isinstance(paths, Mapping):
        for key, value in paths.items():
            if isinstance(value, str) and _looks_like_inbox_latest(value):
                _refuse(f"paths.{key}", "explicit pack path", value)


def _force_remove(path: Path) -> None:
    path = Path(path)
    if not os.path.lexists(path):
        return

    def _onerror(func: Any, name: str, _exc: object) -> None:
        try:
            os.chmod(name, 0o700)
            func(name)
        except OSError:
            pass

    try:
        if path.is_symlink() or path.is_file():
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            path.unlink()
            return
        shutil.rmtree(path, onerror=_onerror)
    except OSError:
        pass


def assigned_checkpoint_id(run_id: str) -> str:
    """Smoke (and kick) own the checkpoint name. Launchers cannot pick it."""
    return f"ckpt-{run_id}"


def collect_forged_smoke_checkpoints(run_dir: Path, assigned: Path | None) -> list[Path]:
    """Any ckpt-* / smoke dir other than the run-scoped id is a forged snapshot."""
    extras: list[Path] = []
    root = Path(run_dir)
    if not root.is_dir():
        return extras
    assigned_resolved = assigned.resolve() if assigned is not None else None
    try:
        children = list(root.iterdir())
    except OSError:
        return extras
    for child in children:
        name = child.name
        if name != "smoke" and not name.startswith("ckpt-"):
            continue
        try:
            resolved = child.resolve()
        except OSError:
            extras.append(child)
            continue
        if assigned_resolved is not None and resolved == assigned_resolved:
            continue
        extras.append(child)
    return extras


def cleanup_smoke_artifacts(
    *,
    checkpoint_dir: Path | None,
    run_private: Path | None,
    inbox: Path | None,
) -> list[str]:
    """Delete smoke ckpt, run-dir copies, and inbox. Return surviving paths."""
    targets: list[tuple[str, Path]] = []
    if checkpoint_dir is not None:
        targets.append(("checkpoint", Path(checkpoint_dir)))
    if run_private is not None:
        targets.append(("run_private", Path(run_private)))
    if inbox is not None:
        targets.append(("inbox", Path(inbox)))
    survivors: list[str] = []
    for label, path in targets:
        _force_remove(path)
        if os.path.lexists(path):
            survivors.append(f"{label}:{path}")
    return survivors


def _empty_trainer_exit(*, waited: bool = False) -> dict[str, Any]:
    return {
        "exit_code": None,
        "signal": None,
        "timeout": False,
        "waited": waited,
        "observed": False,
    }


def _trainer_exit_is_observed(info: Mapping[str, Any]) -> bool:
    if not info.get("waited"):
        return False
    if info.get("timeout"):
        return True
    if info.get("signal") is not None:
        return True
    return info.get("exit_code") is not None


def _trainer_exit_is_bad(info: Mapping[str, Any]) -> bool:
    if not _trainer_exit_is_observed(info):
        return True
    if info.get("timeout"):
        return True
    if info.get("signal") is not None:
        return True
    return info.get("exit_code") not in (0,)


def _trainer_stdout_is_spoofed(text: str) -> bool:
    """Trainer stdout is never a result source. Flag MATCH-like evidence lines."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(INTEGRITY_EVIDENCE_LINE_PREFIX):
            return True
        if stripped.startswith("INTEGRITY_EVIDENCE "):
            return True
    return False


def combine_trainer_exits(parts: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Prefer the last waited trainer; unobserved or nonzero/signal/timeout is REFUSED."""
    recorded = _empty_trainer_exit()
    bad: dict[str, Any] | None = None
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        slim = {
            "exit_code": part.get("exit_code"),
            "signal": part.get("signal"),
            "timeout": bool(part.get("timeout")),
            "waited": bool(part.get("waited")),
            "observed": False,
        }
        slim["observed"] = _trainer_exit_is_observed(slim)
        if slim["waited"]:
            recorded = slim
        if _trainer_exit_is_bad(slim) and slim["observed"]:
            bad = slim
    if bad is not None:
        return bad
    if not recorded.get("observed"):
        return _empty_trainer_exit()
    return recorded


def _wait_process(proc: Any, wait_timeout: object) -> Any:
    wait = proc.wait
    if wait_timeout is None:
        return wait()
    try:
        return wait(timeout=wait_timeout)
    except TypeError:
        return wait()


def _exit_from_wait_rc(rc: object) -> dict[str, Any]:
    if rc is None:
        return _empty_trainer_exit(waited=True)
    try:
        code = int(rc)
    except (TypeError, ValueError):
        _refuse("trainer.exit", "int exit_code", rc)
        raise AssertionError("unreachable")
    info = {
        "exit_code": code,
        "signal": None,
        "timeout": False,
        "waited": True,
        "observed": True,
    }
    if code < 0:
        info["signal"] = -code
    return info


def wait_for_training_exit(launched: Mapping[str, Any] | None) -> dict[str, Any]:
    """Block until the trainer the launcher started has exited.

    Launchers that already wait (return after the process exits) are a no-op
    here. A pid or Popen-like ``process`` is waited in this same process.
    Returns ``exit_code`` / ``signal`` / ``timeout``. ``waited`` is True when
    this call observed a process, pid, or explicit launcher exit fields.
    """
    if not isinstance(launched, Mapping):
        return _empty_trainer_exit()
    waited_rc: object | None = None
    saw_process = False
    proc = launched.get("process")
    if proc is not None and hasattr(proc, "wait"):
        saw_process = True
        wait_timeout = launched.get("wait_timeout")
        try:
            waited_rc = _wait_process(proc, wait_timeout)
        except subprocess.TimeoutExpired:
            kill = getattr(proc, "kill", None)
            if callable(kill):
                try:
                    kill()
                    _wait_process(proc, None)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            return {
                "exit_code": None,
                "signal": None,
                "timeout": True,
                "waited": True,
                "observed": True,
            }
        if waited_rc is None:
            waited_rc = getattr(proc, "returncode", None)
        # The process wait return code is the source of truth. A launcher dict
        # that also carries exit_code=0 must not hide a nonzero wait().
        return _exit_from_wait_rc(waited_rc)
    pid = launched.get("pid") if launched.get("pid") is not None else launched.get("trainer_pid")
    if pid is not None:
        try:
            _wpid, status = os.waitpid(int(pid), 0)
            del _wpid
            if os.WIFSIGNALED(status):
                sig = os.WTERMSIG(status)
                return {
                    "exit_code": -sig,
                    "signal": sig,
                    "timeout": False,
                    "waited": True,
                    "observed": True,
                }
            if os.WIFEXITED(status):
                return {
                    "exit_code": os.WEXITSTATUS(status),
                    "signal": None,
                    "timeout": False,
                    "waited": True,
                    "observed": True,
                }
            return _exit_from_wait_rc(status)
        except ChildProcessError:
            pass
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            _refuse("trainer.pid", "waitable pid", f"{type(exc).__name__}:{exc}")
    if launched.get("timeout") is True:
        return {
            "exit_code": launched.get("exit_code"),
            "signal": launched.get("signal"),
            "timeout": True,
            "waited": True,
            "observed": True,
        }
    if launched.get("signal") is not None:
        try:
            sig = int(launched["signal"])
        except (TypeError, ValueError):
            _refuse("trainer.exit", "signal number", launched.get("signal"))
            raise AssertionError("unreachable")
        code = launched.get("exit_code", -sig)
        try:
            code_i = int(code) if code is not None else -sig
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", code)
            raise AssertionError("unreachable")
        return {
            "exit_code": code_i,
            "signal": sig,
            "timeout": False,
            "waited": True,
            "observed": True,
        }
    if "exit_code" in launched:
        code = launched.get("exit_code")
        try:
            code_i = int(code) if code is not None else 0
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", code)
            raise AssertionError("unreachable")
        info = {
            "exit_code": code_i,
            "signal": None,
            "timeout": False,
            "waited": True,
            "observed": True,
        }
        if code_i < 0:
            info["signal"] = -code_i
        return info
    return _empty_trainer_exit()


def apply_trainer_exit(record: dict[str, Any], exit_info: Mapping[str, Any] | None) -> dict[str, Any]:
    """Record trainer exit on the integrity evidence. Unobserved or bad exit is REFUSED."""
    info = dict(exit_info) if isinstance(exit_info, Mapping) else _empty_trainer_exit()
    timeout = bool(info.get("timeout"))
    signal = info.get("signal")
    if signal is not None:
        try:
            signal = int(signal)
        except (TypeError, ValueError):
            _refuse("trainer.exit", "signal number", signal)
            raise AssertionError("unreachable")
    exit_code = info.get("exit_code")
    if timeout:
        pass
    elif exit_code is None:
        pass
    else:
        try:
            exit_code = int(exit_code)
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", exit_code)
            raise AssertionError("unreachable")
    record["exit_code"] = exit_code
    record["trainer_exit_waited"] = bool(info.get("waited"))
    record["trainer_exit_observed"] = _trainer_exit_is_observed(info)
    if signal is not None:
        record["signal"] = signal
    if timeout:
        record["timeout"] = True
    unobserved = not _trainer_exit_is_observed(info)
    bad = unobserved or timeout or signal is not None or exit_code not in (0,)
    if bad and record.get("status") == CHECKPOINT_MATCH:
        record["status"] = CHECKPOINT_REFUSED
        record["match"] = False
        record["field"] = "trainer.exit"
        record["expected"] = 0
        if unobserved:
            record["actual"] = "unobserved"
        elif timeout:
            record["actual"] = "timeout"
        elif signal is not None:
            record["actual"] = f"signal {signal}"
        else:
            record["actual"] = exit_code
    return record


def checkpoint_dir_for(run_dir: Path, checkpoint_id: object) -> Path | None:
    if checkpoint_id is None or checkpoint_id is False:
        return None
    text = str(checkpoint_id).strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        _refuse("checkpoint_id", "single path segment", checkpoint_id)
    return Path(run_dir) / text


def checkpoint_integrity_status(checkpoint_dir: Path) -> str:
    path = Path(checkpoint_dir) / INTEGRITY_EVIDENCE_NAME
    if not path.is_file():
        return CHECKPOINT_UNSCORED
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return CHECKPOINT_UNSCORED
    if not isinstance(data, dict):
        return CHECKPOINT_UNSCORED
    if data.get("smoke") is True:
        return CHECKPOINT_UNSCORED
    status = data.get("status")
    if status in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED):
        return str(status)
    return CHECKPOINT_UNSCORED


def _require_mode_0400(path: Path, field: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        _refuse(field, "present", "missing")
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    if stat.S_ISLNK(info.st_mode):
        _refuse(field, "regular file", "symlink")
    if not stat.S_ISREG(info.st_mode):
        _refuse(field, "regular file", "non-regular")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o400:
        _refuse(field, "0400", oct(stat.S_IMODE(info.st_mode)))


def rehash_recorded_trainer_paths(
    recorded_paths: Mapping[str, str],
    *,
    pin: Mapping[str, Any],
    manifest_shas: Mapping[str, str],
    host: str,
) -> dict[str, Any]:
    """Re-hash the exact files the trainer read. Same host/process as launch."""
    post: dict[str, str] = {}
    record: dict[str, Any] = {
        "status": CHECKPOINT_MATCH,
        "host": host,
        "paths": {key: recorded_paths[key] for key in TRAINER_PATH_FILES},
        "computed_shas": post,
        "pin_shas": {
            "sha256_pack": pin["sha256_pack"],
            "sha256_train": pin["sha256_train"],
            "sha256_holdout": pin["sha256_holdout"],
        },
        "manifest_shas": dict(manifest_shas),
        "checked_at": _utc_now(),
        "match": True,
    }
    try:
        for sha_field, path_key in PATH_KEY_BY_SHA.items():
            path = Path(recorded_paths[path_key])
            _require_mode_0400(path, sha_field)
            actual = sha256_file(path)
            post[sha_field] = actual
            pin_sha = pin[sha_field]
            man_sha = manifest_shas[sha_field]
            if actual != pin_sha:
                _refuse(sha_field, pin_sha, actual)
            if actual != man_sha:
                _refuse(sha_field, man_sha, actual)
        _require_mode_0400(Path(recorded_paths["manifest"]), MANIFEST_FILE)
    except KickRefused as exc:
        record["status"] = CHECKPOINT_REFUSED
        record["match"] = False
        record["field"] = exc.field
        record["expected"] = exc.expected
        record["actual"] = exc.actual
    record["computed_shas"] = post
    record["checked_at"] = _utc_now()
    return record


def _public_integrity_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not str(key).startswith("_")}


def verify_and_stage(
    pack_dir: Path,
    *,
    run_private: Path,
    pin_record: Mapping[str, Any],
    run_id: str,
    smoke: bool = False,
    pin_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Copy-hash pack/train/holdout and check them against the staged v2 pin.

    Returns evidence fields on success. Raises KickRefused on any failure. Does not
    start training or POST kickoff. No MANIFEST-only or ticket fallback. Never fetches.
    The verified pin bytes are written to ``run_private/cam-pin-v2.json`` so the
    launcher never takes ``pin_path`` from the kick POST body.
    """
    _refuse_skip_env()
    _refuse_pin_env()
    refuse_implicit_inbox_pack(pack_dir)
    pack_root = _resolve_pack_dir(Path(pack_dir))
    refuse_implicit_inbox_pack(pack_root)
    _refuse_local_pin_files(pack_root)
    run_private = _require_run_private_dir(Path(run_private))
    need = 0
    for filename in (MANIFEST_FILE, PACK_FILE, TRAIN_FILE, HOLDOUT_FILE):
        src = _regular_file_in_pack(pack_root, filename)
        try:
            need += os.path.getsize(src)
        except OSError as exc:
            _refuse(filename, "readable regular file", f"OSError:{exc.errno}")
    try:
        for child in pack_root.iterdir():
            if child.suffix != ".jsonl" or child.name in _LEAK_PACK_JSONL:
                continue
            try:
                need += os.path.getsize(child)
            except OSError as exc:
                _refuse(child.name, "readable regular file", f"OSError:{exc.errno}")
    except OSError as exc:
        _refuse("sidecar", "readable jsonl", f"OSError:{exc.errno}")
    if type(pin_bytes) is bytes:
        need += len(pin_bytes)
    # Staged copies plus sealed memfds share the tmpfs (shmem).
    _require_run_private_capacity(run_private, need * 2)

    copy_dir_fd = _open_dir_nofollow(str(run_private))
    global _COPY_DIR_FD
    prev_copy_fd = _COPY_DIR_FD
    _COPY_DIR_FD = copy_dir_fd
    try:
        if type(pin_bytes) is not bytes or not pin_bytes:
            _refuse("cam-pin", "staged v2 pin bytes", "missing")
        _stage_verified_pin_bytes(run_private, pin_bytes)
        manifest_dest = run_private / MANIFEST_FILE
        manifest_sha = _copy_and_hash(
            _regular_file_in_pack(pack_root, MANIFEST_FILE), manifest_dest, MANIFEST_FILE
        )
        manifest_buf = _verify_manifest_copy(run_private, manifest_sha)
        try:
            manifest = json.loads(manifest_buf.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
        except UnicodeDecodeError:
            _refuse(MANIFEST_FILE, "utf-8 text", "invalid encoding")
        except ValueError as exc:
            _refuse(MANIFEST_FILE, "valid JSON object", f"invalid JSON ({exc})")
        if not isinstance(manifest, dict):
            _refuse(MANIFEST_FILE, "valid JSON object", type(manifest).__name__)
        pack_id = manifest.get("pack_id")
        if type(pack_id) is not str or not pack_id:
            _refuse("pack_id", "present", "missing")
        if manifest.get("champion_touched") is not False:
            _refuse("champion_touched", False, manifest.get("champion_touched"))
        pin = _require_cam_pin(pin_record, pack_id, run_id=run_id)
        claimed_reserved = pin.get("reserved_content_uuids_sha256")
        if claimed_reserved != RESERVED_CONTENT_UUIDS_SHA256:
            _refuse(
                "cam-pin.reserved_content_uuids_sha256",
                RESERVED_CONTENT_UUIDS_SHA256,
                claimed_reserved,
            )
        claimed_min = pin.get("reserved_content_uuids_min_rows")
        if claimed_min != RESERVED_CONTENT_UUIDS_MIN_ROWS:
            _refuse(
                "cam-pin.reserved_content_uuids_min_rows",
                RESERVED_CONTENT_UUIDS_MIN_ROWS,
                claimed_min,
            )
        claimed_manifest = pin.get("sha256_manifest")
        if claimed_manifest != manifest_sha:
            _refuse("cam-pin.sha256_manifest", manifest_sha, claimed_manifest)
        try:
            content_uuid.require_near_dup_tokenizer_version(
                pin.get("near_dup_tokenizer_version")
            )
        except content_uuid.ContentUuidError as exc:
            _refuse(exc.field, exc.expected, exc.actual)
        claimed_tok_sha = pin.get("near_dup_tokenizer_sha256")
        if claimed_tok_sha != content_uuid.NEAR_DUP_TOKENIZER_SHA256:
            _refuse(
                "cam-pin.near_dup_tokenizer_sha256",
                content_uuid.NEAR_DUP_TOKENIZER_SHA256,
                claimed_tok_sha,
            )

        computed_shas: dict[str, str] = {}
        manifest_shas: dict[str, str] = {}
        row_counts: dict[str, dict[str, int]] = {}

        for sha_field, filename, rows_field, pin_rows_field in ARTIFACTS:
            src = _regular_file_in_pack(pack_root, filename)
            dest = run_private / filename
            computed = _copy_and_hash(src, dest, sha_field)
            if rows_field not in manifest:
                _refuse(rows_field, "present", "missing")
            expected_rows = _require_int(rows_field, manifest[rows_field])
            actual_rows = count_rows(dest)
            pin_rows = pin[pin_rows_field]
            if pin_rows != expected_rows:
                _refuse(pin_rows_field, pin_rows, expected_rows)
            if pin_rows != actual_rows:
                _refuse(pin_rows_field, pin_rows, actual_rows)
            if actual_rows != expected_rows:
                _refuse(rows_field, expected_rows, actual_rows)
            manifest_value = manifest.get(sha_field)
            if not isinstance(manifest_value, str) or not manifest_value:
                _refuse(sha_field, "present", "missing")
            file_manifest_sha = _require_sha256_hex(sha_field, manifest_value)
            pin_sha = pin[sha_field]
            if pin_sha != file_manifest_sha:
                _refuse(sha_field, pin_sha, file_manifest_sha)
            if pin_sha != computed:
                _refuse(sha_field, pin_sha, computed)
            computed_shas[sha_field] = computed
            manifest_shas[sha_field] = file_manifest_sha
            row_counts[filename] = {"expected": expected_rows, "actual": actual_rows}

        try:
            for child in pack_root.iterdir():
                if not child.is_file() or child.suffix != ".jsonl":
                    continue
                if child.name in _LEAK_PACK_JSONL:
                    continue
                src = _regular_file_in_pack(pack_root, child.name)
                _copy_and_hash(src, run_private / child.name, child.name)
        except OSError as exc:
            _refuse("sidecar", "readable jsonl", f"OSError:{exc.errno}")

        trainer_paths = trainer_input_paths(run_private)
        _split_soundness(run_private, computed_shas)
        enforce_pack_gates(
            manifest,
            trainer_paths,
            smoke=smoke,
            pack_dir=run_private,
        )
        _verify_manifest_copy(run_private, manifest_sha)

        return {
            "pack_id": pack_id,
            "host": socket.gethostname(),
            "anchor_source": PIN_SOURCE,
            "pin": pin,
            "computed_shas": computed_shas,
            "private_copy_shas": dict(computed_shas),
            "expected_shas": {
                "sha256_pack": pin["sha256_pack"],
                "sha256_train": pin["sha256_train"],
                "sha256_holdout": pin["sha256_holdout"],
            },
            "manifest_shas": manifest_shas,
            "sha256_manifest": manifest_sha,
            "row_counts": row_counts,
            "paths": trainer_paths,
            "run_private_dir": str(run_private.resolve()),
            "source_pack_dir": str(pack_root),
            "checked_at": _utc_now(),
            "ok": True,
        }
    finally:
        _COPY_DIR_FD = prev_copy_fd
        _close_quietly(copy_dir_fd)


def write_evidence(
    evidence: Mapping[str, Any],
    evidence_path: Path,
    *,
    mode: int | None = None,
) -> Path:
    """Atomically write evidence JSON (mkstemp in the same directory + os.replace).

    Checkpoint ``integrity_evidence.json`` must use
    ``write_integrity_evidence_held`` instead: this replace path is the B-RACE
    window. Overwrite is only for the run-dir pack evidence log.
    """
    evidence_path = Path(evidence_path)
    if evidence_path.name == INTEGRITY_EVIDENCE_NAME:
        write_integrity_evidence_held(dict(evidence), evidence_path)
        return evidence_path
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(evidence), indent=2) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        prefix=evidence_path.name + ".",
        suffix=".tmp",
        dir=str(evidence_path.parent),
    )
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    os.replace(tmp_name, evidence_path)
    if mode is not None and os.name == "posix":
        os.chmod(evidence_path, mode)
    return evidence_path


def write_integrity_evidence_held(
    record: Mapping[str, Any],
    evidence_path: Path,
) -> dict[str, Any]:
    """O_CREAT|O_EXCL write of checkpoint evidence. Hash the bytes written.

    Completion ``result`` is the in-memory ``record["status"]``, never a
    re-read of a replaceable path. After fsync/fchmod, fstat the held fd
    and refuse if the named path's dev/inode differ (swapper).
    """
    evidence_path = Path(evidence_path)
    public = _public_integrity_record(record)
    payload = (json.dumps(public, indent=2) + "\n").encode("utf-8")
    sha256_evidence = hashlib.sha256(payload).hexdigest()
    status = public.get("status")
    result = status if status in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED) else CHECKPOINT_REFUSED
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(evidence_path):
        try:
            os.chmod(evidence_path, 0o600)
        except OSError:
            pass
        try:
            os.unlink(evidence_path)
        except OSError as exc:
            _refuse(INTEGRITY_EVIDENCE_NAME, "exclusive create", f"OSError:{exc.errno}")
    try:
        fd = os.open(str(evidence_path), _open_flags_write(), 0o600)
    except OSError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "exclusive create", f"OSError:{exc.errno}")
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, view[offset:])
        if hasattr(os, "fsync"):
            os.fsync(fd)
        if os.name == "posix" and hasattr(os, "fchmod"):
            os.fchmod(fd, 0o400)
        written = os.fstat(fd)
        try:
            named = os.lstat(evidence_path)
        except OSError as exc:
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", f"OSError:{exc.errno}")
        if (written.st_dev, written.st_ino) != (named.st_dev, named.st_ino):
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", "path swapped")
        if named.st_nlink != 1:
            _refuse(INTEGRITY_EVIDENCE_NAME, "nlink=1", named.st_nlink)
        if os.name == "posix" and stat.S_IMODE(written.st_mode) != 0o400:
            _refuse(
                INTEGRITY_EVIDENCE_NAME,
                "0400",
                oct(stat.S_IMODE(written.st_mode)),
            )
    except KickRefused:
        raise
    except OSError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "held-fd write", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    return {
        "sha256_evidence": sha256_evidence,
        "integrity_evidence": json.loads(payload.decode("utf-8")),
        "result": result,
        "st_dev": written.st_dev,
        "st_ino": written.st_ino,
    }


def format_integrity_evidence_line(
    *,
    sha256_evidence: str,
    sha256_pack: str,
    sha256_train: str,
    sha256_holdout: str,
    result: str,
    host: str,
) -> str:
    return (
        f"{INTEGRITY_EVIDENCE_LINE_PREFIX} sha256_evidence={sha256_evidence} "
        f"sha256_pack={sha256_pack} sha256_train={sha256_train} "
        f"sha256_holdout={sha256_holdout} result={result} host={host}"
    )


def parse_integrity_evidence_line(line: str) -> dict[str, str]:
    """Parse the structured operator line. Keys are the sha/result/host fields."""
    text = line.strip()
    if not text.startswith(INTEGRITY_EVIDENCE_LINE_PREFIX + " "):
        _refuse("integrity_evidence_line", INTEGRITY_EVIDENCE_LINE_PREFIX, text[:32])
    parsed: dict[str, str] = {}
    for part in text.split()[1:]:
        key, sep, value = part.partition("=")
        if not sep or not key:
            _refuse("integrity_evidence_line", "key=value fields", part)
        parsed[key] = value
    required = (
        "sha256_evidence",
        "sha256_pack",
        "sha256_train",
        "sha256_holdout",
        "result",
        "host",
    )
    for key in required:
        if key not in parsed:
            _refuse("integrity_evidence_line", key, "missing")
    if parsed["result"] not in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED):
        _refuse("integrity_evidence_line.result", "MATCH|REFUSED", parsed["result"])
    for sha_key in ("sha256_evidence", "sha256_pack", "sha256_train", "sha256_holdout"):
        digest = parsed[sha_key]
        if len(digest) != SHA256_LEN or any(ch not in _HEX for ch in digest):
            _refuse(f"integrity_evidence_line.{sha_key}", "64-char lowercase hex", digest)
    return parsed


def emit_integrity_evidence_line(
    evidence_path: Path,
    record: Mapping[str, Any],
    *,
    log_path: Path | None = None,
    sha256_evidence: str | None = None,
) -> str:
    """Print one human line after the trainer's stdout is closed. Never a result source."""
    evidence_path = Path(evidence_path)
    if os.name == "posix":
        os.chmod(evidence_path, 0o400)
    if sha256_evidence is None:
        sha256_evidence = sha256_file(evidence_path)
    computed = record.get("computed_shas") if isinstance(record.get("computed_shas"), Mapping) else {}
    pin_shas = record.get("pin_shas") if isinstance(record.get("pin_shas"), Mapping) else {}

    def _sha(field: str) -> str:
        value = computed.get(field) or pin_shas.get(field)
        if type(value) is not str or not value:
            _refuse(field, "64-char lowercase hex", value)
        return value

    line = format_integrity_evidence_line(
        sha256_evidence=sha256_evidence,
        sha256_pack=_sha("sha256_pack"),
        sha256_train=_sha("sha256_train"),
        sha256_holdout=_sha("sha256_holdout"),
        result=str(record.get("status") or CHECKPOINT_REFUSED),
        host=str(record.get("host") or socket.gethostname()),
    )
    print(line, flush=True)
    if log_path is not None:
        log = Path(log_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return line


def load_integrity_completion(evidence_path: Path) -> dict[str, Any]:
    """sha256_evidence and parsed JSON from the 0400 file. Never stdout."""
    evidence_path = Path(evidence_path)
    _require_mode_0400(evidence_path, INTEGRITY_EVIDENCE_NAME)
    sha256_evidence = sha256_file(evidence_path)
    try:
        parsed = json.loads(evidence_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        _refuse(INTEGRITY_EVIDENCE_NAME, "utf-8 JSON", "invalid encoding")
        raise AssertionError("unreachable")
    except OSError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "readable JSON", f"OSError:{exc.errno}")
        raise AssertionError("unreachable")
    except ValueError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "valid JSON object", f"invalid JSON ({exc})")
        raise AssertionError("unreachable")
    if not isinstance(parsed, dict):
        _refuse(INTEGRITY_EVIDENCE_NAME, "JSON object", type(parsed).__name__)
    status = parsed.get("status")
    result = status if status in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED) else CHECKPOINT_REFUSED
    return {
        "sha256_evidence": sha256_evidence,
        "integrity_evidence": parsed,
        "result": result,
    }


def seal_integrity_evidence(
    evidence_path: Path,
    record: Mapping[str, Any],
    *,
    log_path: Path | None = None,
    sealed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit the human line from the in-memory held-fd write. Never re-parse for result."""
    if sealed is None:
        sealed = write_integrity_evidence_held(record, evidence_path)
    out = dict(sealed)
    line = emit_integrity_evidence_line(
        evidence_path,
        record,
        log_path=log_path,
        sha256_evidence=out["sha256_evidence"],
    )
    out["integrity_evidence_line"] = line
    out["result"] = (
        record["status"]
        if record.get("status") in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED)
        else CHECKPOINT_REFUSED
    )
    return out


def _sha_from_record(record: Mapping[str, Any], field: str) -> str:
    computed = record.get("computed_shas") if isinstance(record.get("computed_shas"), Mapping) else {}
    pin_shas = record.get("pin_shas") if isinstance(record.get("pin_shas"), Mapping) else {}
    value = computed.get(field) or pin_shas.get(field)
    if type(value) is not str or not value:
        _refuse(field, "64-char lowercase hex", value)
    return value


def _post_hq_event(event: str, payload: Mapping[str, Any]) -> None:
    try:
        cam_pin_spec.post_hq_event(event, dict(payload))
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


def default_start_training(pack_dir: Path, evidence: dict[str, Any], log_path: Path) -> dict[str, Any]:
    """Public alias that always refuses: the train hook is not a skip path."""
    _refuse("start_training", "via kick() after integrity gate", "direct call")


_TRAINER_FD_CONSUME = (
    "import hashlib, os, sys\n"
    "out = []\n"
    "for raw in sys.argv[1:]:\n"
    "    fd = int(raw)\n"
    "    h = hashlib.sha256()\n"
    "    while True:\n"
    "        block = os.read(fd, 1 << 20)\n"
    "        if not block:\n"
    "            break\n"
    "        h.update(block)\n"
    "    out.append(h.hexdigest())\n"
    "sys.stdout.write(','.join(out))\n"
)


def _authorized_start_training(
    pack_dir: Path,
    evidence: dict[str, Any],
    log_path: Path,
    *,
    _gate: object,
    sealed_fds: Mapping[str, int] | None = None,
    verified: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    if _gate is not _GATE_OK:
        _refuse("start_training", "via kick() after integrity gate", "direct call")
    inputs = dict(verified) if verified is not None else _open_and_verify_trainer_inputs(evidence)
    train_buf = inputs["train"]
    pack_buf = inputs["pack"]
    holdout_buf = inputs["holdout"]
    pin = evidence.get("pin") if isinstance(evidence.get("pin"), Mapping) else {}
    train_sha = hashlib.sha256(train_buf).hexdigest()
    pack_sha = hashlib.sha256(pack_buf).hexdigest()
    holdout_sha = hashlib.sha256(holdout_buf).hexdigest()
    pin_train = pin.get("sha256_train")
    pin_pack = pin.get("sha256_pack")
    pin_holdout = pin.get("sha256_holdout")
    if type(pin_train) is str and not hmac.compare_digest(train_sha, pin_train):
        _refuse("sha256_train", pin_train, train_sha)
    if type(pin_pack) is str and not hmac.compare_digest(pack_sha, pin_pack):
        _refuse("sha256_pack", pin_pack, pack_sha)
    if type(pin_holdout) is str and not hmac.compare_digest(holdout_sha, pin_holdout):
        _refuse("sha256_holdout", pin_holdout, holdout_sha)
    fds = dict(sealed_fds) if sealed_fds is not None else seal_verified_buffers(inputs)
    ordered_keys = ("pack", "train", "holdout")
    pass_fds = tuple(int(fds[key]) for key in ordered_keys if key in fds)
    argv = [sys.executable, "-c", _TRAINER_FD_CONSUME, *[str(fd) for fd in pass_fds]]
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=pass_fds,
        close_fds=True,
    )
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        _refuse(
            "trainer.exit",
            0,
            f"rc={proc.returncode} stderr={stderr[-200:]!r}",
        )
    consumed = stdout.decode("utf-8").strip().split(",") if stdout else []
    if len(consumed) >= 2 and not hmac.compare_digest(consumed[1], train_sha):
        _refuse("sha256_train", train_sha, consumed[1])
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{evidence['checked_at']} HELPER_FT_KICK allowed "
        f"pack_id={evidence['pack_id']} host={evidence['host']} "
        f"run_id={evidence.get('run_id')} anchor_source={evidence['anchor_source']} "
        f"auto_promote=false inputs={pack_dir}\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return {
        "training_started": True,
        "auto_promote": False,
        "pack_dir": str(pack_dir),
        "ok": True,
        "exit_code": 0,
        "train_sha256": train_sha,
        "pack_sha256": pack_sha,
        "holdout_sha256": holdout_sha,
        "process": proc,
    }


def post_kickoff(body: dict[str, Any], url: str = DEFAULT_KICKOFF_URL) -> dict[str, Any]:
    """POST the HELPER FT kickoff. Tests mock this; production hits :8765."""
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        _refuse("kickoff", "HTTP success", str(exc.reason) if getattr(exc, "reason", None) else str(exc))
    except OSError as exc:
        _refuse("kickoff", "HTTP success", f"OSError:{getattr(exc, 'errno', None)}")
    try:
        result = json.loads(raw) if raw else {}
    except ValueError:
        _refuse("kickoff", "JSON object", "invalid JSON")
    if not isinstance(result, dict) or result.get("ok") is not True:
        _refuse("kickoff", "ok", result)
    return result


def _apply_post_train_record(
    evidence: dict[str, Any],
    record: Mapping[str, Any],
    *,
    run_dir: Path,
    log_path: Path | None = None,
    post_completion: bool = True,
) -> None:
    evidence["post_train_shas"] = dict(record.get("computed_shas") or {})
    evidence["post_train_host"] = record["host"]
    evidence["post_train_paths"] = dict(record["paths"])
    evidence["post_train_checked_at"] = record["checked_at"]
    evidence["exit_code"] = record.get("exit_code", 0)
    if record.get("signal") is not None:
        evidence["signal"] = record["signal"]
    if record.get("timeout"):
        evidence["timeout"] = True
    ckpt_dir = checkpoint_dir_for(run_dir, evidence.get("checkpoint_id"))
    if ckpt_dir is not None:
        ckpt_path = ckpt_dir / INTEGRITY_EVIDENCE_NAME
        public = _public_integrity_record(record)
        public.update(_entrypoint_event_fields(evidence))
        if "script_git_sha" in evidence:
            public["script_git_sha"] = evidence["script_git_sha"]
        if isinstance(evidence.get("private_copy_shas"), Mapping):
            public["private_copy_shas"] = dict(evidence["private_copy_shas"])
        if evidence.get("run_private_dir"):
            public["run_private_dir"] = evidence["run_private_dir"]
        if "stdout_spoof" in evidence:
            public["stdout_spoof"] = bool(evidence["stdout_spoof"])
        if "scorable" in evidence:
            public["scorable"] = bool(evidence["scorable"])
        in_memory_result = (
            record["status"]
            if record.get("status") in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED)
            else CHECKPOINT_REFUSED
        )
        sealed = write_integrity_evidence_held(public, ckpt_path)
        try:
            named = os.lstat(ckpt_path)
        except OSError as exc:
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", f"OSError:{exc.errno}")
        if (named.st_dev, named.st_ino) != (sealed["st_dev"], sealed["st_ino"]):
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", "path swapped")
        sealed = seal_integrity_evidence(
            ckpt_path, record, log_path=log_path, sealed=sealed
        )
        evidence["checkpoint_integrity_evidence_path"] = str(ckpt_path.resolve())
        evidence["checkpoint_integrity_status"] = record["status"]
        evidence["integrity_evidence_line"] = sealed["integrity_evidence_line"]
        evidence["sha256_evidence"] = sealed["sha256_evidence"]
        evidence["integrity_evidence"] = sealed["integrity_evidence"]
        evidence["result"] = in_memory_result
        if post_completion:
            completion = {
                "run_id": evidence["run_id"],
                "sha256_evidence": sealed["sha256_evidence"],
                "sha256_pack": _sha_from_record(record, "sha256_pack"),
                "sha256_train": _sha_from_record(record, "sha256_train"),
                "sha256_holdout": _sha_from_record(record, "sha256_holdout"),
                "result": in_memory_result,
                "exit_code": record.get("exit_code", 0),
            }
            completion.update(_entrypoint_event_fields(evidence))
            try:
                _post_hq_event("completion", completion)
            except KickRefused as exc:
                refused = dict(public)
                refused["status"] = CHECKPOINT_REFUSED
                refused["match"] = False
                refused["field"] = "hq.event"
                refused["expected"] = "posted"
                refused["actual"] = "hq_post_failed"
                write_integrity_evidence_held(refused, ckpt_path)
                evidence["checkpoint_integrity_status"] = CHECKPOINT_REFUSED
                evidence["result"] = CHECKPOINT_REFUSED
                evidence["hq_post_failed"] = True
                evidence["ok"] = False
                raise KickRefused("hq.event", "posted", "hq_post_failed") from exc
    if record["status"] != CHECKPOINT_MATCH:
        evidence["ok"] = False
        evidence["result"] = CHECKPOINT_REFUSED


def _recheck_copies(
    run_private: Path,
    evidence: dict[str, Any],
    *,
    run_dir: Path,
    log_path: Path | None = None,
    exit_info: Mapping[str, Any] | None = None,
    smoke: bool = False,
) -> None:
    recorded = evidence.get("paths")
    if not isinstance(recorded, dict):
        recorded = trainer_input_paths(run_private)
    host = socket.gethostname()
    record = rehash_recorded_trainer_paths(
        recorded,
        pin=evidence["pin"],
        manifest_shas=evidence["manifest_shas"],
        host=host,
    )
    apply_trainer_exit(record, exit_info)
    if smoke:
        record["smoke"] = True
    _apply_post_train_record(
        evidence,
        record,
        run_dir=run_dir,
        log_path=log_path,
        post_completion=not smoke,
    )
    if record["status"] != CHECKPOINT_MATCH:
        _refuse(record.get("field", "post_train"), record.get("expected"), record.get("actual"))


def probe_sealed_code_pins(
    *,
    root: Path,
    pin: Mapping[str, Any],
    run_id: str,
) -> Any:
    """Production caller of ``launch_sealed_child``. Refuses drifted CODE_PINS.

    ``helper_ft_kickoff`` imports this module at top level, so the sealed-child
    launcher is imported here only for this production probe.
    """
    import helper_ft_kickoff as _kickoff  # circular: helper_ft_kickoff imports this module

    try:
        proc = _kickoff.launch_sealed_child(root=root, pin=pin, run_id=run_id)
    except KickRefused:
        raise
    if proc.returncode != 0 or "HELPER_FT_SEALED_OK" not in (proc.stdout or ""):
        _refuse(
            "cam-pin.code_pins",
            "sealed child HELPER_FT_SEALED_OK",
            "sealed child refused",
        )
    return proc


def kick(
    pack_dir: Path,
    *,
    run_id: str | None = None,
    pin_path: str | Path | int | None = None,
    log_path: Path | None = None,
    start_training: StartTraining | None = None,
    kickoff: KickoffFn | None = None,
    kickoff_url: str = DEFAULT_KICKOFF_URL,
    smoke: bool = False,
) -> dict[str, Any]:
    """Verify the staged v2 pin, stage private copies, POST kickoff, re-check shas.

    ``run_id`` is required and must match the pin binding. ``pin_path`` is a
    held fd or a path under ``FORGE_RUN_PRIVATE_ROOT``. This process never
    fetches a pin. ``start_training`` / ``kickoff`` are test injection hooks
    and still run only after the gate. CLI and env cannot supply them. There
    is no skip/override. ``smoke=True`` never posts HQ events, marks evidence
    unscorable, and deletes checkpoint/run-dir copies/inbox before returning.
    """
    _refuse_skip_env()
    _refuse_pin_env()
    refuse_implicit_inbox_pack(pack_dir)
    pack_dir = Path(pack_dir)
    smoke = bool(smoke)
    _refuse_local_pin_files(_resolve_pack_dir(pack_dir))
    path_run_id = run_id if type(run_id) is str and run_id else "refused"
    assigned_ckpt = assigned_checkpoint_id(path_run_id)
    if log_path is not None:
        log_path = Path(log_path)
        run_dir = log_path.parent
    else:
        run_dir = Path(tempfile.mkdtemp(prefix=f"{path_run_id}-"))
        log_path = run_dir / DEFAULT_LOG_NAME
    run_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = run_dir / f"pack_integrity_evidence_{path_run_id}.json"
    run_private: Path | None = None
    sealed_fds: dict[str, int] | None = None
    pinned = load_pinned_copy_mode()
    if pinned is not None:
        git_sha = None
        entrypoint_pins = dict(pinned["files"])
        pins_source_commit = pinned["head"]
        cam_pin_spec.bind_pinned_copy_trust(pinned["root"])
        trust_blobs = dict(pinned["trust_blobs"])
    else:
        git_sha = _script_git_sha()
        entrypoint_pins, pins_source_commit = load_entrypoint_pins(git_sha=git_sha)
        try:
            trust_blobs = cam_pin_spec.require_committed_trust()
        except cam_pin_spec.CamPinError as exc:
            _refuse(exc.field, exc.expected, exc.actual)
    evidence: dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "checkpoint_id": None,
        "script_git_sha": git_sha,
        "script_sha256": (
            pinned["files"][PINNED_COPY_KICK_REL] if pinned is not None else _script_sha256()
        ),
        "entrypoint_pins": entrypoint_pins,
        "pins_source_commit": pins_source_commit,
        "kickoff_url": kickoff_url,
        "host": socket.gethostname(),
        "anchor_source": PIN_SOURCE,
        "evidence_path": str(evidence_path.resolve()),
        "checked_at": _utc_now(),
        "trust_blobs": trust_blobs,
        "head_sha": trust_blobs.get("HEAD"),
    }
    if pinned is not None:
        evidence["head"] = pinned["head"]
        evidence["pins_map_sha256"] = pinned["map_sha256"]
        evidence["pins_file_sha256"] = pinned["file_sha256"]
        evidence["pinned_copy_root"] = str(pinned["root"])
        evidence["script_git_sha_reason"] = PINNED_COPY_REASON

    def persist() -> None:
        write_evidence(evidence, evidence_path)

    try:
        persist()
        if type(run_id) is not str or not run_id:
            _refuse("run-id", "present", "missing")
        pin_bytes = _read_staged_v2_pin_bytes(pin_path)
        pin_record, _payload = _parse_staged_v2_pin_bytes(pin_bytes, run_id=run_id)
        try:
            cam_pin_spec.verify_code_pins_match(pin_record["code_pins"])
        except cam_pin_spec.CamPinError as exc:
            _refuse(exc.field, exc.expected, exc.actual)
        pin_commit = pin_record.get("git_commit")
        if pin_commit != pins_source_commit:
            _refuse("cam-pin.git_commit", pins_source_commit, pin_commit)
        run_private = _make_run_private_dir()
        _register_run_private_cleanup(run_private)
        staged = verify_and_stage(
            pack_dir,
            run_private=run_private,
            pin_record=pin_record,
            run_id=run_id,
            smoke=smoke,
            pin_bytes=pin_bytes,
        )
        evidence.update(staged)
        evidence["run_id"] = run_id
        evidence["checkpoint_id"] = None
        evidence["script_git_sha"] = git_sha
        evidence["script_sha256"] = evidence.get("script_sha256") or _script_sha256()
        evidence["entrypoint_pins"] = entrypoint_pins
        evidence["pins_source_commit"] = pins_source_commit
        evidence["kickoff_url"] = kickoff_url
        evidence["evidence_path"] = str(evidence_path.resolve())
        evidence["trust_blobs"] = trust_blobs
        evidence["head_sha"] = trust_blobs.get("HEAD")
        if pinned is not None:
            evidence["head"] = pinned["head"]
            evidence["entrypoint_pins"] = dict(pinned["files"])
            evidence["pins_map_sha256"] = pinned["map_sha256"]
            evidence["pins_file_sha256"] = pinned["file_sha256"]
            evidence["pinned_copy_root"] = str(pinned["root"])
            evidence["script_git_sha"] = None
            evidence["script_git_sha_reason"] = PINNED_COPY_REASON
            evidence["script_sha256"] = pinned["files"][PINNED_COPY_KICK_REL]
        if smoke:
            evidence["smoke"] = True
        persist()
        staged_paths = trainer_input_paths(run_private)
        evidence["paths"] = staged_paths
        evidence["staged_paths"] = dict(staged_paths)
        if "sha256_manifest" in evidence:
            _verify_manifest_copy(run_private, str(evidence["sha256_manifest"]))
        verified = _open_and_verify_trainer_inputs(evidence)
        manifest_sha = evidence.get("sha256_manifest")
        if type(manifest_sha) is str and len(manifest_sha) == SHA256_LEN:
            verified["manifest"] = _verify_manifest_copy(run_private, manifest_sha)
        sealed_fds = seal_verified_buffers(verified)
        fd_paths = trainer_fd_paths(sealed_fds)
        trainer_config = {"host": evidence["host"]}
        trainer_argv = build_trainer_argv(fd_paths)
        evidence["trainer_config"] = trainer_config
        persist()
        if not smoke:
            kick_event = {
                "run_id": run_id,
                "sha256_pack": evidence["computed_shas"]["sha256_pack"],
                "sha256_train": evidence["computed_shas"]["sha256_train"],
                "sha256_holdout": evidence["computed_shas"]["sha256_holdout"],
            }
            kick_event.update(_entrypoint_event_fields(evidence))
            _post_hq_event("kick", kick_event)
        hook_evidence = dict(evidence)
        hook_evidence.pop("trainer_argv", None)
        body = {
            "mode": "helper-ft-smoke" if smoke else "helper-ft",
            "pack_id": evidence["pack_id"],
            "sha256_pack": evidence["computed_shas"]["sha256_pack"],
            "sha256_train": evidence["computed_shas"]["sha256_train"],
            "sha256_holdout": evidence["computed_shas"]["sha256_holdout"],
            "expected_shas": dict(evidence["expected_shas"]),
            "pin": dict(evidence["pin"]),
            "run_private_dir": evidence["run_private_dir"],
            "paths": dict(staged_paths),
            "trainer_config": dict(trainer_config),
            "evidence": hook_evidence,
            "evidence_path": evidence["evidence_path"],
            "run_id": run_id,
            "checked_at": evidence["checked_at"],
        }
        if smoke:
            body["smoke"] = True
        with guard_trainer_fd_writes(fd_paths, evidence["pin"]):
            if kickoff is not None:
                hook_body = dict(body)
                result = kickoff(hook_body)
                if not isinstance(result, dict) or result.get("ok") is not True:
                    if isinstance(result, dict) and result.get("field"):
                        _refuse(result.get("field"), result.get("expected"), result.get("actual"))
                    _refuse("kickoff", "ok", result)
            else:
                result = post_kickoff(body, url=kickoff_url)
            launcher_ckpt = (
                result.get("checkpoint_id") if isinstance(result, dict) else None
            )
            if smoke:
                evidence["checkpoint_id"] = assigned_ckpt
                persist()
            elif launcher_ckpt:
                evidence["checkpoint_id"] = launcher_ckpt
                persist()
            exits: list[Mapping[str, Any]] = []
            exits.append(wait_for_training_exit(result if isinstance(result, dict) else None))
            captured = StringIO()
            evidence["paths"] = fd_paths
            with redirect_stdout(captured):
                if start_training is None:
                    started = _authorized_start_training(
                        run_private,
                        evidence,
                        log_path,
                        _gate=_GATE_OK,
                        sealed_fds=sealed_fds,
                        verified=verified,
                    )
                else:
                    started = start_training(run_private, evidence, log_path)
            trainer_stdout = captured.getvalue()
        if trainer_stdout:
            sys.stdout.write(trainer_stdout)
            sys.stdout.flush()
        spoofed = _trainer_stdout_is_spoofed(trainer_stdout)
        evidence["stdout_spoof"] = spoofed
        evidence["scorable"] = (not spoofed) and (not smoke)
        persist()
        exits.append(wait_for_training_exit(started if isinstance(started, dict) else None))
        exit_info = combine_trainer_exits(exits)
        host = socket.gethostname()
        record = rehash_held_fds(
            sealed_fds,
            pin=evidence["pin"],
            manifest_shas=evidence["manifest_shas"],
            host=host,
            refuse_on_mismatch=True,
        )
        apply_trainer_exit(record, exit_info)
        if smoke:
            record["smoke"] = True
        _apply_post_train_record(
            evidence,
            record,
            run_dir=run_dir,
            log_path=log_path,
            post_completion=not smoke,
        )
        if record["status"] != CHECKPOINT_MATCH:
            _refuse(record.get("field", "post_train"), record.get("expected"), record.get("actual"))
        if smoke:
            evidence["smoke"] = True
            evidence["scorable"] = False
            ckpt_dir = checkpoint_dir_for(run_dir, assigned_ckpt)
            forged = collect_forged_smoke_checkpoints(run_dir, ckpt_dir)
            forged_names = [path.name for path in forged]
            for extra in forged:
                _force_remove(extra)
            survivors = cleanup_smoke_artifacts(
                checkpoint_dir=ckpt_dir,
                run_private=run_private,
                inbox=pack_dir,
            )
            evidence["checkpoint_id"] = None
            evidence.pop("checkpoint_integrity_evidence_path", None)
            evidence["checkpoint_integrity_status"] = CHECKPOINT_UNSCORED
            leftover_forged = [
                path.name
                for path in collect_forged_smoke_checkpoints(run_dir, None)
                if os.path.lexists(path)
            ]
            if leftover_forged or any(os.path.lexists(path) for path in forged):
                leftover_forged = sorted(set(forged_names + leftover_forged))
                evidence["ok"] = False
                evidence["result"] = CHECKPOINT_REFUSED
                evidence["survivors"] = leftover_forged
                persist()
                _refuse("smoke.checkpoint_id", assigned_ckpt, leftover_forged)
            if forged_names:
                evidence["ok"] = False
                evidence["result"] = CHECKPOINT_REFUSED
                evidence["forged_checkpoints"] = forged_names
                persist()
                _refuse("smoke.checkpoint_id", assigned_ckpt, forged_names)
            if survivors:
                evidence["ok"] = False
                evidence["result"] = CHECKPOINT_REFUSED
                evidence["survivors"] = survivors
                persist()
                _refuse("smoke.cleanup", "nothing survives", survivors)
        persist()
        return evidence
    except KickRefused as exc:
        evidence["ok"] = False
        evidence["field"] = exc.field
        evidence["expected"] = exc.expected
        evidence["actual"] = exc.actual
        if smoke:
            evidence["smoke"] = True
            evidence["scorable"] = False
            ckpt_dir = None
            try:
                ckpt_dir = checkpoint_dir_for(run_dir, assigned_ckpt)
            except KickRefused:
                ckpt_dir = None
            for extra in collect_forged_smoke_checkpoints(run_dir, ckpt_dir):
                _force_remove(extra)
            survivors = cleanup_smoke_artifacts(
                checkpoint_dir=ckpt_dir,
                run_private=run_private,
                inbox=pack_dir,
            )
            evidence["checkpoint_id"] = None
            evidence.pop("checkpoint_integrity_evidence_path", None)
            evidence["checkpoint_integrity_status"] = CHECKPOINT_UNSCORED
            if survivors:
                evidence["survivors"] = survivors
        try:
            persist()
        except OSError:
            pass
        raise
    except content_uuid.ContentUuidError as exc:
        evidence["ok"] = False
        evidence["field"] = exc.field
        evidence["expected"] = exc.expected
        evidence["actual"] = exc.actual
        try:
            persist()
        except OSError:
            pass
        _refuse(exc.field, exc.expected, exc.actual)
    except RecursionError as exc:
        evidence["ok"] = False
        evidence["field"] = "content_uuid.too_deep"
        evidence["expected"] = f"depth <= {content_uuid.MAX_DEPTH}"
        evidence["actual"] = f"RecursionError: {exc}"
        try:
            persist()
        except OSError:
            pass
        _refuse(
            "content_uuid.too_deep",
            f"depth <= {content_uuid.MAX_DEPTH}",
            f"RecursionError: {exc}",
        )
    except Exception as exc:
        evidence["ok"] = False
        evidence["field"] = "kickoff"
        evidence["expected"] = "success"
        evidence["actual"] = f"{type(exc).__name__}: {exc}"
        try:
            persist()
        except OSError:
            pass
        _refuse("kickoff", "success", f"{type(exc).__name__}: {exc}")
    finally:
        if sealed_fds:
            for fd in sealed_fds.values():
                _close_quietly(fd)
        if run_private is not None:
            _force_remove(run_private)
            try:
                _CLEANUP_PATHS.remove(run_private)
            except ValueError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        type=Path,
        required=True,
        help="inbox pack directory (MANIFEST.json + curated_pack_v2*.jsonl)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="launcher-assigned run id; must match the staged v2 pin binding",
    )
    parser.add_argument(
        "--pin",
        default=None,
        help="staged v2 pin: path under FORGE_RUN_PRIVATE_ROOT or /proc/self/fd/N",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="run log path; evidence JSON is written in that run directory",
    )
    parser.add_argument(
        "--kickoff-url",
        default=DEFAULT_KICKOFF_URL,
        help="HELPER FT POST /train/kickoff URL (default 127.0.0.1:8765)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="explicit smoke mode: never post HQ events, unscorable, delete copies/inbox",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    try:
        if unknown:
            _refuse("argv", "known arguments only", unknown[0])
        evidence = kick(
            args.pack,
            run_id=args.run_id,
            pin_path=args.pin,
            log_path=args.log,
            kickoff_url=args.kickoff_url,
            smoke=bool(args.smoke),
        )
    except KickRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(evidence, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
