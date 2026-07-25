# Solo personal project, no connection to employer, built with public/free-tier only
"""CVE — dependency auditing against a CACHED OSV snapshot (openswap #29: Snyk/Dependabot).

Everything deterministic lives here: the manifest/lockfile readers
(requirements.txt, pyproject.toml, package.json, package-lock.json, uv.lock /
poetry.lock), PEP 440 and SemVer 2.0.0 ordering, the OSV `affected.ranges.events`
interval walk, CVSS v3 base-score arithmetic, and the rule pass that maps
findings onto the family diagnostic schema. The plugin CLI owns the ONE real I/O
call (reading local text files) and nothing else.

THE SNAPSHOT IS A FILE. Snyk and Dependabot are architecturally "give our
service your dependency graph and we will tell you"; deleting that call IS the
product. The vulnerability database is a JSON file you placed on disk out of
band, and this module only ever receives ALREADY-PARSED JSON. There is no fetch
path to disable at audit time because there is no fetch path at all, and the
manifest disables the network axis with an empty domain list so the claim is
falsifiable rather than a promise.

That architecture has an honest cost, and the code states it everywhere instead
of hiding it:
- A snapshot has an AGE. `snapshot_age` reports it, `cve:snapshot-stale` fails
  the gate past a caller-set bound, and a snapshot that declares no generation
  date yields `cve:snapshot-undated` — its age is unknown, and unknown is not
  fresh. A clean audit against a year-old file is not a clean dependency tree.
- Absence of a package from the snapshot is NOT proof it has no advisory. Every
  report counts `packages_without_records` and `cve:package-not-in-snapshot`
  exists (default-disabled, enable via the rules overlay) so the caller can see
  exactly which packages the snapshot said nothing about.

Honesty rules that shape the code:
- A dependency has EITHER a pinned `version` OR a `pin_reason`, never both,
  never neither. `requests>=2` has no version to audit; saying "clean" about it
  would be a fabricated verdict, so it becomes `cve:version-unpinned` naming the
  specifier that made the version undecidable.
- An advisory evaluation has EITHER `affected` (a bool) OR `error`, never both,
  never neither. An unparseable range boundary means the interval set is
  incomplete, so a missing `fixed` event can never be silently read as "still
  vulnerable" or as "clean" — it is `cve:advisory-unevaluable` with the reason.
- CVSS `score` and `rating` are separate readings, each value-XOR-error. A GHSA
  record that declares only `database_specific.severity: HIGH` gets a rating
  from that string and an ERROR on the score, because no vector means no
  computable base score.
- Line numbers are real or zero: requirements.txt is line oriented and carries
  true positions, while `json` and `tomllib` report no source offsets at all, so
  dependencies from JSON/TOML manifests carry line 0 rather than a guess.

Ecosystems are PyPI and npm ON PURPOSE, because those are the two whose version
ordering is implemented here. An OSV record for Maven or Go is COUNTED as
out-of-scope in the snapshot summary rather than half-matched with the wrong
comparator, and a `git+`/`file:`/`workspace:` dependency becomes
`cve:ecosystem-unsupported` instead of a name lookup that cannot mean anything.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from bigbang.core import openswap

try:  # tomllib is stdlib from 3.11; pyproject/lock support degrades, never crashes
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - this repo targets 3.11+
    tomllib = None

# ---- ecosystems -------------------------------------------------------------

ECO_PYPI = "PyPI"
ECO_NPM = "npm"
ECOSYSTEMS = (ECO_PYPI, ECO_NPM)

# OSV writes ecosystems as "PyPI", "npm", or "Alpine:v3.16" — the part before
# the colon is the ecosystem, the suffix is a distro release.
_ECO_ALIASES = {"pypi": ECO_PYPI, "npm": ECO_NPM}

SECONDS_PER_DAY = 86400.0

_PYPI_SEP_RE = re.compile(r"[-_.]+")


def canonical_ecosystem(raw: str | None) -> str | None:
    """OSV ecosystem string -> a supported ecosystem, or None when out of scope."""
    if not isinstance(raw, str):
        return None
    head = raw.split(":", 1)[0].strip().lower()
    return _ECO_ALIASES.get(head)


def normalize_name(name: str | None, ecosystem: str) -> str:
    """Package name in the form its ecosystem compares by.

    PyPI is PEP 503: runs of `-`, `_` and `.` collapse to one `-`, lowercased,
    so `Flask_Login` and `flask-login` are the same package. npm names are
    already lowercase-by-registry-rule and keep their `@scope/` prefix.
    """
    text = (name or "").strip()
    if ecosystem == ECO_PYPI:
        return _PYPI_SEP_RE.sub("-", text).lower()
    return text.lower()


# ---- PEP 440 ordering -------------------------------------------------------

_PEP440_RE = re.compile(
    r"^\s*v?"
    r"(?:(?P<epoch>[0-9]+)!)?"
    r"(?P<release>[0-9]+(?:\.[0-9]+)*)"
    r"(?:[-_.]?(?P<pre_l>alpha|beta|preview|pre|rc|a|b|c)[-_.]?(?P<pre_n>[0-9]+)?)?"
    r"(?:(?:-(?P<post_n1>[0-9]+))"
    r"|(?:[-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n2>[0-9]+)?))?"
    r"(?P<dev>[-_.]?dev[-_.]?(?P<dev_n>[0-9]+)?)?"
    r"(?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?\s*$",
    re.IGNORECASE,
)
# PEP 440 normalization of pre-release spellings; `a` < `b` < `rc` sorts right
# alphabetically, which is why the aliases resolve to those three letters.
_PRE_ALIASES = {"alpha": "a", "beta": "b", "c": "rc", "pre": "rc", "preview": "rc"}

# Sorts below every real version key, whatever the ecosystem: real keys start
# with a non-negative int (an epoch or a major), so one element decides it.
_MIN_KEY: tuple = (-1,)


def parse_pep440(version: str | None) -> tuple | None:
    """A PEP 440 version -> a sortable key, or None when this core cannot order it.

    None is a real answer meaning "unknown ordering". Callers must record WHY
    rather than guessing, because a mis-ordered version is a false clean.
    Implements epoch, release (trailing zeros normalized away so 1.0 == 1.0.0),
    pre/post/dev segments with their spelling aliases, and local versions.
    """
    if not isinstance(version, str):
        return None
    m = _PEP440_RE.match(version)
    if m is None:
        return None
    release = tuple(int(part) for part in m.group("release").split("."))
    while len(release) > 1 and release[-1] == 0:
        release = release[:-1]
    pre_l = (m.group("pre_l") or "").lower()
    has_post = m.group("post_n1") is not None or m.group("post_l") is not None
    post_n = int(m.group("post_n1") or m.group("post_n2") or 0)
    has_dev = m.group("dev") is not None
    if pre_l:
        pre_key: tuple = (0, _PRE_ALIASES.get(pre_l, pre_l), int(m.group("pre_n") or 0))
    elif has_dev and not has_post:
        pre_key = (-1, "", 0)  # 1.0.dev1 precedes 1.0a1 as well as 1.0
    else:
        pre_key = (1, "", 0)  # a final release outranks every pre-release
    local = m.group("local")
    if local is None:
        local_key: tuple = ((-1, 0, ""),)  # no local version sorts below any local
    else:
        local_key = tuple(
            (1, int(seg), "") if seg.isdigit() else (0, 0, seg.lower())
            for seg in re.split(r"[-_.]", local)
        )
    return (
        int(m.group("epoch") or 0),
        release,
        pre_key,
        (0, post_n) if has_post else (-1, 0),
        (0, int(m.group("dev_n") or 0)) if has_dev else (1, 0),
        local_key,
    )


# ---- SemVer 2.0.0 ordering --------------------------------------------------

_SEMVER_RE = re.compile(
    r"^\s*v?(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\.(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\s*$"
)


def parse_semver(version: str | None) -> tuple | None:
    """A SemVer 2.0.0 version -> a sortable key, or None when it is not semver.

    Build metadata is parsed and then DISCARDED from the key, which is what the
    spec requires: 1.0.0+build.1 and 1.0.0+build.2 have equal precedence.
    A present pre-release always sorts below the same version without one.
    """
    if not isinstance(version, str):
        return None
    m = _SEMVER_RE.match(version)
    if m is None:
        return None
    pre = m.group("pre")
    if pre is None:
        pre_rank, pre_ids = 1, ()
    else:
        pre_rank = 0
        pre_ids = tuple(
            (0, int(ident), "") if ident.isdigit() else (1, 0, ident)
            for ident in pre.split(".")
        )
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
        pre_rank,
        pre_ids,
    )


_VERSION_PARSERS = {ECO_PYPI: parse_pep440, ECO_NPM: parse_semver}
VERSION_SCHEMES = {ECO_PYPI: "PEP 440", ECO_NPM: "SemVer 2.0.0"}


def version_key(version: str | None, ecosystem: str) -> tuple | None:
    """Sortable key for a version in its ecosystem's scheme, or None."""
    parser = _VERSION_PARSERS.get(ecosystem)
    return parser(version) if parser is not None else None


