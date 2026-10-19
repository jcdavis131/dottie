"""Deterministic veto pre-filter for System One ``POST /decide``.

Pure function: no network, no files, no config, no env kill-switch. The veto
can only add a halt. It never returns ``execute`` and never weakens a halt.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Rule ids. Frozen names: tests and the /decide body both quote these.
PIPE_DOWNLOAD_TO_SHELL = "pipe_download_to_shell"
FORK_BOMB = "fork_bomb"
CONTROL_PLANE = "control_plane"
RM_RF = "rm_rf"
MKFS = "mkfs"

VETO_RULES: tuple[str, ...] = (
    PIPE_DOWNLOAD_TO_SHELL,
    FORK_BOMB,
    CONTROL_PLANE,
    RM_RF,
    MKFS,
)

_FETCHERS = frozenset({"curl", "wget", "fetch"})
_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "python", "python3", "perl"})
_DECODERS = frozenset({"base64"})
_CONTROL_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "0.0.0.0",
        "::1",
        "[::1]",
        "nugatron",
    }
)
_CONTROL_PORTS = frozenset({"8770", "8765", "8769"})
_ADMIN_PATHS = frozenset({"/reload", "/admin", "/admin/reload", "/swap", "/train/kickoff"})

_WRAPPER_RE = re.compile(
    r"^(?:"
    r"sudo(?:\s+-E)?|"
    r"doas|"
    r"nice(?:\s+-n\s+\S+)?|"
    r"nohup|"
    r"time|"
    r"stdbuf(?:\s+\S+)*|"
    r"command(?:\s+-p)?|"
    r"builtin|"
    r"exec|"
    r"env(?:\s+[A-Za-z_][\w]*=\S+)*"
    r")\s+"
)
_ABSBIN_RE = re.compile(
    r"(?:^|(?<=[\s;|&(`]))(?:/(?:usr(?:/local)?/)?s?bin/)([\w.+-]+)"
)
_IFS_RE = re.compile(r"\$\{?IFS\}?")
_STATEMENT_RE = re.compile(r"\s*(?:&&|\|\||;)\s*")
_HTTP_METHOD_RE = re.compile(
    r"\b(?:get|post|put|delete|patch|head|options)\b.{0,80}/(?:reload|admin|swap|train/kickoff)\b",
    re.IGNORECASE | re.DOTALL,
)
_URL_RE = re.compile(
    r"(?:https?://)?(?P<host>127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\]|::1|nugatron|"
    r"[\w.-]+\.ts\.net|[\w.-]+\.tailscale\.net)"
    r"(?::(?P<port>8770|8765|8769))?(?P<path>/reload|/admin(?:/reload)?|/swap|/train/kickoff)\b",
    re.IGNORECASE,
)
_PORT_PATH_RE = re.compile(
    r":(?P<port>8770|8765|8769)(?P<path>/reload|/admin(?:/reload)?|/swap|/train/kickoff)\b",
    re.IGNORECASE,
)
_TAILNET_RE = re.compile(r"(?:^|[\s@/])[\w.-]+\.(?:ts\.net|tailscale\.net)(?::(?:8770|8765|8769))?(?:/reload|/admin)", re.I)
_FORK_COMPACT_RE = re.compile(r"([:/\w.]+)\(\)\{(?:\1\|\1&?)+\};\1")
_CLASSIC_FORK = ":(){:|:&};:"
_PROC_SUBST_RE = re.compile(
    r"(?:(?:bash|sh|zsh|dash|ksh)\s+)?<\(\s*(?:curl|wget|fetch)\b",
    re.IGNORECASE,
)
_INTERP_C_FETCH_RE = re.compile(
    r"\b(?:bash|sh|zsh|dash|ksh|python3?|perl)\s+(?:-c|-e)\s*[\"']?\$\(\s*(?:curl|wget|fetch)\b",
    re.IGNORECASE,
)
_EVAL_FETCH_RE = re.compile(
    r"\beval\b.{0,200}\b(?:curl|wget|fetch)\b",
    re.IGNORECASE | re.DOTALL,
)
_EVAL_SUBST_FETCH_RE = re.compile(
    r"\beval\b\s+\$\(\s*(?:curl|wget|fetch)\b",
    re.IGNORECASE,
)
_CMD_SUBST_FETCH_RE = re.compile(
    r"(?:^|[\s;|&\"'])\$\(\s*(?:curl|wget|fetch)\b",
    re.IGNORECASE,
)
_BACKTICK_FETCH_RE = re.compile(
    r"(?:^|[\s;|&])`\s*(?:curl|wget|fetch)\b",
    re.IGNORECASE,
)
_EVAL_BACKTICK_FETCH_RE = re.compile(
    r"\beval\b.{0,80}`\s*(?:curl|wget|fetch)\b",
    re.IGNORECASE | re.DOTALL,
)
_FETCH_PIPE_INTERP_RE = re.compile(
    r"\b(?:curl|wget|fetch)\b[^;&]{0,400}\|\s*(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|python3?|perl)\b",
    re.IGNORECASE | re.DOTALL,
)


def extract_strings(value: Any) -> list[str]:
    """Flatten a JSON-like payload into text the veto can scan."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(extract_strings(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            out.extend(extract_strings(item))
        if parts:
            out.append(" ".join(parts))
        return out
    return []


