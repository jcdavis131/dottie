"""SafetyPolicy — the gate the harness's function surface must pass through.

Why this module exists, stated plainly: the SPEC's first draft described
`sh()`, `edit_file()` and `rlm()` with NO confinement, NO approval hook, and
NO recursion cap. That is an unsupervised arbitrary-execution loop that can
also spawn copies of itself, and the review pass reproduced all three
consequences:

    rlm.py:330  200 successive spawn_child() calls, zero refusals, threads
                never pruned  -> unbounded fanout and depth
    rlm.py:164  sh("set") on Windows puts the entire environment -- including
                DOTTIE_RLM_API_KEY -- into the trajectory, and trajectories
                feed the PUBLIC gist status chain
    rlm.py:454  the injected closures hold `self`, so model-authored kernel
                code can reach the runtime and bypass scope checks

Defaults here are therefore RESTRICTIVE, and the permissive settings exist but
must be asked for by name:

    workspace_root        writes/edits confined to this tree (default: cwd)
    allow_shell=False     sh() refuses until enabled
    approval_hook=None    when set, called before every shell command and
                          every write; returning False refuses the action
    max_children=8        per-session concurrent-child cap
    max_depth=3           root -> child -> grandchild; deeper is refused
    scrub_env             names matching these patterns are removed from the
                          child environment of sh() AND redacted from output

None of this makes code execution safe in the abstract -- it makes the blast
radius declared, capped, and auditable, which is the difference between a tool
and an accident.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: Env names whose VALUES must never reach a trajectory, a log, or a child
#: process. Matched case-insensitively as substrings.
DEFAULT_SCRUB_PATTERNS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "API_KEY",
    "APIKEY",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "SESSION_KEY",
    "AUTH",
    "HF_",
    "OPENAI",
    "ANTHROPIC",
    "AWS_",
    "GH_",
    "GITHUB_",
)

REDACTED = "[REDACTED]"


class PolicyRefusal(RuntimeError):  # noqa: N818 - a refusal, not an error state
    """An action the policy declines. Carries an actionable reason.

    Named for what it IS: the policy working as designed, not a failure.
    """


@dataclass
class SafetyPolicy:
    workspace_root: Path = field(default_factory=Path.cwd)
    allow_shell: bool = False
    allow_writes_outside_workspace: bool = False
    approval_hook: Callable[[str, str], bool] | None = None
    max_children: int = 8
    max_depth: int = 3
    scrub_patterns: tuple[str, ...] = DEFAULT_SCRUB_PATTERNS
    max_output_chars: int = 20_000

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).resolve()

    # -- path confinement ---------------------------------------------------

    def resolve_in_workspace(self, path: str | Path) -> Path:
        """Resolve `path` and refuse if it escapes the workspace.

        Resolves BOTH sides (the symlink-escape lesson from bigbang's policy:
        comparing an unresolved target against a resolved root lets
        `workspace/link -> C:/Windows` through). os.path.realpath is
        non-strict, so this works for paths that do not exist yet.
        """
        target = Path(os.path.realpath(str(Path(path).expanduser())))
        root = Path(os.path.realpath(str(self.workspace_root)))
        if target == root:
            return target
        try:
            target.relative_to(root)
        except ValueError:
            if self.allow_writes_outside_workspace:
                return target
            raise PolicyRefusal(
                f"{target} is outside the workspace root {root}. Pass "
                f"allow_writes_outside_workspace=True to the policy if that is "
                f"genuinely intended."
            ) from None
        return target

    # -- approval -----------------------------------------------------------

    def require_approval(self, action: str, detail: str) -> None:
        hook = self.approval_hook
        if hook is None:
            return
        if not hook(action, detail):
            raise PolicyRefusal(f"{action} declined by approval hook: {detail}")

    # -- shell --------------------------------------------------------------

    def check_shell(self, cmd: str) -> None:
        if not self.allow_shell:
            raise PolicyRefusal(
                "sh() is disabled by policy. Construct the Runtime with a "
                "SafetyPolicy(allow_shell=True) to enable the shell surface."
            )
        self.require_approval("shell", cmd)

    def child_env(self) -> dict[str, str]:
        """os.environ minus every secret-shaped name.

        A child shell must not be able to print what it was never given.
        """
        return {k: v for k, v in os.environ.items() if not self.is_secret_name(k)}

    def is_secret_name(self, name: str) -> bool:
        up = name.upper()
        return any(p in up for p in self.scrub_patterns)

    def redact(self, text: str) -> str:
        """Replace any secret-shaped env VALUE appearing in `text`.

        Belt and braces: child_env() removes them from the child, but the
        parent process may still hold them and a model could echo one it read
        another way. Only values of length >= 8 are matched, so short or empty
        vars cannot blank out unrelated text.
        """
        if not text:
            return text
        out = text
        for name, value in os.environ.items():
            if not value or len(value) < 8:
                continue
            if self.is_secret_name(name) and value in out:
                out = out.replace(value, REDACTED)
        return out

    # -- sub-agents ---------------------------------------------------------

    def check_spawn(self, depth: int, live_children: int) -> None:
        if depth >= self.max_depth:
            raise PolicyRefusal(
                f"sub-agent depth {depth} would exceed max_depth={self.max_depth}; "
                f"this session is too deep to spawn another child."
            )
        if live_children >= self.max_children:
            raise PolicyRefusal(
                f"{live_children} children already live, cap is "
                f"max_children={self.max_children}; wait for one to finish."
            )


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def safe_component(name: str) -> str:
    """Validate a single path component (skill/memory names, session ids)."""
    if not name or not _SAFE_NAME.match(name) or name in {".", ".."}:
        raise PolicyRefusal(
            f"{name!r} is not a safe path component (letters, digits, dot, "
            f"underscore, dash only)"
        )
    return name
