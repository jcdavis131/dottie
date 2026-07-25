# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout a11y` — Siteimprove replacement, fully local (openswap #25).

Static accessibility auditing with the SaaS crawler deleted: img alt presence,
label/control association, heading order, landmark presence and WCAG 2.x
contrast ratios, computed on THIS box from files you already have. The ONE real
I/O call in this plugin is `Path.read_text` in _read_html; every judgment is
deterministic and lives in bigbang/core/a11y.py, so the whole audit is unit
testable with strings and no fixtures on disk.

Zero egress is the product, not a setting. Siteimprove's architecture is "our
crawler fetches your pages and the findings live on our servers", so the
manifest disables the network axis with an EMPTY domain list, and `detect` and
`check` both call _egress_guard first, which re-reads the manifest and REFUSES
to run if that section was ever widened. There is no enforce_or_raise call site
for the network axis because there is no outbound call to gate — the guard is
the inverse assertion, and it is what makes the claim falsifiable.

There is no native tier and there will not be one. axe-core CLI and pa11y are
the open checkers in this category and both drive a headless Chrome that fetches
the page and its subresources over the network; running one would reintroduce
the egress this adapter exists to delete, and would make the verdict depend on
PATH contents and someone's Chrome version (the links #4 doctrine: a gate whose
answer moves with PATH is flaky by construction). They are PROBED and surfaced
for awareness, never executed, and `detect` says so in `native_used` on every
tier rather than letting tier=native imply a binary was used.

Not a browser, and it says so: `SCOPE_LIMITS` ships in the payload of `check`
and `detect`. Only inline styles and the html/:root/body rules of <style> blocks
are resolved, so text coloured by a class, an @media block, a linked stylesheet
or JavaScript is reported as `a11y:contrast-unknown` WITH THE REASON. A stated
unknown is the honest output; a ratio computed against an assumed white
background would be a fabricated pass.

