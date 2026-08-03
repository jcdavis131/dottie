# Solo personal project, no connection to employer, built with public/free-tier only
"""forge plugin — the self-evolution engine. This is how Dottie LLM extends scout-cli itself.

Thesis: One CLI to rule them all, and the LLM knows how to edit this CLI to add any new tool the harness needs.
So the LLM only needs ONE tool in its manifest: `scout`.

Usage by LLM:
  scout --json forge new github --description "GitHub API wrapper"
  scout --json forge from-openapi --name stripe --url https://api.stripe.com/openapi.yaml
  scout --json forge edit mytool --code "new implementation"
  scout --json forge test mytool
  scout --json forge publish --target dottie

All forge commands emit standard ok envelope with example + discover for next step.
"""

import re
import shutil
import textwrap
from pathlib import Path

import typer
import yaml

from bigbang.core.cli_ux import examples_epilog, fail_agent
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit

app = make_plugin_app(
    "forge",
    "🔨 Forge — self-evolution engine. Teach scout a new tool, permanent.",
    examples=[
        "scout --json forge new mytool --description 'does X'",
        "scout --json forge from-openapi --name linear --url https://api.linear.app/openapi.json",
        "scout --json forge list",
        "scout --json forge test mytool",
        "scout --json forge edit mytool --append-command 'search'",
        "scout forge scaffold mytool # quick alias to system scaffold",
    ],
)

PLUGIN_ROOT = Path(__file__).parent.parent  # bigbang/plugins
SKILLS_ROOT = (
    Path(__file__).parents[2] / "skills"
)  # bigbang/skills — `skill install` source


def _valid_name(name: str):
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{1,31}", name))


def _plugin_dir(name: str) -> Path:
    """PLUGIN_ROOT/<name>, refusing anything that escapes PLUGIN_ROOT.

    THE DEFECT, proven in an isolated sandbox on 2026-08-02:

        forge rm ../victim --force
        -> {"ok": true, "removed": "../victim",
            "dir": ".../plugins/../victim", "skill_md_removed": false}
        victim directory: GONE

    `PLUGIN_ROOT / name` follows `..` and, given an absolute path, discards PLUGIN_ROOT
    entirely. In this repo that made `scout forge rm ../core --force` an rmtree of
    bigbang/core — the whole core package — reported as a success.

    _valid_name existed and guarded new_plugin and from_openapi. It was NOT called by the
    four commands that take a name for an EXISTING plugin:

        cat_cmd    reads   -> arbitrary file read
        edit_cmd   writes  -> arbitrary file write
        test_cmd   runs    -> subprocess against an arbitrary dir
        rm_cmd     deletes -> rmtree of an arbitrary dir

    The guard lives HERE rather than in those four, so a fifth caller added later cannot
    miss it. Two checks, not one: the name pattern, and containment of the RESOLVED path.
    The pattern alone would be enough today, but it is one loosened regex away from not
    being — and containment is the property actually wanted.
    """
    if not _valid_name(name):
        fail_agent(
            f"invalid plugin name: {name!r}",
            command="forge",
            example="scout forge rm mytool --force",
            discover="names are [a-z][a-z0-9_]{1,31} — no paths, no separators",
        )
    candidate = PLUGIN_ROOT / name
    try:
        resolved = candidate.resolve()
        root = PLUGIN_ROOT.resolve()
    except OSError:
        resolved, root = candidate, PLUGIN_ROOT
    if resolved != root and root not in resolved.parents:
        fail_agent(
            f"refusing a path outside the plugin root: {resolved}",
            command="forge",
            example="scout forge rm mytool --force",
        )
    return candidate


def _skill_dir(name: str) -> Path:
    """SKILLS_ROOT/<name>, refusing anything that escapes SKILLS_ROOT.

    The same guard _plugin_dir carries, for the same reason. Today the only caller of
    _scaffold_skill_md is new_plugin, which validates at line 238 — so this is not a live
    hole. It is here because "the caller happens to validate" is the property that failed
    in a5c155b: _valid_name existed and guarded two commands while four others, added
    later, used _plugin_dir directly. Putting the check next to the mkdir is what makes a
    fifth caller safe by default rather than by review.
    """
    if not _valid_name(name):
        fail_agent(
            f"invalid skill name: {name!r}",
            command="forge",
            example="scout forge new mytool --desc '...'",
            discover="names are [a-z][a-z0-9_]{1,31} — no paths, no separators",
        )
    candidate = SKILLS_ROOT / name
    try:
        resolved, root = candidate.resolve(), SKILLS_ROOT.resolve()
    except OSError:
        resolved, root = candidate, SKILLS_ROOT
    if resolved != root and root not in resolved.parents:
        fail_agent(
            f"refusing a path outside the skills root: {resolved}",
            command="forge",
            example="scout forge new mytool --desc '...'",
        )
    return candidate