def compare_versions(left: str, right: str, ecosystem: str) -> int | None:
    """-1/0/1 for left vs right, or None when either side cannot be ordered."""
    a = version_key(left, ecosystem)
    b = version_key(right, ecosystem)
    if a is None or b is None:
        return None
    if a < b:
        return -1
    return 1 if a > b else 0


# ---- dependency records -----------------------------------------------------


def dependency(
    *,
    name: str,
    ecosystem: str | None,
    specifier: str,
    version: str | None,
    pin_reason: str | None,
    field: str,
    line: int = 0,
    extras: str = "",
    marker: str = "",
) -> dict[str, Any]:
    """One declared dependency: `version` XOR `pin_reason`, never both/neither.

    `name` keeps its declared spelling; `key` is the normalized lookup name.
    `line` is a true source line for line-oriented manifests and 0 for JSON/TOML,
    because neither `json` nor `tomllib` reports source positions and a guessed
    position is worse than an absent one.
    """
    if (version is None) == (pin_reason is None):
        raise ValueError(
            f"{name}: a dependency needs exactly one of version / pin_reason "
            f"(got version={version!r}, pin_reason={pin_reason!r})"
        )
    return {
        "name": name,
        "key": normalize_name(name, ecosystem) if ecosystem else name.strip().lower(),
        "ecosystem": ecosystem,
        "specifier": specifier,
        "version": version,
        "pin_reason": pin_reason,
        "field": field,
        "line": int(line),
        "extras": extras,
        "marker": marker,
    }


# ---- requirements.txt -------------------------------------------------------

# pip treats `#` as a comment at line start or after whitespace, so an inline
# `egg=name#sha` fragment survives while a trailing note does not.
_COMMENT_RE = re.compile(r"(?:^|\s)#")
_REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[^\]]*)\])?"
    r"\s*(?P<spec>[^;]*?)"
    r"\s*(?:;\s*(?P<marker>.*))?$"
)
# Options that name MORE requirements living in a file this pass did not read.
_INCLUDE_OPTS = ("-r", "--requirement", "-c", "--constraint")
# Options that configure pip itself and carry no dependency information.
_IGNORED_OPTS = (
    "-i", "--index-url", "--extra-index-url", "--find-links", "-f",
    "--trusted-host", "--no-binary", "--only-binary", "--pre",
    "--prefer-binary", "--use-pep517", "--no-deps", "--require-hashes",
)


def _strip_comment(line: str) -> str:
    m = _COMMENT_RE.search(line)
    return line[: m.start()] if m else line


def _join_continuations(text: str) -> list[tuple[int, str]]:
    """(line number of the first physical line, logical line) pairs."""
    out: list[tuple[int, str]] = []
    pending: list[str] = []
    start = 0
    for number, raw in enumerate((text or "").splitlines(), start=1):
        body = _strip_comment(raw).rstrip()
        if not pending:
            start = number
        if body.endswith("\\"):
            pending.append(body[:-1])
            continue
        pending.append(body)
        out.append((start, " ".join(part.strip() for part in pending).strip()))
        pending = []
    if pending:  # a trailing backslash with nothing after it
        out.append((start, " ".join(part.strip() for part in pending).strip()))
    return out


def pypi_pin(specifier: str) -> tuple[str | None, str | None]:
    """(pinned version, why there is none) for a PEP 440 specifier set — XOR.

    Only `==X` / `===X` with no wildcard pins a version. `>=2.0` admits every
    later release, `==2.*` admits a whole series, and `~=2.1` admits 2.x — none
    of them names the version that is actually installed, so none of them can be
    audited without inventing the answer.
    """
    spec = (specifier or "").strip()
    if not spec:
        return None, "no version specifier at all, so the installed version is unknown"
    pins: list[str] = []
    loose: list[str] = []
    for clause in spec.split(","):
        part = clause.strip()
        if not part:
            continue
        if part.startswith("==="):
            pins.append(part[3:].strip())
        elif part.startswith("=="):
            candidate = part[2:].strip()
            if candidate.endswith(".*") or "*" in candidate:
                loose.append(part)
            else:
                pins.append(candidate)
        else:
            loose.append(part)
    unique = sorted(set(pins))
    if len(unique) > 1:
        return None, f"conflicting pins {', '.join(unique)} cannot both be installed"
    if unique:
        return unique[0], None
    return None, f"specifier {spec!r} is a range, not a pin"


_NPM_RANGE_HINTS = (
    ("^", "a caret range admits every compatible later release"),
    ("~", "a tilde range admits later patch releases"),
    (">", "an open lower bound admits every later release"),
    ("<", "an open upper bound names no single version"),
    ("||", "an alternation admits more than one version"),
    (" - ", "a hyphen range admits an interval"),
    ("x", "an x-range admits a whole series"),
    ("*", "a wildcard admits every version"),
)
_NPM_NON_REGISTRY = ("file:", "link:", "git", "http", "workspace:", "npm:", "portal:")


def npm_pin(specifier: str) -> tuple[str | None, str | None]:
    """(pinned version, why there is none) for an npm version range — XOR.

    Only an exact version (optionally written `=1.2.3`) pins. Everything else,
    including a protocol reference like `file:` or `git+https`, has no registry
    version this snapshot could be keyed by.
    """
    spec = (specifier or "").strip()
    if not spec:
        return None, "empty version range, so the installed version is unknown"
    low = spec.lower()
    for prefix in _NPM_NON_REGISTRY:
        if low.startswith(prefix):
            return None, f"{spec!r} is a {prefix} reference, not a registry version"
    if low in ("latest", "next", "*", "", "x"):
        return None, f"dist-tag/wildcard {spec!r} names no fixed version"
    exact = spec[1:].strip() if spec.startswith("=") else spec
    if parse_semver(exact) is not None:
        return exact, None
    for token, why in _NPM_RANGE_HINTS:
        if token in spec:
            return None, f"{spec!r}: {why}"
    return None, f"{spec!r} is not an exact semver version"