Deliberately NOT duplicated from `seo` (#3), which already crawls and audits
remote pages: single-h1 and page <title> stay seo's rules (they are SEO checks;
WCAG asks about heading ORDER and this plugin checks that instead), and the
alt-attribute overlap is the one place the two touch — seo counts missing alts
for a Screaming Frog export, this issues a per-image 1.1.1 verdict that honours
role=presentation, aria-hidden and placeholder alt text. See the core module
docstring for the full extend-vs-new-plugin reasoning.
"""

from __future__ import annotations

from pathlib import Path

import typer

from bigbang.core import a11y, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import load_manifest

FALLBACK_SCOPE = (
    "pure-stdlib html.parser + WCAG 2.x arithmetic is the complete product for "
    "this adapter: img alt presence (honouring role=presentation, aria-hidden "
    "and decorative alt=\"\"), label/control association (label[for], wrapping "
    "label, aria-label, aria-labelledby, title, button text), heading order and "
    "empty headings, landmark presence, duplicate ids, html lang, and contrast "
    "ratios from hex/rgb/keyword colors with the large-text rule; tier "
    "'fallback' is the expected steady state (Siteimprove is SaaS and the open "
    "checkers all drive a headless browser, so no local native binary is a "
    "superset of this offline core). What it does NOT do is layout: no cascade, "
    "no JavaScript, no rendered geometry"
)
INSTALL_HINT = (
    "nothing to install — the stdlib core is complete; axe-core CLI and pa11y "
    "are heavier browser-driven checkers to run by hand when you want a "
    "rendered-DOM second opinion (this plugin never executes them)"
)
NEVER_EXECUTED = (
    "axe/pa11y/tidy are probed for awareness and NEVER executed: they drive a "
    "headless browser that fetches the page over the network, which is the "
    "egress this adapter exists to delete, and their verdict would then vary "
    "with PATH contents and browser version"
)

app = make_plugin_app(
    "a11y",
    "Audit local HTML for accessibility (Siteimprove-class), fully local: "
    "alt text, label association, heading order, landmarks, WCAG 2.x contrast",
    examples=[
        "scout --json a11y check page.html",
        "scout --json a11y check site --fail-on error",
        "scout --json a11y contrast --fg '#767676' --bg white",
        "scout --json a11y rules",
        "scout --json a11y detect",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _egress_guard(command: str) -> dict:
    """Assert the manifest still declares ZERO egress, or refuse to run.

    The inverse of an enforce_or_raise call site: this plugin makes no outbound
    call, so the thing worth checking is that nobody widened the axis to allow
    one. A privacy guarantee that is only in a docstring is a promise; one that
    fails the command is a contract.
    """
    net = (_manifest().get("capabilities") or {}).get("network") or {}
    if net.get("enabled") or (net.get("domains") or []):
        fail_agent(
            "manifest declares network access for a plugin whose whole premise is "
            "zero egress — refusing to run until capabilities.network is disabled "
            "with an empty domain list",
            command=command,
            example="scout --json a11y detect",
        )
    return {"network_enabled": False, "domains": [], "reads": "local files only"}


def _capability() -> dict:
    # Siteimprove is SaaS with no local CLI, and every open checker in this
    # category (axe-core CLI, pa11y) drives a headless browser that fetches over
    # the network, so `native` stays a truthful probe that reports absent and
    # `native_used` is False on EVERY tier — tier=native must never be able to
    # imply that a binary produced these findings. tidy's -access checks are
    # surfaced for the same reason: real, local, and no contrast support at all.
    native = openswap.probe_binary("axe", probe_args=("--version",))
    extras = {
        "pa11y": openswap.probe_binary("pa11y", probe_args=("--version",)),
        "tidy": openswap.probe_binary("tidy", probe_args=("-v",)),
    }
    report = openswap.capability_report(
        "a11y",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )
    report["native_used"] = False
    report["native_never_executed"] = NEVER_EXECUTED
    report["scope_limits"] = a11y.SCOPE_LIMITS
    return report


def _rules_or_fail(rules_file: str | None, command: str) -> dict:
    try:
        return a11y.load_rules(rules_file)
    except Exception as e:
        fail_agent(
            f"bad rules overlay: {type(e).__name__}: {e}",
            command=command,
            example="scout --json a11y rules --rules org-a11y.json",
            discover="scout --json a11y rules",
        )
        raise  # unreachable: fail_agent exits


def _collect_files(paths: list[str], command: str) -> list[Path]:
    """Named files as given; directories walked for a11y.HTML_EXTS (from seo #3)."""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            for ext in a11y.HTML_EXTS:
                files.extend(p.rglob(f"*{ext}"))
        else:
            fail_agent(
                f"path not found: {raw}",
                command=command,
                example="scout --json a11y check page.html",
            )
    return sorted(set(files))


def _read_html(path: Path) -> tuple[str, str | None]:
    """The ONE real I/O call in this plugin: read one local file as utf-8.

    errors="replace" keeps a mojibake byte from aborting an audit of otherwise
    valid markup; a failure to open returns the exception text so the caller can
    record WHY the file was not audited instead of reporting it clean.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace"), None
    except OSError as e:
        return "", f"{type(e).__name__}: {e}"


def _fail_on_or_fail(fail_on: str | None, command: str) -> None:
    if fail_on is not None and fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json a11y check page.html --fail-on error",
        )


@app.command("hello", epilog=examples_epilog(["scout --json a11y hello"]))
def hello():
    """Smoke check — is the a11y surface alive?"""
    emit(
        ok(
            {"ready": True, "plugin": "a11y"},
            command="a11y hello",
            example="scout --json a11y check page.html",
            discover="scout a11y detect",
        ),
        command="a11y hello",
    )


@app.command("detect", epilog=examples_epilog(["scout --json a11y detect"]))
def detect():
    """Report the capability tier (fallback IS the product here — see module doc)."""
    data = _capability()
    data["egress"] = _egress_guard("a11y detect")
    emit(
        ok(
            data,
            command="a11y detect",
            example="scout --json a11y check page.html",
            discover="scout a11y rules",
        ),
        command="a11y detect",
    )


@app.command(
    "rules",
    epilog=examples_epilog(
        ["scout --json a11y rules", "scout --json a11y rules --rules org-a11y.json"]
    ),
)
def rules_cmd(
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
):
    """Publish the effective rule table: id, severity, WCAG criterion, enabled."""
    merged = _rules_or_fail(rules_file, "a11y rules")
    emit(
        ok(
            {
                "rules": merged,
                "overlay": rules_file,
                "severities": list(openswap.SEVERITIES),
                "scope_limits": a11y.SCOPE_LIMITS,
            },
            command="a11y rules",
            example="scout --json a11y check page.html --rules org-a11y.json",
            discover="scout a11y check <path>",
        ),
        command="a11y rules",
    )


@app.command(
    "contrast",
    epilog=examples_epilog(
        [
            "scout --json a11y contrast --fg '#767676' --bg white",
            "scout --json a11y contrast --fg 'rgb(153,153,153)' --bg '#fff' --font-px 24",
            "scout --json a11y contrast --fg '#777' --bg 'rgba(0,0,0,0.5)'",
        ]
    ),
)
def contrast_cmd(
    fg: str = typer.Option(..., "--fg", help="foreground color: hex, rgb()/rgba() or keyword"),
    bg: str = typer.Option(..., "--bg", help="background color: hex, rgb()/rgba() or keyword"),
    font_px: float | None = typer.Option(
        None, "--font-px", help=f"text size in px (>= {a11y.LARGE_PX:g}, or >= {a11y.LARGE_BOLD_PX:g} bold, is WCAG large)"
    ),
    bold: bool = typer.Option(False, "--bold/--no-bold", help="treat the text as bold"),
    fail_below: str | None = typer.Option(
        None, "--fail-below", help="exit 1 unless the pair passes this level (AA|AAA)"
    ),
):
    """One WCAG 2.x contrast reading for a color pair. No files, no network."""
    if fail_below is not None and fail_below.upper() not in a11y.LEVELS:
        fail_agent(
            f"--fail-below must be one of {'|'.join(a11y.LEVELS)}, got {fail_below!r}",
            command="a11y contrast",
            example="scout --json a11y contrast --fg '#777' --bg white --fail-below AA",
        )
    reading = a11y.contrast_reading(fg, bg, font_px=font_px, bold=bold, font_source="cli")
    emit(
        ok(
            reading,
            command="a11y contrast",
            example="scout --json a11y check page.html",
            discover="scout a11y rules",
        ),
        command="a11y contrast",
    )
    if fail_below is not None:
        key = "passes_aaa" if fail_below.upper() == "AAA" else "passes_aa"
        if reading[key] is not True:  # an UNKNOWN reading fails the gate too
            raise typer.Exit(code=1)


@app.command(
    "check",
    epilog=examples_epilog(
        [
            "scout --json a11y check page.html",
            "scout --json a11y check site --fail-on error",
            "scout --json a11y check page.html --rules org-a11y.json --max-findings 50",
        ]
    ),
)
def check(
    paths: list[str] = typer.Argument(
        ..., help="files or directories (dirs walked for " + ", ".join(a11y.HTML_EXTS) + ")"
    ),
    rules_file: str | None = typer.Option(
        None, "--rules", help="JSON rules overlay (org policy, policy-as-config)"
    ),
    fail_on: str | None = typer.Option(
        None,
        "--fail-on",
        help="exit 1 if findings at/above this severity (error|warning|suggestion|info) "
        "— the pre-publish CI gate hook",
    ),
    max_findings: int = typer.Option(
        200, "--max-findings", help="cap emitted diagnostics (summary stays complete)"
    ),
    show_contrast: bool = typer.Option(
        False, "--contrast/--no-contrast", help="include every per-style contrast reading"
    ),
):
    """Audit local HTML files. Reads files; opens no socket on any path."""
    _fail_on_or_fail(fail_on, "a11y check")
    _egress_guard("a11y check")
    rules = _rules_or_fail(rules_file, "a11y check")
    files = _collect_files(paths, "a11y check")
    if not files:
        fail_agent(
            f"no HTML files found (looking for {', '.join(a11y.HTML_EXTS)})",
            command="a11y check",
            example="scout --json a11y check page.html",
        )
    reports = []
    diags: list[dict] = []
    for f in files:
        text, error = _read_html(f)
        report = (
            a11y.unreadable_report(str(f), error, rules=rules)
            if error
            else a11y.page_report(text, path=str(f), rules=rules)
        )
        if not show_contrast:
            report = {k: v for k, v in report.items() if k != "contrast"}
        reports.append(report)
        diags.extend(report["diagnostics"])
    diags = openswap.sort_diagnostics(diags)
    cap = _capability()
    emit(
        ok(
            {
                "tier": cap["tier"],
                "native_used": False,
                "scope_limits": a11y.SCOPE_LIMITS,
                "scope_note": FALLBACK_SCOPE,
                "aggregate": a11y.aggregate(reports),
                "pages": reports,
                "diagnostics": diags[:max_findings],
                "truncated": len(diags) > max_findings,
                "summary": openswap.summarize(diags),
            },
            command="a11y check",
            example="scout --json a11y check site --fail-on error",
            discover="scout a11y rules",
        ),
        command="a11y check",
    )
    if fail_on is not None:
        gate = openswap.severity_rank(fail_on)
        if any(openswap.severity_rank(d["severity"]) <= gate for d in diags):
            raise typer.Exit(code=1)


def register(root):
    root.add_typer(app, name="a11y")