def _scaffold_skill_md(name: str, description: str) -> Path:
    """Write bigbang/skills/<name>/SKILL.md so `scout skill install <name>` works the
    moment a tool is forged — teaching Dottie was a manual step the self-evolution
    loop always had to remember (TODOS 6.4)."""
    sdir = _skill_dir(name)
    sdir.mkdir(parents=True, exist_ok=True)
    md = sdir / "SKILL.md"
    if not md.exists():
        triggers = (
            ", ".join(
                sorted(
                    {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", description)}
                    | {name}
                )[:6]
            )
            or name
        )
        md.write_text(
            f"---\nname: {name}\ndescription: {description}\n"
            f"j_space_target: system1\nhalf_life: 30\ntriggers: [{triggers}]\n---\n"
            f"Auto-forged tool. Discover with `scout --json {name} --help`; typical call\n"
            f"`scout --json {name} run ...`. Edit this file to refine routing metadata.\n",
            encoding="utf-8",
        )
    return md


def _ensure_scaffold(name: str, description: str):
    pdir = _plugin_dir(name)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "__init__.py").touch(exist_ok=True)
    cli_file = pdir / "cli.py"
    manifest = pdir / "manifest.yaml"

    if not cli_file.exists():
        cli_file.write_text(
            textwrap.dedent(f'''
            # Solo personal project, no connection to employer, built with public/free-tier only
            """{name} plugin — auto-forged by scout forge, editable by Dottie LLM."""
            from pathlib import Path
            from typing import Optional
            import typer
            from bigbang.core.contract import make_plugin_app, ok
            from bigbang.core.output import emit
            from bigbang.core.cli_ux import examples_epilog

            app = make_plugin_app(
                "{name}",
                "{description}",
                examples=[
                    "scout --json {name} hello",
                    "scout {name} --help",
                    "scout --json {name} run --arg hello",
                ],
            )

            @app.command("hello", epilog=examples_epilog(["scout --json {name} hello"]))
            def hello():
                """Smoke test — this is how harness verifies the tool loads."""
                emit(ok({{"message": "Hello from {name}!", "ready": True}}, command="{name} hello", example="scout --json {name} hello", discover="scout forge edit {name}"))

            @app.command("run", epilog=examples_epilog([ "scout --json {name} run --arg value" ]))
            def run_cmd(arg: str = typer.Argument("world", help="anything"), verbose: bool = typer.Option(False, "--verbose")):
                """Main entrypoint — LLM should replace this with real logic."""
                # TODO: LLM — replace with real implementation. You can import httpx, call APIs, read files, etc.
                # Example pattern:
                # import httpx
                # r = httpx.get("https://api.example.com?q="+arg, timeout=10)
                # data = r.json()
                emit(ok({{"input": arg, "output": f"{{name}} processed: {{arg}}", "verbose": verbose, "todo": "Replace run() with real logic via scout forge edit"}}, command="{name} run", example="scout --json {name} run 'hello world'"))

            @app.command("edit-instructions")
            def edit_instructions():
                """Tell LLM how to edit this file."""
                emit(ok({{
                    "plugin_dir": str(Path(__file__).parent),
                    "cli_file": str(Path(__file__)),
                    "manifest": str(Path(__file__).parent / "manifest.yaml"),
                    "how_to_edit": [
                        "1. Read cli.py via scout --json forge cat {name}",
                        "2. Write new implementation via scout --json forge edit {name} --code '<new cli.py content>'",
                        "3. Verify via scout --json forge test {name}",
                        "4. Teach Dottie: scout skill install {name} --target dottie (if you create SKILL.md)"
                    ],
                    "contract": "Use make_plugin_app + ok() envelope + examples_epilog + emit(). Always return {{ok:True}} with example+discover.",
                    "capabilities": "Declare in manifest.yaml: network.domains, filesystem.write, secrets.allow"
                }}, command="{name} edit-instructions"))
        ''').lstrip(),
            encoding="utf-8",
        )

    if not manifest.exists():
        manifest.write_text(
            f"""name: {name}
version: 0.7.0
description: {description}
capabilities:
  network:
    enabled: false
    domains: []
  filesystem:
    write: false
    paths: []
  secrets:
    allow: []
# LLM can edit this to request capabilities — policy enforces.
# Example to enable network:
# network:
#   enabled: true
#   domains: ["api.github.com"]
""",
            encoding="utf-8",
        )
    return pdir