_PINNERS = {ECO_PYPI: pypi_pin, ECO_NPM: npm_pin}


def exact_pin(version: str, ecosystem: str) -> tuple[str | None, str | None]:
    """Treat `version` as an exact pin and validate it — (version, why not), XOR.

    The `cve match` path: a caller naming a single installed version still goes
    through the ecosystem's own pin rule, so `2.*` or `^1.0` typed at the CLI is
    refused with the same reason a manifest would get instead of being matched
    as if it were a literal version string.
    """
    text = (version or "").strip()
    if ecosystem == ECO_PYPI:
        return pypi_pin(f"=={text}" if text else "")
    pinner = _PINNERS.get(ecosystem)
    if pinner is None:
        return None, f"ecosystem {ecosystem!r} has no pin rule in this core"
    return pinner(text)


def parse_requirements(text: str, *, field: str = "requirements") -> dict[str, Any]:
    """A requirements.txt / .in body -> dependencies + notes. Never raises."""
    deps: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for line, logical in _join_continuations(text):
        body = re.sub(r"--hash=\S+", "", logical).strip()
        if not body:
            continue
        head = body.split()[0]
        if head in _INCLUDE_OPTS:
            notes.append(
                {
                    "kind": "unresolved-include",
                    "line": line,
                    "detail": f"{body!r} points at another requirements file that "
                    "this pass did not read, so its dependencies were NOT audited",
                }
            )
            continue
        if head in ("-e", "--editable"):
            notes.append(
                {
                    "kind": "ecosystem-unsupported",
                    "line": line,
                    "detail": f"{body!r} is an editable/local install with no "
                    "registry version to look up",
                }
            )
            continue
        if head.startswith("-"):
            notes.append(
                {
                    "kind": "option-ignored",
                    "line": line,
                    "detail": f"{head!r} is a pip option, not a dependency"
                    + ("" if head in _IGNORED_OPTS else " (unrecognized)"),
                }
            )
            continue
        deps.append(_requirement_dep(body, line, field, notes))
    return {
        "kind": "requirements.txt",
        "ecosystem": ECO_PYPI,
        "dependencies": [d for d in deps if d is not None],
        "notes": notes,
        "error": None,
    }


def _requirement_dep(
    body: str, line: int, field: str, notes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if "@" in body and not body.lstrip().startswith("@"):
        name, _, target = body.partition("@")
        if name.strip() and not name.strip().endswith(("=", "<", ">", "!", "~")):
            return dependency(
                name=name.split("[")[0].strip(),
                ecosystem=ECO_PYPI,
                specifier=f"@ {target.strip()}",
                version=None,
                pin_reason=f"direct URL reference to {target.strip()[:60]!r} "
                "carries no PyPI version",
                field=field,
                line=line,
            )
    m = _REQ_RE.match(body)
    if m is None:
        notes.append(
            {
                "kind": "unparsed-line",
                "line": line,
                "detail": f"{body[:60]!r} is not a PEP 508 requirement this core reads",
            }
        )
        return None
    version, reason = pypi_pin(m.group("spec") or "")
    return dependency(
        name=m.group("name"),
        ecosystem=ECO_PYPI,
        specifier=(m.group("spec") or "").strip(),
        version=version,
        pin_reason=reason,
        field=field,
        line=line,
        extras=(m.group("extras") or "").strip(),
        marker=(m.group("marker") or "").strip(),
    )


# ---- pyproject.toml / TOML locks -------------------------------------------

_NO_TOMLLIB = (
    "tomllib is unavailable on this interpreter (stdlib from Python 3.11), so "
    "TOML manifests cannot be parsed and were NOT audited"
)


def _load_toml(text: str) -> tuple[dict | None, str | None]:
    if tomllib is None:
        return None, _NO_TOMLLIB
    try:
        return tomllib.loads(text or ""), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _empty(kind: str, ecosystem: str | None, error: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "ecosystem": ecosystem,
        "dependencies": [],
        "notes": [],
        "error": error,
    }


def parse_pyproject(text: str) -> dict[str, Any]:
    """[project] PEP 621 deps + optional-dependencies + poetry's own table."""
    data, error = _load_toml(text)
    if data is None:
        return _empty("pyproject.toml", ECO_PYPI, error or "TOML could not be parsed")
    deps: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    for spec in project.get("dependencies") or []:
        _append_pep508(deps, notes, str(spec), "project.dependencies")
    optional = project.get("optional-dependencies")
    for group, specs in (optional.items() if isinstance(optional, dict) else []):
        for spec in specs or []:
            _append_pep508(deps, notes, str(spec), f"project.optional-dependencies.{group}")
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry")
    if isinstance(poetry, dict):
        _poetry_deps(poetry, deps, notes)
    return {
        "kind": "pyproject.toml",
        "ecosystem": ECO_PYPI,
        "dependencies": deps,
        "notes": notes,
        "error": None,
    }


def _append_pep508(
    deps: list[dict[str, Any]], notes: list[dict[str, Any]], spec: str, field: str
) -> None:
    dep = _requirement_dep(spec.strip(), 0, field, notes)
    if dep is not None:
        deps.append(dep)


_POETRY_OPERATORS = "<>=!,"


def poetry_pin(constraint: str) -> tuple[str | None, str | None]:
    """(pinned version, why there is none) for a Poetry constraint — XOR.

    Poetry's own dialect: a BARE version string is an exact requirement, while
    `^1.2` / `~1.2` / `*` are ranges. Anything carrying a PEP 440 operator is
    handed to the standard specifier rule so `>=1,<2` is refused for the same
    stated reason it would be refused in a requirements file.
    """
    raw = (constraint or "").strip()
    if not raw:
        return None, "poetry constraint is empty, so the installed version is unknown"
    if raw.startswith(("^", "~")):
        return None, f"poetry constraint {raw!r} is a range, not a pin"
    if "*" in raw:
        return None, f"poetry constraint {raw!r} is a wildcard, not a pin"
    if any(op in raw for op in _POETRY_OPERATORS):
        return pypi_pin(raw)
    return pypi_pin(f"=={raw}")  # a bare version is an exact requirement in Poetry


def _poetry_deps(
    poetry: dict[str, Any], deps: list[dict[str, Any]], notes: list[dict[str, Any]]
) -> None:
    """Poetry declares deps as name -> constraint (or a table with `version`)."""
    table = poetry.get("dependencies")
    for name, raw in (table.items() if isinstance(table, dict) else []):
        if name.lower() == "python":
            continue  # the interpreter constraint is not a PyPI package
        if isinstance(raw, dict):
            raw = raw.get("version") or ""
        if not isinstance(raw, str):
            notes.append(
                {
                    "kind": "unparsed-line",
                    "line": 0,
                    "detail": f"tool.poetry.dependencies.{name} is not a version string",
                }
            )
            continue
        version, reason = poetry_pin(raw)
        deps.append(
            dependency(
                name=name,
                ecosystem=ECO_PYPI,
                specifier=raw,
                version=version,
                pin_reason=reason,
                field="tool.poetry.dependencies",
            )
        )


def parse_python_lock(text: str, *, kind: str = "python-lock") -> dict[str, Any]:
    """uv.lock / poetry.lock: `[[package]]` tables with name + resolved version."""
    data, error = _load_toml(text)
    if data is None:
        return _empty(kind, ECO_PYPI, error or "TOML could not be parsed")
    deps: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for entry in data.get("package") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        raw = entry.get("version")
        if not name:
            continue
        if not isinstance(raw, str) or not raw.strip():
            notes.append(
                {
                    "kind": "unparsed-line",
                    "line": 0,
                    "detail": f"lock entry {name!r} declares no resolved version",
                }
            )
            continue
        deps.append(
            dependency(
                name=name,
                ecosystem=ECO_PYPI,
                specifier=f"=={raw}",
                version=raw.strip(),
                pin_reason=None,
                field="package",
            )
        )
    return {
        "kind": kind,
        "ecosystem": ECO_PYPI,
        "dependencies": deps,
        "notes": notes,
        "error": None,
    }


# ---- package.json / package-lock.json --------------------------------------

_NPM_FIELDS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)