def _strip_wrappers(cmd: str) -> str:
    text = cmd.strip()
    while True:
        match = _WRAPPER_RE.match(text)
        if match is None:
            break
        text = text[match.end() :]
    if text.startswith("eval "):
        text = text[5:].strip()
    return text


def normalize_command(text: str) -> str:
    """Collapse quoting, wrappers, IFS, and absolute bin paths. No I/O."""
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.replace("\\\n", " ").replace("\\\r\n", " ")
    folded = _IFS_RE.sub(" ", folded)
    folded = folded.replace("\\", " ")
    folded = folded.replace("'", " ").replace('"', " ")
    folded = _ABSBIN_RE.sub(r"\1", folded)
    folded = re.sub(r"[()]", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip().lower()
    return _strip_wrappers(folded)


def _first_token(stage: str) -> str:
    stage = _strip_wrappers(stage.strip().lower())
    if not stage:
        return ""
    return stage.split()[0]


def _flag_letters(tokens: list[str]) -> tuple[set[str], set[str]]:
    letters: set[str] = set()
    longs: set[str] = set()
    for tok in tokens:
        if tok == "--":
            break
        if not tok.startswith("-") or tok == "-":
            break
        if tok.startswith("--"):
            longs.add(tok)
            continue
        letters.update(tok[1:])
    return letters, longs


def _is_rm_rf(statement: str) -> bool:
    tokens = _strip_wrappers(statement).split()
    if not tokens or tokens[0] != "rm":
        return False
    letters, longs = _flag_letters(tokens[1:])
    recursive = "r" in letters or "R" in letters or "--recursive" in longs
    force = "f" in letters or "--force" in longs
    return recursive and force


def _is_mkfs(statement: str) -> bool:
    token = _first_token(statement)
    return token == "mkfs" or token.startswith("mkfs.")


def _pipe_download(statement: str, original: str) -> bool:
    if _FETCH_PIPE_INTERP_RE.search(original) or _FETCH_PIPE_INTERP_RE.search(statement):
        return True
    if _PROC_SUBST_RE.search(original) or _PROC_SUBST_RE.search(statement):
        return True
    if _INTERP_C_FETCH_RE.search(original) or _INTERP_C_FETCH_RE.search(statement):
        return True
    if _EVAL_FETCH_RE.search(original) or _EVAL_SUBST_FETCH_RE.search(statement):
        return True
    if _EVAL_BACKTICK_FETCH_RE.search(original):
        return True
    orig_stripped = original.strip()
    if _CMD_SUBST_FETCH_RE.search(orig_stripped) or _BACKTICK_FETCH_RE.search(orig_stripped):
        # $(curl) / `curl` as the command itself, or feeding an interpreter.
        head = _strip_wrappers(orig_stripped)
        if head.startswith("$(") or head.startswith("`"):
            return True
        if re.match(r"(?:bash|sh|zsh|dash|ksh|python3?|perl|eval)\b", head):
            return True
    stages = [_strip_wrappers(part) for part in statement.split("|")]
    if len(stages) < 2:
        return False
    heads = [_first_token(stage) for stage in stages]
    has_fetch = any(head in _FETCHERS for head in heads)
    has_decode = False
    for stage, head in zip(stages, heads, strict=False):
        if head in _DECODERS and re.search(r"(?:-d|--decode)\b", stage):
            has_decode = True
    has_interp = any(head in _INTERPRETERS for head in heads)
    return bool((has_fetch or has_decode) and has_interp)


def _control_plane(text: str) -> bool:
    if _HTTP_METHOD_RE.search(text):
        return True
    match = _URL_RE.search(text)
    if match:
        host = match.group("host").lower()
        port = match.group("port")
        path = match.group("path").lower()
        tailnet = host.endswith(".ts.net") or host.endswith(".tailscale.net")
        if path in _ADMIN_PATHS and (
            host in _CONTROL_HOSTS or tailnet or (port is not None and port in _CONTROL_PORTS)
        ):
            return True
    if _PORT_PATH_RE.search(text) or _TAILNET_RE.search(text):
        return True
    return False


def _fork_bomb(text: str, compact: str) -> bool:
    if _CLASSIC_FORK in compact:
        return True
    if _FORK_COMPACT_RE.search(compact):
        return True
    return False


def veto_command(command: str) -> str | None:
    """Return a veto rule id if ``command`` matches a halt class, else None.

    Never returns ``execute``. None means "no veto" (fall through to the model).
    """
    if not command or not command.strip():
        return None
    lowered = unicodedata.normalize("NFKC", command)
    compact = re.sub(r"\s+", "", lowered.lower())
    if _fork_bomb(lowered, compact):
        return FORK_BOMB
    normalized = normalize_command(command)
    if _control_plane(command) or _control_plane(normalized) or _control_plane(lowered):
        return CONTROL_PLANE
    statements = [s for s in _STATEMENT_RE.split(normalized) if s]
    if not statements:
        statements = [normalized]
    originals = [s for s in _STATEMENT_RE.split(lowered) if s] or [lowered]
    for statement, original in zip(statements, originals + [lowered] * len(statements), strict=False):
        if _is_rm_rf(statement):
            return RM_RF
        if _is_mkfs(statement):
            return MKFS
        if _pipe_download(statement, original):
            return PIPE_DOWNLOAD_TO_SHELL
    if _pipe_download(normalized, lowered):
        return PIPE_DOWNLOAD_TO_SHELL
    return None


def veto_from_payload(payload: Any) -> str | None:
    """Scan every string (and argv-joined lists) in a /decide payload."""
    texts = extract_strings(payload)
    for text in texts:
        rule = veto_command(text)
        if rule is not None:
            return rule
    if texts:
        return veto_command("\n".join(texts))
    return None


def strengthen_choice(model_choice: str | None, veto_rule: str | None) -> str | None:
    """Veto may only add a halt. A model halt stays a halt."""
    if veto_rule:
        return "halt"
    return model_choice


def halt_answer(question: dict[str, Any], rule: str) -> dict[str, Any]:
    """Schema-shaped answer. Never picks ``execute`` when another option exists."""
    qtype = question["type"]
    if qtype == "choice":
        keys = list(question["criteria"])
        if "halt" in question["criteria"]:
            pick = "halt"
        else:
            pick = next((key for key in keys if key != "execute"), keys[0])
        probs = {key: (1.0 if key == pick else 0.0) for key in keys}
        return {
            "type": "choice",
            "choice": pick,
            "probabilities": probs,
            "shape_concentration": 1.0,
            "veto_rule": rule,
        }
    if qtype == "score":
        n = len(question["criteria"])
        keys = [str(i) for i in range(n)]
        last = keys[-1]
        probs = {key: (1.0 if key == last else 0.0) for key in keys}
        return {
            "type": "score",
            "score": float(n - 1),
            "legend": {str(i): label for i, label in enumerate(question["criteria"])},
            "probabilities": probs,
            "shape_concentration": 1.0,
            "veto_rule": rule,
        }
    if qtype == "noul":
        return {"type": "noul", "noul": 0.0, "veto_rule": rule}
    impossible: str = qtype
    raise ValueError(f"unhandled question type {impossible!r}")


def veto_body(request: dict[str, Any], *, model: str, rule: str) -> dict[str, Any]:
    """A /decide response that is Choice=halt. Does not call a model."""
    answers = {qid: halt_answer(question, rule) for qid, question in request["questions"].items()}
    return {
        "schema": request["schema"],
        "model": model,
        "mode": "veto",
        "veto_rule": rule,
        "choice": "halt",
        "answers": answers,
    }