@app.command(
    "new",
    epilog=examples_epilog(
        ["scout --json forge new weather --description 'Weather API'"]
    ),
)
def new_plugin(
    name: str = typer.Argument(
        ..., help="new tool name snake_case, e.g. weather, github, linear"
    ),
    description: str = typer.Option("", "--description", "-d", help="what it does"),
    domains: str = typer.Option(
        "",
        "--domains",
        help="comma-separated allowed network domains, e.g. api.github.com,api.linear.app",
    ),
    with_network: bool = typer.Option(
        False, "--network", help="enable network capability"
    ),
):
    """Forge a brand new permanent CLI plugin — this is how LLM adds a tool."""
    if not _valid_name(name):
        fail_agent(
            f"Invalid plugin name {name} — must be [a-z][a-z0-9_]{{1,31}}",
            command="forge new",
            example="scout forge new my_tool",
        )
    pdir = _plugin_dir(name)
    if pdir.exists() and (pdir / "cli.py").exists():
        fail_agent(
            f"Plugin {name} already exists at {pdir}",
            command="forge new",
            example=f"scout --json forge edit {name}",
        )

    desc = description or f"{name} — auto-forged by Dottie LLM via scout forge"
    pdir = _ensure_scaffold(name, desc)

    # Update manifest with domains if provided
    if domains or with_network:
        mf = yaml.safe_load((pdir / "manifest.yaml").read_text(encoding="utf-8")) or {}
        mf.setdefault("capabilities", {}).setdefault("network", {})["enabled"] = True
        doms = [d.strip() for d in domains.split(",") if d.strip()]
        if doms:
            mf["capabilities"]["network"]["domains"] = doms
        (pdir / "manifest.yaml").write_text(yaml.safe_dump(mf), encoding="utf-8")

    skill_md = _scaffold_skill_md(name, desc)

    emit(
        ok(
            {
                "plugin": name,
                "dir": str(pdir),
                "cli_file": str(pdir / "cli.py"),
                "manifest": str(pdir / "manifest.yaml"),
                "skill_md": str(skill_md),
                "status": "scaffolded",
                "next_steps": [
                    f"scout --json {name} hello  # verify it loads",
                    f"scout forge edit {name} --instructions  # how to implement real logic",
                    f"scout --json forge test {name}",
                    f"scout skill install {name} --target dottie  # SKILL.md scaffolded for you",
                ],
                "llm_editable": True,
                "self_evolution": f"You can now edit {pdir / 'cli.py'} to implement any tool you need. Use scout forge edit {name}",
            },
            command="forge new",
            example=f"scout --json {name} hello",
            discover="scout forge edit",
        ),
        command="forge new",
    )


@app.command(
    "from-openapi",
    epilog=examples_epilog(
        [
            "scout --json forge from-openapi --name linear --url https://api.linear.app/openapi.json"
        ]
    ),
)
def from_openapi(
    name: str = typer.Option(..., "--name", "-n", help="plugin name"),
    url: str = typer.Option(..., "--url", "-u", help="OpenAPI spec URL"),
    description: str = typer.Option("", "--description"),
):
    """Forge from OpenAPI spec — auto-generates full Typer plugin from spec URL."""
    if not _valid_name(name):
        fail_agent(f"Invalid name {name}", command="forge from-openapi")
    try:
        from bigbang.core.openapi import fetch_spec, generate_typer_plugin

        spec = fetch_spec(url)
        code = generate_typer_plugin(name, spec, url)
        pdir = _plugin_dir(name)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "__init__.py").touch(exist_ok=True)
        (pdir / "cli.py").write_text(code, encoding="utf-8")
        # manifest with domain from URL
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        (pdir / "manifest.yaml").write_text(
            f"""name: {name}
version: 0.7.0
description: {description or f"{name} — generated from OpenAPI {url}"}
source: {url}
capabilities:
  network:
    enabled: true
    domains: ["{domain}"]
  filesystem:
    write: false
""",
            encoding="utf-8",
        )
        emit(
            ok(
                {
                    "plugin": name,
                    "from": url,
                    "ops": len(spec.get("paths", {})),
                    "dir": str(pdir),
                },
                command="forge from-openapi",
                example=f"scout --json {name} --help",
            ),
            command="forge from-openapi",
        )
    except Exception as e:
        fail_agent(
            f"OpenAPI forge failed: {e}",
            command="forge from-openapi",
            example="scout tools add linear --type openapi --url <url> # fallback dynamic",
        )