def _load_json(text: str) -> tuple[Any, str | None]:
    import json

    try:
        return json.loads(text or ""), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def parse_package_json(text: str) -> dict[str, Any]:
    """package.json dependency tables. Ranges stay ranges — see npm_pin."""
    data, error = _load_json(text)
    if not isinstance(data, dict):
        return _empty(
            "package.json", ECO_NPM, error or "package.json is not a JSON object"
        )
    deps: list[dict[str, Any]] = []
    for field in _NPM_FIELDS:
        table = data.get(field)
        if not isinstance(table, dict):
            continue
        for name, raw in table.items():
            spec = raw if isinstance(raw, str) else ""
            version, reason = npm_pin(spec)
            deps.append(
                dependency(
                    name=str(name),
                    ecosystem=ECO_NPM,
                    specifier=spec,
                    version=version,
                    pin_reason=reason,
                    field=field,
                )
            )
    return {
        "kind": "package.json",
        "ecosystem": ECO_NPM,
        "dependencies": deps,
        "notes": [],
        "error": None,
    }


def parse_package_lock(text: str) -> dict[str, Any]:
    """package-lock.json v1 `dependencies` or v2/v3 `packages` — resolved versions.

    A lockfile is the ONLY npm input that can produce a verdict, because it is
    the only one that names the version that is actually installed.
    """
    data, error = _load_json(text)
    if not isinstance(data, dict):
        return _empty(
            "package-lock.json", ECO_NPM, error or "package-lock.json is not a JSON object"
        )
    deps: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for path, entry in packages.items():
            name = _lock_name(str(path))
            if name:
                _append_locked(deps, notes, name, entry, "packages")
    legacy = data.get("dependencies")
    if isinstance(legacy, dict) and not isinstance(packages, dict):
        _walk_legacy_lock(legacy, deps, notes)
    return {
        "kind": "package-lock.json",
        "ecosystem": ECO_NPM,
        "dependencies": deps,
        "notes": notes,
        "error": None,
        "lockfile_version": data.get("lockfileVersion"),
    }


def _lock_name(path: str) -> str:
    """`node_modules/@scope/pkg` -> `@scope/pkg`; "" for the root project entry.

    The lockfile's `""` key is the project itself, not one of its dependencies,
    and nested `a/node_modules/b` keys name b — the LAST segment after the final
    `node_modules/` is the package.
    """
    marker = "node_modules/"
    idx = path.rfind(marker)
    return path[idx + len(marker) :] if idx >= 0 else ""


