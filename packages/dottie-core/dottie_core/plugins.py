# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Plugin registry: Models, Middleware, and Policies via entry points.

Clean-room principle: the core stays minimal and dependency-free. Everything
a contributor might want to swap — the decision function, a harness stage, the
policy engine — is a plugin. Plugins are discovered through the standard
``importlib.metadata`` entry-point mechanism (stdlib only), so any installed
package can extend Dottie without touching the core.

Entry-point groups (all under the ``dottie.`` namespace)::

    dottie.models      -> Model implementations (the decision function)
    dottie.middleware  -> Middleware stages (Callable[[RunContext], RunContext])
    dottie.policies    -> Policy factories (Callable[[], Policy])

A plugin author declares entry points in their own ``pyproject.toml``::

    [project.entry-points."dottie.models"]
    my-model = "my_package.module:MyModel"

and Dottie finds it with :func:`discover` / :func:`load`. For tests and
scripts that don't want to install a package, :func:`register` adds a plugin
to the in-process registry directly.

The registry never imports a plugin until :func:`load` is called — discovery
is cheap and side-effect free.
"""

from __future__ import annotations

import sys
from importlib import metadata
from typing import Any, Callable

#: Valid plugin kinds, matching the entry-point group suffixes.
KINDS = ("model", "middleware", "policy")

#: Entry-point group prefix. Full group is f"{GROUP_PREFIX}.{kind}s".
GROUP_PREFIX = "dottie"


def _group(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown plugin kind {kind!r}; expected one of {KINDS}")
    # "model" -> "dottie.models", "middleware" -> "dottie.middleware", ...
    return f"{GROUP_PREFIX}.{kind}s"


# In-process registry for programmatic registration (tests, scripts, REPL).
# Maps (kind, name) -> object or import path string.
_process_registry: dict[tuple[str, str], Any] = {}


def register(kind: str, name: str, plugin: Any) -> None:
    """Register a plugin in-process without installing a package.

    ``plugin`` may be the object itself (a Model instance, a middleware
    callable, a Policy factory) or a ``"module:attr"`` import path string
    resolved lazily at :func:`load` time.

    Overwrites any previous registration under the same (kind, name).
    Entry-point plugins are never overwritten by this — :func:`load` prefers
    the in-process registry, so ``register`` is how tests shadow real plugins.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown plugin kind {kind!r}; expected one of {KINDS}")
    if not name or not isinstance(name, str):
        raise ValueError("plugin name must be a non-empty string")
    _process_registry[(kind, name)] = plugin


def _resolve(spec: Any) -> Any:
    """Turn a plugin spec into the object: import "module:attr" strings."""
    if isinstance(spec, str) and ":" in spec:
        module_name, _, attr = spec.partition(":")
        module = __import__(module_name, fromlist=[attr])
        return getattr(module, attr)
    return spec


def discover(kind: str | None = None) -> dict[str, dict[str, metadata.EntryPoint]]:
    """List available plugins without importing them.

    Returns ``{kind: {name: entry_point}}`` (or just ``{name: entry_point}``
    for a single kind). Merges entry points from installed distributions with
    the in-process registry; in-process entries appear as pseudo entry points
    whose ``value`` is the registered object or import path.
    """
    kinds = (kind,) if kind else KINDS
    out: dict[str, dict[str, Any]] = {}
    for k in kinds:
        found: dict[str, Any] = {}
        # Installed distributions first (stdlib entry-point discovery).
        try:
            for ep in metadata.entry_points(group=_group(k)):
                found[ep.name] = ep
        except Exception:
            pass  # hostile/broken metadata must not break discovery
        # In-process registry shadows entry points of the same name.
        for (rk, name), plugin in _process_registry.items():
            if rk == k:
                found[name] = plugin
        out[k] = found
    if kind:
        return out[kind]
    return out


def load(kind: str, name: str) -> Any:
    """Load a plugin by kind and name. Imports it on first use.

    Raises :class:`KeyError` if no plugin is registered under (kind, name),
    :class:`ImportError` if its import path fails to resolve.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown plugin kind {kind!r}; expected one of {KINDS}")
    available = discover(kind)
    if name not in available:
        known = sorted(available) or "none"
        raise KeyError(
            f"no {kind} plugin named {name!r}; available: {known}. "
            f"Register one via entry points [{_group(kind)}] or plugins.register()."
        )
    spec = available[name]
    if isinstance(spec, metadata.EntryPoint):
        try:
            return spec.load()
        except Exception as exc:
            raise ImportError(f"failed to load {kind} plugin {name!r}: {exc}") from exc
    return _resolve(spec)


def clear_registry() -> None:
    """Drop all in-process registrations. Test helper; not for production."""
    _process_registry.clear()


__all__ = ["KINDS", "GROUP_PREFIX", "register", "discover", "load", "clear_registry"]