@app.command(
    "from-mcp",
    epilog=examples_epilog(
        ["scout --json forge from-mcp --name notion --url https://mcp.notion.com/sse"]
    ),
)
def from_mcp(
    name: str = typer.Option(..., "--name"),
    url: str = typer.Option(..., "--url"),
):
    """Forge from MCP server URL — registers as permanent MCP-backed plugin."""
    pdir = _ensure_scaffold(name, f"{name} MCP wrapper for {url}")
    # Keep scaffold but update manifest to MCP
    mf_path = pdir / "manifest.yaml"
    data = yaml.safe_load(mf_path.read_text(encoding="utf-8")) or {}
    data["type"] = "mcp"
    data["url"] = url
    data["capabilities"] = data.get("capabilities", {})
    data["capabilities"]["network"] = {
        "enabled": True,
        "domains": [url.split("/")[2] if "://" in url else url],
    }
    mf_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    # Append MCP proxy to cli.py
    cli_file = pdir / "cli.py"
    existing = cli_file.read_text(encoding="utf-8")
    if "mcp_proxy" not in existing:
        cli_file.write_text(
            existing
            + f'\n\n# MCP proxy added by forge from-mcp\n@app.command("call-mcp")\ndef call_mcp(tool_name: str = typer.Argument(..., help="MCP tool name"), args_json: str = typer.Argument("{{}}")):\n    """Proxy to MCP server {url}""" \n    import json, httpx\n    emit(ok({{"proxy":"mcp", "server":"{url}", "tool": tool_name, "args": json.loads(args_json)}}, command="{name} call-mcp"))\n'
        )

    emit(
        ok(
            {"plugin": name, "mcp_url": url, "dir": str(pdir)},
            command="forge from-mcp",
            example=f"scout --json {name} call-mcp <tool>",
        ),
        command="forge from-mcp",
    )


@app.command("list", epilog=examples_epilog(["scout --json forge list"]))
def list_cmd():
    """List all forgeable + forged plugins."""
    plugins = []
    for pdir in PLUGIN_ROOT.iterdir():
        if not pdir.is_dir() or pdir.name.startswith("__"):
            continue
        mf = pdir / "manifest.yaml"
        cli = pdir / "cli.py"
        plugins.append(
            {
                "name": pdir.name,
                "has_cli": cli.exists(),
                "has_manifest": mf.exists(),
                "forged_by": "forge"
                if "auto-forged"
                in (cli.read_text(encoding="utf-8")[:1000] if cli.exists() else "")
                else "system",
            }
        )
    emit(
        ok(
            {"plugins": plugins, "count": len(plugins), "forge_root": str(PLUGIN_ROOT)},
            command="forge list",
            discover="scout system policy",
        ),
        command="forge list",
    )


@app.command("cat", epilog=examples_epilog(["scout --json forge cat mytool"]))
def cat_cmd(name: str = typer.Argument(..., help="plugin name")):
    """Cat cli.py + manifest.yaml — so LLM can read before editing."""
    pdir = _plugin_dir(name)
    if not pdir.exists():
        fail_agent(
            f"Plugin {name} not found", command="forge cat", example="scout forge list"
        )
    cli = pdir / "cli.py"
    mf = pdir / "manifest.yaml"
    out = {}
    if cli.exists():
        out["cli.py"] = cli.read_text(encoding="utf-8")[:20000]  # limit 20k
    if mf.exists():
        out["manifest.yaml"] = mf.read_text()
    emit(ok(out, command=f"forge cat {name}"), command="forge cat")