def _append_locked(
    deps: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    name: str,
    entry: Any,
    field: str,
) -> None:
    raw = entry.get("version") if isinstance(entry, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        notes.append(
            {
                "kind": "unparsed-line",
                "line": 0,
                "detail": f"locked entry {name!r} declares no resolved version",
            }
        )
        return
    version, reason = npm_pin(raw.strip())
    deps.append(
        dependency(
            name=name,
            ecosystem=ECO_NPM,
            specifier=raw.strip(),
            version=version,
            pin_reason=reason,
            field=field,
        )
    )


def _walk_legacy_lock(
    table: dict[str, Any], deps: list[dict[str, Any]], notes: list[dict[str, Any]]
) -> None:
    for name, entry in table.items():
        _append_locked(deps, notes, str(name), entry, "dependencies")
        nested = entry.get("dependencies") if isinstance(entry, dict) else None
        if isinstance(nested, dict):
            _walk_legacy_lock(nested, deps, notes)


# ---- manifest dispatch ------------------------------------------------------

_KIND_PARSERS = {
    "requirements.txt": parse_requirements,
    "pyproject.toml": parse_pyproject,
    "package.json": parse_package_json,
    "package-lock.json": parse_package_lock,
    "python-lock": parse_python_lock,
}
# Names a directory walk recognizes. requirements*.txt and *.in are matched by
# pattern, everything else by exact file name.
MANIFEST_NAMES = (
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "uv.lock",
    "poetry.lock",
)


def manifest_kind(filename: str) -> str | None:
    """Which parser owns this file name, or None when nothing here reads it."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in ("uv.lock", "poetry.lock"):
        return "python-lock"
    if name in _KIND_PARSERS:
        return name
    if name.startswith("requirements") and name.endswith((".txt", ".in")):
        return "requirements.txt"
    if name.endswith(".txt") and "requirements" in name:
        return "requirements.txt"
    return None


def parse_manifest(text: str, filename: str) -> dict[str, Any]:
    """Dispatch on the file NAME; content is never sniffed. Never raises."""
    kind = manifest_kind(filename)
    if kind is None:
        return _empty(
            "unknown",
            None,
            f"{filename!r} is not a manifest this core reads "
            f"(expected requirements*.txt or one of {', '.join(MANIFEST_NAMES)})",
        )
    parser = _KIND_PARSERS[kind]
    if kind == "python-lock":
        return parser(text, kind="python-lock")
    return parser(text)


# ---- CVSS v3 base score -----------------------------------------------------

# CVSS v3.1 specification, section 7.1 metric weights. Privileges Required is
# scope-dependent, which is why it is a nested table.
_CVSS_WEIGHTS: dict[str, dict[str, float]] = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PR_WEIGHTS = {
    "U": {"N": 0.85, "L": 0.62, "H": 0.27},
    "C": {"N": 0.85, "L": 0.68, "H": 0.5},
}
_CVSS_REQUIRED = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")
# 0.0 is "None"; the bands come from the CVSS v3.1 qualitative severity scale.
_RATING_BANDS = ((9.0, "critical"), (7.0, "high"), (4.0, "medium"), (0.1, "low"))
RATING_ORDER = ("critical", "high", "medium", "low", "none")


def parse_cvss_vector(vector: str | None) -> dict[str, str] | None:
    """A CVSS v3.x base vector -> its metrics, or None when it is not one.

    Only v3.0/v3.1 base metrics are understood. A v2 or v4 vector returns None
    so the caller reports "no score computable" with the version named, rather
    than scoring it with the wrong formula.
    """
    if not isinstance(vector, str):
        return None
    parts = [p for p in vector.strip().split("/") if p]
    if not parts or parts[0].upper() not in ("CVSS:3.0", "CVSS:3.1"):
        return None
    metrics: dict[str, str] = {}
    for part in parts[1:]:
        key, _, value = part.partition(":")
        if key and value:
            metrics[key.strip().upper()] = value.strip().upper()
    if any(k not in metrics for k in _CVSS_REQUIRED):
        return None
    if metrics["S"] not in _PR_WEIGHTS:
        return None
    if metrics["PR"] not in _PR_WEIGHTS[metrics["S"]]:
        return None
    for key, table in _CVSS_WEIGHTS.items():
        if metrics[key] not in table:
            return None
    return metrics


def _roundup(value: float) -> float:
    """CVSS v3.1 Appendix A roundup: ceiling to one decimal, float-noise safe."""
    scaled = round(value * 100000)  # round() of one arg is already an int
    if scaled % 10000 == 0:
        return scaled / 100000.0
    return (scaled // 10000 + 1) / 10.0


def cvss_base_score(metrics: dict[str, str]) -> float:
    """CVSS v3.1 base score from validated base metrics (0.0 - 10.0)."""
    impact_sub = 1.0 - (
        (1.0 - _CVSS_WEIGHTS["C"][metrics["C"]])
        * (1.0 - _CVSS_WEIGHTS["I"][metrics["I"]])
        * (1.0 - _CVSS_WEIGHTS["A"][metrics["A"]])
    )
    changed = metrics["S"] == "C"
    if changed:
        impact = 7.52 * (impact_sub - 0.029) - 3.25 * (impact_sub - 0.02) ** 15
    else:
        impact = 6.42 * impact_sub
    if impact <= 0:
        return 0.0
    exploitability = (
        8.22
        * _CVSS_WEIGHTS["AV"][metrics["AV"]]
        * _CVSS_WEIGHTS["AC"][metrics["AC"]]
        * _PR_WEIGHTS[metrics["S"]][metrics["PR"]]
        * _CVSS_WEIGHTS["UI"][metrics["UI"]]
    )
    total = impact + exploitability
    if changed:
        total *= 1.08
    return _roundup(min(total, 10.0))


def cvss_rating(score: float) -> str:
    """CVSS v3.1 qualitative band for a base score."""
    for floor, name in _RATING_BANDS:
        if score >= floor:
            return name
    return "none"


def _reading(value: Any, error: str | None, **extra: Any) -> dict[str, Any]:
    """One measurement: EITHER `value` OR `error`, never both, never neither."""
    if (value is None) == (error is None):
        raise ValueError(f"reading needs exactly one of value/error: {value!r} {error!r}")
    return {"value": value, "error": error, **extra}


def advisory_severity(record: dict[str, Any]) -> dict[str, Any]:
    """{"score": reading, "rating": reading} for one OSV record.

    Two independent readings on purpose. A GHSA export commonly carries a
    textual `database_specific.severity` and no vector at all: the rating is then
    real and the score is an ERROR naming the absence, because a base score
    that was not computed from a vector would be invented.
    """
    vectors = []
    for entry in record.get("severity") or []:
        if isinstance(entry, dict) and entry.get("score"):
            vectors.append((str(entry.get("type") or "?"), str(entry["score"])))
    score: dict[str, Any] | None = None
    for kind, raw in vectors:
        metrics = parse_cvss_vector(raw)
        if metrics is not None:
            value = cvss_base_score(metrics)
            score = _reading(value, None, source=f"severity[{kind}]", vector=raw)
            break
    if score is None:
        detail = (
            f"declared severity vectors {[k for k, _ in vectors]} are not CVSS v3"
            if vectors
            else "advisory declares no severity vector"
        )
        score = _reading(None, f"no CVSS v3 base score computable: {detail}", source=None, vector=None)
    declared = ((record.get("database_specific") or {}).get("severity") or "")
    if score["value"] is not None:
        rating = _reading(
            cvss_rating(score["value"]), None, source="computed from the CVSS v3 vector"
        )
    elif str(declared).strip().lower() in RATING_ORDER:
        rating = _reading(
            str(declared).strip().lower(), None, source="database_specific.severity"
        )
    else:
        rating = _reading(
            None,
            "no CVSS vector and no recognized database_specific.severity, so this "
            "advisory carries no severity rating",
            source=None,
        )
    return {"score": score, "rating": rating}


# ---- OSV snapshot -----------------------------------------------------------

SNAPSHOT_SCHEMA = "osv-snapshot/1"


class SnapshotError(ValueError):
    """The snapshot on disk is not a shape this core can index."""


def _records_of(obj: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Accept {"advisories": [...]} with metadata, or a bare list of OSV records."""
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)], {}
    if not isinstance(obj, dict):
        raise SnapshotError(
            "snapshot must be a JSON object with an 'advisories' list, or a bare "
            f"JSON list of OSV records (got {type(obj).__name__})"
        )
    for key in ("advisories", "vulns", "records"):
        raw = obj.get(key)
        if isinstance(raw, list):
            meta = {k: v for k, v in obj.items() if k != key}
            return [r for r in raw if isinstance(r, dict)], meta
    raise SnapshotError(
        "snapshot object has no 'advisories' (or 'vulns'/'records') list — nothing "
        "to index, and an empty index would read as a clean audit"
    )


def load_snapshot(obj: Any) -> dict[str, Any]:
    """Index ALREADY-PARSED snapshot JSON by (ecosystem, normalized name).

    Pure: this function never opens a file and never opens a socket. The CLI
    reads the bytes; this decides what they mean. Records for ecosystems this
    core cannot order are COUNTED, not silently dropped, because "0 advisories"
    and "400 advisories we ignored" are different facts.
    """
    records, meta = _records_of(obj)
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    out_of_scope: dict[str, int] = {}
    withdrawn = 0
    unusable = 0
    for record in records:
        affected = record.get("affected")
        if not isinstance(affected, list) or not affected:
            unusable += 1
            continue
        if record.get("withdrawn"):
            withdrawn += 1
        placed = False
        out_of_scope_here = False
        for block in affected:
            package = block.get("package") if isinstance(block, dict) else None
            if not isinstance(package, dict):
                continue
            eco = canonical_ecosystem(package.get("ecosystem"))
            if eco is None:
                raw = str(package.get("ecosystem") or "?").split(":", 1)[0]
                out_of_scope[raw] = out_of_scope.get(raw, 0) + 1
                out_of_scope_here = True
                continue
            name = normalize_name(str(package.get("name") or ""), eco)
            if not name:
                continue
            bucket = index.setdefault((eco, name), [])
            if record not in bucket:
                bucket.append(record)
            placed = True
        if not placed and not out_of_scope_here:
            unusable += 1
    return {
        "meta": meta,
        "index": index,
        "counts": {
            "records": len(records),
            "packages": len(index),
            "withdrawn": withdrawn,
            "unusable": unusable,
            "out_of_scope_ecosystems": dict(sorted(out_of_scope.items())),
        },
    }


def parse_timestamp(text: Any) -> float | None:
    """RFC3339 / ISO-8601 -> POSIX seconds, or None when it is not a timestamp."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


_DATE_KEYS = ("generated", "generated_at", "modified", "date", "snapshot_date")


def snapshot_age(meta: dict[str, Any], now_ts: float) -> dict[str, Any]:
    """How old the snapshot claims to be: `age_days` XOR `error`.

    An undated snapshot is the dangerous case — it looks exactly like a fresh
    one in every report — so the age is an ERROR naming the absence, and the
    rule pass turns that into cve:snapshot-undated rather than assuming today.
    """
    declared = None
    key_used = None
    for key in _DATE_KEYS:
        value = (meta or {}).get(key)
        if isinstance(value, str) and value.strip():
            declared, key_used = value.strip(), key
            break
    if declared is None:
        return {
            "generated": None,
            "key": None,
            "age_days": None,
            "error": "snapshot declares no generation date "
            f"(looked for {', '.join(_DATE_KEYS)}), so its age is unknown",
        }
    stamp = parse_timestamp(declared)
    if stamp is None:
        return {
            "generated": declared,
            "key": key_used,
            "age_days": None,
            "error": f"{key_used}={declared!r} is not an RFC3339 timestamp, so the "
            "snapshot age could not be computed",
        }
    return {
        "generated": declared,
        "key": key_used,
        "age_days": round((now_ts - stamp) / SECONDS_PER_DAY, 2),
        "error": None,
    }


# ---- OSV range evaluation ---------------------------------------------------

_EVENT_RANK = {"introduced": 0, "fixed": 1, "last_affected": 1}


def range_intervals(rng: dict[str, Any], ecosystem: str) -> tuple[list[dict], list[str]]:
    """OSV events -> affected intervals, plus every reason they are incomplete.

    Events are sorted by version, with `introduced` ranked before a boundary at
    the SAME version so `introduced: 1.2` + `fixed: 1.2` is the empty interval
    it means, while `introduced: 1.2` + `last_affected: 1.2` includes 1.2.
    A boundary that cannot be ordered is a PROBLEM, never a dropped event: a
    missing `fixed` would turn a patched version into a false positive.
    """
    parsed: list[tuple[tuple, int, str, str]] = []
    problems: list[str] = []
    for event in rng.get("events") or []:
        if not isinstance(event, dict) or not event:
            problems.append(f"event {event!r} is not a single-key object")
            continue
        for kind, raw in event.items():
            text = str(raw).strip()
            if kind not in _EVENT_RANK:
                problems.append(f"event kind {kind!r} (={text!r}) is not supported here")
                continue
            if kind == "introduced" and text == "0":
                parsed.append((_MIN_KEY, 0, kind, text))
                continue
            key = version_key(text, ecosystem)
            if key is None:
                problems.append(
                    f"{kind} boundary {text!r} is not a valid "
                    f"{VERSION_SCHEMES.get(ecosystem, ecosystem)} version"
                )
                continue
            parsed.append((key, _EVENT_RANK[kind], kind, text))
    intervals: list[dict] = []
    open_intro: tuple[tuple, str] | None = None
    for key, _rank, kind, text in sorted(parsed, key=lambda e: (e[0], e[1])):
        if kind == "introduced":
            if open_intro is None:
                open_intro = (key, text)
            continue
        start = open_intro if open_intro is not None else (_MIN_KEY, "0")
        intervals.append(
            {
                "introduced": start[0],
                "introduced_raw": start[1],
                "end": key,
                "end_raw": text,
                "inclusive": kind == "last_affected",
            }
        )
        open_intro = None
    if open_intro is not None:
        intervals.append(
            {
                "introduced": open_intro[0],
                "introduced_raw": open_intro[1],
                "end": None,
                "end_raw": None,
                "inclusive": False,
            }
        )
    return intervals, problems


def _interval_contains(interval: dict, key: tuple) -> bool:
    if key < interval["introduced"]:
        return False
    if interval["end"] is None:
        return True
    return key <= interval["end"] if interval["inclusive"] else key < interval["end"]


def evaluate_block(
    block: dict[str, Any], version: str, ecosystem: str
) -> dict[str, Any]:
    """One `affected` entry vs one version: `affected` bool XOR `error`."""
    key = version_key(version, ecosystem)
    if key is None:
        return _reading(
            None,
            f"version {version!r} is not a valid "
            f"{VERSION_SCHEMES.get(ecosystem, ecosystem)} version",
            evidence=None,
        )
    listed = [str(v) for v in (block.get("versions") or []) if isinstance(v, (str, int))]
    for candidate in listed:
        if version_key(candidate, ecosystem) == key:
            return _reading(True, None, evidence=f"listed in affected.versions as {candidate!r}")
    ranges = [r for r in (block.get("ranges") or []) if isinstance(r, dict)]
    usable = [r for r in ranges if canonical_range_type(r, ecosystem)]
    if not ranges and not listed:
        return _reading(
            None,
            "affected entry declares neither ranges nor versions, so it cannot be "
            "evaluated against a version",
            evidence=None,
        )
    if ranges and not usable:
        kinds = sorted({str(r.get("type") or "?") for r in ranges})
        return _reading(
            None,
            f"affected ranges are typed {', '.join(kinds)}, which this core cannot "
            f"order for {ecosystem}",
            evidence=None,
        )
    problems: list[str] = []
    for rng in usable:
        intervals, issues = range_intervals(rng, ecosystem)
        if issues:
            # A range with an unreadable boundary decides NOTHING. Using its
            # surviving events would be the exact false positive this module
            # promises not to produce: drop a `fixed` event and every later
            # release falls inside an interval that now looks unbounded. Erring
            # toward "unknown" can downgrade a true hit to unevaluable, which
            # the operator sees; the other direction is a fabricated verdict.
            problems.extend(issues)
            continue
        for interval in intervals:
            if _interval_contains(interval, key):
                bound = (
                    "unbounded (no fixed release in this range)"
                    if interval["end"] is None
                    else f"{'through' if interval['inclusive'] else 'before'} "
                    f"{interval['end_raw']}"
                )
                return _reading(
                    True,
                    None,
                    evidence=f"introduced {interval['introduced_raw']}, affected {bound}",
                    fixed=None if interval["inclusive"] else interval["end_raw"],
                )
    if problems:
        return _reading(
            None,
            "affected range is incomplete, so no verdict is possible: "
            + "; ".join(dict.fromkeys(problems[:3])),
            evidence=None,
        )
    if usable:
        return _reading(
            False, None, evidence=f"outside all {len(usable)} declared affected range(s)"
        )
    return _reading(False, None, evidence=f"not among the {len(listed)} listed version(s)")


def canonical_range_type(rng: dict[str, Any], ecosystem: str) -> bool:
    """Can this range's type be ordered with the ecosystem's comparator?

    OSV `SEMVER` and `ECOSYSTEM` both mean "compare with the ecosystem's own
    scheme" for PyPI and npm. `GIT` ranges are commit hashes and carry no
    version ordering at all, so they are refused rather than approximated.
    """
    kind = str(rng.get("type") or "").strip().upper()
    if kind in ("ECOSYSTEM", ""):
        return True
    return kind == "SEMVER" and ecosystem in (ECO_NPM, ECO_PYPI)


def evaluate_advisory(
    record: dict[str, Any], *, name: str, version: str, ecosystem: str
) -> dict[str, Any]:
    """One advisory vs one pinned version. `affected` bool XOR `error`.

    A definite hit wins over an undecidable sibling block (the evidence stands
    on its own), but a single undecidable block is enough to refuse a "clean"
    verdict — that refusal is the whole point.

    A WITHDRAWN record is refused before any matching happens: the database has
    retracted it, so it asserts nothing about any version, and reporting
    `affected: true` from a retraction is a false positive. It becomes a
    no-verdict reading whose error names the withdrawal date, which is why the
    withdrawn count and the vulnerable count can never double-count the same row.
    """
    blocks = [
        b
        for b in (record.get("affected") or [])
        if isinstance(b, dict)
        and canonical_ecosystem((b.get("package") or {}).get("ecosystem")) == ecosystem
        and normalize_name(str((b.get("package") or {}).get("name") or ""), ecosystem) == name
    ]
    result: dict[str, Any] = {
        "id": str(record.get("id") or "?"),
        "aliases": [str(a) for a in (record.get("aliases") or [])],
        "summary": str(record.get("summary") or record.get("details") or "")[:200],
        "withdrawn": record.get("withdrawn") or None,
        "modified": record.get("modified") or None,
        "severity": advisory_severity(record),
        "affected": None,
        "error": None,
        "evidence": None,
        "fixed": None,
    }
    if result["withdrawn"]:
        result["error"] = (
            f"advisory {result['id']} was WITHDRAWN on {result['withdrawn']}, so it "
            "asserts nothing about any version and was not evaluated"
        )
        return result
    if not blocks:
        result["error"] = (
            f"advisory {result['id']} has no affected entry for {ecosystem} "
            f"package {name!r}, so it could not be evaluated"
        )
        return result
    errors: list[str] = []
    for block in blocks:
        reading = evaluate_block(block, version, ecosystem)
        if reading["value"] is True:
            result["affected"] = True
            result["evidence"] = reading["evidence"]
            result["fixed"] = reading.get("fixed")
            return result
        if reading["value"] is None:
            errors.append(str(reading["error"]))
    if errors:
        result["error"] = "; ".join(errors[:3])
        return result
    result["affected"] = False
    result["evidence"] = f"not matched by any of {len(blocks)} affected entry/entries"
    return result


def advisories_for(snapshot: dict[str, Any], dep: dict[str, Any]) -> list[dict[str, Any]]:
    """Every indexed advisory for this dependency's (ecosystem, normalized name)."""
    if not dep.get("ecosystem"):
        return []
    return list((snapshot.get("index") or {}).get((dep["ecosystem"], dep["key"]), []))