@app.command(
    "edit",
    epilog=examples_epilog(["scout --json forge edit mytool --code 'new content'"]),
)
def edit_cmd(
    name: str = typer.Argument(..., help="plugin name"),
    code: str | None = typer.Option(
        None, "--code", help="full new cli.py content (or use --code-file)"
    ),
    code_file: str | None = typer.Option(
        None, "--code-file", help="path to file containing new cli.py"
    ),
    append_command: str | None = typer.Option(
        None, "--append-command", help="quick append a new command stub named X"
    ),
    instructions: bool = typer.Option(False, "--instructions", help="show how to edit"),
):
    """Edit a forged plugin — LLM's way to implement real logic."""
    pdir = _plugin_dir(name)
    if not pdir.exists():
        fail_agent(
            f"Plugin {name} not found — forge new first",
            command="forge edit",
            example=f"scout forge new {name}",
        )

    if instructions:
        emit(
            ok(
                {
                    "how": [
                        f"Read current: scout --json forge cat {name}",
                        "Write new cli.py with your real implementation",
                        f"scout --json forge edit {name} --code '<full file>'",
                        f"Test: scout --json {name} hello",
                        "Repeat until tests pass. Use ok() envelope + emit().",
                        "Declare capabilities in manifest.yaml if you need network/filesystem",
                    ],
                    "contract_file": "bigbang/core/contract.py — make_plugin_app, ok(), err()",
                    "example_plugin": "bigbang/plugins/system/cli.py",
                    "llm_tip": "Keep commands JSON-friendly: use scout --json prefix. Always return ok() with example + discover fields so next LLM can find it.",
                },
                command="forge edit",
            ),
            command="forge edit",
        )
        return

    cli_file = pdir / "cli.py"
    if append_command:
        if not cli_file.exists():
            fail_agent("cli.py missing", command="forge edit")
        existing = cli_file.read_text(encoding="utf-8")
        stub = f'''\n\n@app.command("{append_command}")
def {append_command.replace("-", "_")}_cmd(arg: str = typer.Argument("", help="arg")):
    """{append_command} — TODO implemented by LLM"""
    emit(ok({{"command": "{append_command}", "arg": arg, "plugin": "{name}"}}, command="{name} {append_command}"))
'''
        cli_file.write_text(existing + stub, encoding="utf-8")
        emit(
            ok(
                {"appended": append_command, "file": str(cli_file)},
                command="forge edit",
            ),
            command="forge edit",
        )
        return

    new_code = None
    if code_file:
        new_code = Path(code_file).read_text()
    elif code:
        new_code = code

    if not new_code:
        fail_agent(
            "Need --code or --code-file or --append-command or --instructions",
            command="forge edit",
            example=f"scout forge cat {name}",
        )

    cli_file.write_text(new_code, encoding="utf-8")
    emit(
        ok(
            {
                "edited": name,
                "file": str(cli_file),
                "bytes": len(new_code),
                "next": f"scout --json {name} hello",
            },
            command="forge edit",
            discover=f"scout --json {name} --help",
        ),
        command="forge edit",
    )


@app.command("test", epilog=examples_epilog(["scout --json forge test mytool"]))
def test_cmd(name: str = typer.Argument(..., help="plugin name")):
    """Smoke test a forged plugin — hello + --help"""
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + f":{Path(__file__).parents[3]}"
    # Try hello
    pdir = _plugin_dir(name)
    if not pdir.exists():
        emit({"ok": False, "error": f"{name} not found"}, command="forge test")
        raise typer.Exit(1)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "bigbang.cli", "--json", name, "hello"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(Path(__file__).parents[3]),
            env=env,
        )
        out = result.stdout[:5000]
        err = result.stderr[:2000]
        success = result.returncode == 0
        emit(
            ok(
                {
                    "plugin": name,
                    "hello_exit_code": result.returncode,
                    "hello_output": out,
                    "stderr": err,
                    "passes": success,
                    "next": f"scout --json {name} --help"
                    if success
                    else f"scout forge cat {name} and fix",
                },
                command="forge test",
                example=f"scout --json {name} hello",
            ),
            command="forge test",
        )
    except Exception as e:
        emit({"ok": False, "error": str(e)}, command="forge test")
        raise typer.Exit(1)


@app.command("rm", epilog=examples_epilog(["scout forge rm mytool --force"]))
def rm_cmd(
    name: str = typer.Argument(...), force: bool = typer.Option(False, "--force", "-f")
):
    """Remove a forged plugin (requires --force)."""
    pdir = _plugin_dir(name)
    if not pdir.exists():
        emit(
            ok({"removed": False, "reason": "not found"}, command="forge rm"),
            command="forge rm",
        )
        return
    if not force:
        fail_agent(
            f"Pass --force to remove {name}",
            command="forge rm",
            example=f"scout forge rm {name} --force",
        )
    shutil.rmtree(pdir)
    # the scaffolded SKILL.md dies with its tool — no orphaned skills teaching a
    # capability that no longer exists
    skill_dir = SKILLS_ROOT / name
    removed_skill = skill_dir.exists()
    if removed_skill:
        shutil.rmtree(skill_dir, ignore_errors=True)
    emit(
        ok(
            {"removed": name, "dir": str(pdir), "skill_md_removed": removed_skill},
            command="forge rm",
        ),
        command="forge rm",
    )


def register(root):
    root.add_typer(app, name="forge")