# ---- rules (policy-as-config) ----------------------------------------------

RULES: dict[str, dict[str, Any]] = {
    # A pinned version inside a declared affected range. `map_rating` lets the
    # advisory's own CVSS band pick the severity; the `severity` here is the
    # fallback used when the advisory declares no rating at all.
    "cve:vulnerable": {"enabled": True, "severity": "error", "map_rating": True},
    "cve:advisory-withdrawn": {"enabled": True, "severity": "info"},
    "cve:advisory-unevaluable": {"enabled": True, "severity": "warning"},
    "cve:version-unpinned": {"enabled": True, "severity": "warning"},
    "cve:version-unparseable": {"enabled": True, "severity": "warning"},
    # Default OFF: on a real tree it fires for almost every package and would
    # bury the findings. It exists because absence from a snapshot is NOT proof
    # of safety, and an auditor who wants that list should be able to get it.
    "cve:package-not-in-snapshot": {"enabled": False, "severity": "info"},
    "cve:ecosystem-unsupported": {"enabled": True, "severity": "info"},
    "cve:unresolved-include": {"enabled": True, "severity": "info"},
    "cve:manifest-unparseable": {"enabled": True, "severity": "error"},
    # Not about a package: a file that was not READ has not been audited, and it
    # must never leave the gate looking clean.
    "cve:manifest-unreadable": {"enabled": True, "severity": "error"},
    # Not about a package either: these are about the SNAPSHOT, and a clean
    # audit against a stale or undated database is not a clean dependency tree.
    "cve:snapshot-stale": {"enabled": True, "severity": "error"},
    "cve:snapshot-undated": {"enabled": True, "severity": "warning"},
}

RATING_SEVERITY = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "suggestion",
    "none": "info",
}


def load_rules(path: Any = None) -> dict[str, dict[str, Any]]:
    """RULES with an optional JSON overlay (org policy needs no code edit).

    Overlay shape: {"cve:version-unpinned": {"severity": "error"}, ...}. An
    unknown rule id or a bad severity is a hard error — silently ignoring a typo
    in a policy file would mean shipping a gate that does not gate.
    """
    import json
    from pathlib import Path

    merged = {rid: dict(cfg) for rid, cfg in RULES.items()}
    if path is None:
        return merged
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("rules overlay must be a JSON object of rule -> settings")
    for rid, cfg in raw.items():
        if rid not in merged:
            raise ValueError(f"unknown rule id {rid!r} (see: scout cve rules)")
        if not isinstance(cfg, dict):
            raise ValueError(f"rule {rid!r}: settings must be a JSON object")
        sev = cfg.get("severity")
        if sev is not None and sev not in openswap.SEVERITIES:
            raise ValueError(
                f"rule {rid!r}: severity must be one of {'|'.join(openswap.SEVERITIES)}"
            )
        merged[rid].update(cfg)
    return merged


class _Emitter:
    """Rule-gated diagnostic collector — keeps the audit functions short."""

    def __init__(self, rules: dict[str, dict[str, Any]], path: str) -> None:
        self.rules = rules
        self.path = path
        self.diagnostics: list[dict[str, Any]] = []

    def add(
        self,
        rule: str,
        message: str,
        *,
        line: int = 0,
        col: int = 1,
        suggestion: str | None = None,
        severity: str | None = None,
    ) -> None:
        cfg = self.rules.get(rule) or {}
        if not cfg.get("enabled", True):
            return
        self.diagnostics.append(
            openswap.diagnostic(
                path=self.path,
                line=line,
                col=col,
                rule=rule,
                severity=severity or cfg.get("severity", "warning"),
                message=message,
                suggestion=suggestion,
            )
        )

    def severity_for(self, rule: str, rating: str | None) -> tuple[str, str]:
        """(severity, why) for a finding whose advisory may carry a CVSS band."""
        cfg = self.rules.get(rule) or {}
        default = cfg.get("severity", "warning")
        if not cfg.get("map_rating") or rating is None:
            return default, (
                f"severity {default} from the rule table"
                if rating is None
                else f"severity {default} pinned by policy (map_rating off)"
            )
        mapped = RATING_SEVERITY.get(rating, default)
        return mapped, f"severity {mapped} from the advisory CVSS band {rating}"


# ---- the audit --------------------------------------------------------------

SCOPE_LIMITS = (
    "the vulnerability database is a CACHED FILE, never fetched: findings are only "
    "as current as the snapshot, absence of a package from it is not proof the "
    "package is safe, and only PyPI and npm are ordered (PEP 440 / SemVer 2.0.0). "
    "A dependency without an exact pin gets no verdict at all — it is reported as "
    "cve:version-unpinned with the specifier that made it undecidable, because a "
    "range cannot say which version is installed"
)


def audit_dependency(
    dep: dict[str, Any], snapshot: dict[str, Any], emitter: _Emitter
) -> dict[str, Any]:
    """One dependency -> its per-advisory findings, with every unknown labelled."""
    out: dict[str, Any] = {
        "name": dep["name"],
        "key": dep["key"],
        "ecosystem": dep["ecosystem"],
        "specifier": dep["specifier"],
        "version": dep["version"],
        "field": dep["field"],
        "line": dep["line"],
        "advisories": [],
        "checked": False,
        "skipped": None,
    }
    where = f"{dep['name']} ({dep['field']})"
    if dep["ecosystem"] not in ECOSYSTEMS:
        out["skipped"] = f"ecosystem {dep['ecosystem']!r} is not audited by this core"
        emitter.add(
            "cve:ecosystem-unsupported",
            f"{where}: {out['skipped']}",
            line=dep["line"],
        )
        return out
    if dep["version"] is None:
        out["skipped"] = dep["pin_reason"]
        emitter.add(
            "cve:version-unpinned",
            f"{where} was NOT checked: {dep['pin_reason']}",
            line=dep["line"],
            suggestion="pin an exact version (or audit the lockfile) so a verdict "
            "is possible; a range cannot be matched against an advisory",
        )
        return out
    if version_key(dep["version"], dep["ecosystem"]) is None:
        out["skipped"] = (
            f"pinned version {dep['version']!r} is not a valid "
            f"{VERSION_SCHEMES[dep['ecosystem']]} version"
        )
        emitter.add(
            "cve:version-unparseable",
            f"{where} was NOT checked: {out['skipped']}",
            line=dep["line"],
        )
        return out
    out["checked"] = True
    records = advisories_for(snapshot, dep)
    if not records:
        emitter.add(
            "cve:package-not-in-snapshot",
            f"{where} {dep['version']}: this snapshot holds no advisory for the "
            "package, which is not the same as the package being safe",
            line=dep["line"],
        )
        return out
    for record in records:
        out["advisories"].append(_report_advisory(record, dep, emitter, where))
    return out


def _report_advisory(
    record: dict[str, Any], dep: dict[str, Any], emitter: _Emitter, where: str
) -> dict[str, Any]:
    verdict = evaluate_advisory(
        record, name=dep["key"], version=str(dep["version"]), ecosystem=dep["ecosystem"]
    )
    if verdict["withdrawn"]:
        emitter.add(
            "cve:advisory-withdrawn",
            f"{where} {dep['version']}: advisory {verdict['id']} was WITHDRAWN on "
            f"{verdict['withdrawn']} and was NOT matched — it counts as neither a "
            "vulnerability nor a clean check",
            line=dep["line"],
        )
        return verdict
    if verdict["error"] is not None:
        emitter.add(
            "cve:advisory-unevaluable",
            f"{where} {dep['version']} vs {verdict['id']}: {verdict['error']}",
            line=dep["line"],
            suggestion="no verdict was recorded for this advisory — treat it as "
            "unknown, not as clean",
        )
        return verdict
    if verdict["affected"]:
        rating = verdict["severity"]["rating"]["value"]
        severity, why = emitter.severity_for("cve:vulnerable", rating)
        score = verdict["severity"]["score"]["value"]
        band = f"CVSS {score} ({rating})" if score is not None else (
            f"severity {rating}" if rating else "no severity declared"
        )
        emitter.add(
            "cve:vulnerable",
            f"{where} {dep['version']} is affected by {verdict['id']} [{band}]: "
            f"{verdict['evidence']}",
            line=dep["line"],
            severity=severity,
            suggestion=(
                f"upgrade to {verdict['fixed']} or later"
                if verdict["fixed"]
                else "no fixed version is declared in this advisory — check upstream"
            ),
        )
        verdict["severity_used"] = why
    return verdict


_COUNT_KEYS = (
    "dependencies",
    "checked",
    "unpinned",
    "unparseable",
    "unsupported",
    "with_records",
    "packages_without_records",
    "vulnerable",
    "unevaluable",
    "withdrawn",
)


def audit_manifest(
    parsed: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    path: str,
    rules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One parsed manifest + one snapshot -> a report. Pure; opens nothing."""
    emitter = _Emitter(rules or load_rules(), path)
    if parsed.get("error"):
        emitter.add(
            "cve:manifest-unparseable",
            f"manifest not audited: {parsed['error']}",
            suggestion="check the file syntax and name",
        )
        return {
            "path": path,
            "kind": parsed.get("kind"),
            "ecosystem": parsed.get("ecosystem"),
            "unreadable": parsed["error"],
            "counts": None,
            "dependencies": [],
            "notes": [],
            "diagnostics": openswap.sort_diagnostics(emitter.diagnostics),
        }
    for note in parsed.get("notes") or []:
        rule = {
            "unresolved-include": "cve:unresolved-include",
            "ecosystem-unsupported": "cve:ecosystem-unsupported",
        }.get(note["kind"])
        if rule:
            emitter.add(rule, note["detail"], line=note.get("line", 0))
    rows = [audit_dependency(dep, snapshot, emitter) for dep in parsed["dependencies"]]
    counts = dict.fromkeys(_COUNT_KEYS, 0)
    counts["dependencies"] = len(rows)
    for row in rows:
        hits = row["advisories"]
        counts["checked"] += 1 if row["checked"] else 0
        counts["with_records"] += 1 if hits else 0
        counts["packages_without_records"] += 1 if row["checked"] and not hits else 0
        # Every advisory row lands in exactly ONE of these three buckets, so
        # vulnerable + unevaluable + withdrawn + clean == len(advisories).
        counts["vulnerable"] += sum(1 for a in hits if a["affected"] is True)
        counts["withdrawn"] += sum(1 for a in hits if a["withdrawn"])
        counts["unevaluable"] += sum(
            1 for a in hits if a["error"] is not None and not a["withdrawn"]
        )
        if not row["checked"]:
            if row["ecosystem"] not in ECOSYSTEMS:
                counts["unsupported"] += 1
            elif row["version"] is not None:
                counts["unparseable"] += 1  # pinned, but not an orderable version
            else:
                counts["unpinned"] += 1
    return {
        "path": path,
        "kind": parsed.get("kind"),
        "ecosystem": parsed.get("ecosystem"),
        "unreadable": None,
        "counts": counts,
        "dependencies": rows,
        "notes": parsed.get("notes") or [],
        "diagnostics": openswap.sort_diagnostics(emitter.diagnostics),
    }


def unreadable_report(
    path: str, error: str, *, rules: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """A manifest that could not be READ is not a manifest that passed.

    `counts` is None rather than a row of zeros: zero dependencies is a
    measurement, and no measurement was taken.
    """
    emitter = _Emitter(rules or load_rules(), path)
    emitter.add(
        "cve:manifest-unreadable",
        f"could not read the file, so no dependency was audited: {error}",
        suggestion="check the path, permissions and encoding",
    )
    return {
        "path": path,
        "kind": manifest_kind(path),
        "ecosystem": None,
        "unreadable": error,
        "counts": None,
        "dependencies": [],
        "notes": [],
        "diagnostics": emitter.diagnostics,
    }


def snapshot_diagnostics(
    age: dict[str, Any],
    *,
    snapshot_path: str,
    max_age_days: float | None,
    rules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Findings about the DATABASE, so a clean tree cannot hide a stale cache."""
    emitter = _Emitter(rules or load_rules(), snapshot_path)
    if age.get("error") is not None:
        emitter.add(
            "cve:snapshot-undated",
            f"snapshot age is unknown: {age['error']}",
            suggestion=f"add a '{_DATE_KEYS[0]}' RFC3339 timestamp to the snapshot "
            "so staleness can be gated",
        )
    elif max_age_days is not None and age["age_days"] > max_age_days:
        emitter.add(
            "cve:snapshot-stale",
            f"snapshot was generated {age['generated']} — {age['age_days']} days "
            f"old, over the {max_age_days} day bound, so a clean result here does "
            "not mean the tree is clean today",
            suggestion="refresh the OSV export out of band and re-run",
        )
    return emitter.diagnostics


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals across manifests. Unread files are counted as unread, not as zeros."""
    totals = dict.fromkeys(_COUNT_KEYS, 0)
    audited = 0
    unreadable = 0
    for report in reports:
        counts = report.get("counts")
        if counts is None:
            unreadable += 1
            continue
        audited += 1
        for key in _COUNT_KEYS:
            totals[key] += int(counts.get(key, 0))
    return {
        "manifests": len(reports),
        "manifests_audited": audited,
        "manifests_unreadable": unreadable,
        "totals": totals,
    }
