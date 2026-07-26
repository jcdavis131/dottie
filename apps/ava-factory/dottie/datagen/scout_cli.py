"""ScoutCliGenerator — teach the trainee to *use* and *build with* scout-cli.

Solo personal project, no connection to employer, built with public/free-tier only
HOME-only, zero network, private RNG only, byte-identical determinism.

`scout` is the agent's single self-extending CLI (apps/scout-cli, the bigbang
package). Nothing in the curriculum taught the model its contract, so this
generator fills that gap. It teaches the two halves of the skill, grounded in
the *real* foundation contract (bigbang.core.contract / bigbang.core.output),
not invented syntax:

Families
  * scout_use     (tool_selection): a task -> the ONE correct
                  `scout --json <plugin> <command>` invocation -> the JSON
                  envelope it prints -> read `ok`, act on `data`. The envelope
                  is *computed* here (the same ok()/err() shape the CLI emits),
                  never hand-typed, so tests can re-parse and verify it.
  * scout_ground  (deliberate): the observation is an error envelope
                  (`{"ok": false, "error": ...}`), a health check that is down,
                  or an empty result set. The correct continuation REPORTS the
                  failure and never fabricates output the command did not
                  return -- the same grounding discipline as react_tools.
  * scout_build   (deliberate): build a foundation-shaped plugin from a spec.
                  Emits the real template -- make_plugin_app, @app.command,
                  emit(ok(...)), def register(root): root.add_typer(...) -- plus
                  a manifest.yaml whose capabilities are default-deny.
  * scout_contract(automatic): short drills on the envelope shape and the
                  default-deny capability posture. Answers computed by Python.

Curriculum placement: phases (2, 3, 5).
  p2 foundation : learn the CLI surface + envelope + plugin skeleton (automatic
                  drills, single-step tool selection, basic build).
  p3 reasoning  : multi-step trajectories, grounding/recovery, full builds.
  p5 anneal     : high-quality verified plugin builds and verified trajectories.

Byte-deterministic: private random.Random only, sorted structures, json.dumps
with sort_keys, no wall-clock, no network, no global random.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from dottie.datagen.base import Generator, run_cli

# --- faithful mirror of bigbang.core.contract.{ok,err} ----------------------
# Reproduced (not imported) so the generator stays self-contained and offline,
# exactly as compression.py reimplements its algorithms. Kept byte-identical to
# the real envelope so the trainee learns the true output shape.


def _ok(data: Any, *, command: str, discover: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True, "command": command}
    if data is not None:
        payload["data"] = data
    if discover:
        payload["discover"] = discover
    return payload


def _err(error: str, *, command: str, discover: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "command": command, "error": error}
    if discover:
        payload["discover"] = discover
    return payload


def _dumps(envelope: dict[str, Any]) -> str:
    """How `scout --json` serializes: json.dump(..., indent=2) with NO sort_keys
    (see bigbang/core/output.py:emit), so keys print in insertion order -- ok,
    command, data -- exactly like the real envelope. The builders construct every
    dict deterministically, so the corpus stays byte-identical without sorting;
    sort_keys would re-order to alphabetical (ok LAST), a shape real scout never
    emits and the trainee should never learn."""
    return json.dumps(envelope, indent=2)


# --- real scout surface (confirmed against apps/scout-cli/bigbang/plugins) ---
# Only plugins/commands that actually exist are referenced, so the model never
# learns a command that isn't there.

_PLUGINS = [
    (
        "system",
        "doctor",
        "check the local environment (git, docker, ollama, vault, audit log)",
    ),
    ("system", "audit", "show the last N audited tool calls"),
    (
        "system",
        "policy",
        "list each plugin's declared capabilities (network/filesystem/secrets)",
    ),
    ("skill", "show", "read what a skill teaches before invoking it"),
    ("skill", "list", "enumerate installed skills"),
    ("tasks", "add", "record a follow-up task on a list"),
    ("tasks", "list", "show open tasks"),
    ("vector", "search", "semantic search over indexed notes"),
    ("tools", "list", "list registered tools"),
    ("tools", "teach", "print an agent-facing how-to for a tool"),
]

# snake_case fragments used to synthesize believable new plugin/command names
# for the build family (deterministic, never a real collision-sensitive value).
_BUILD_NOUNS = [
    "ledger",
    "beacon",
    "sifter",
    "harbor",
    "quill",
    "tally",
    "relay",
    "warden",
    "lattice",
    "cinder",
    "meadow",
    "pylon",
    "drift",
    "ember",
]
_BUILD_VERBS = [
    "scan",
    "emit",
    "digest",
    "fetch",
    "index",
    "verify",
    "summarize",
    "route",
    "reconcile",
    "snapshot",
]


class ScoutCliGenerator(Generator):
    name = "scout_cli"
    phases = (2, 3, 5)

    def generate(self, target_bytes: int) -> Iterator[dict]:
        bytes_so_far = 0
        idx = 0
        while bytes_so_far < target_bytes:
            # Pick a phase first so every declared phase is reliably emitted
            # (the collector filters the stream by phase and would spin forever
            # on a phase this generator never produces).
            phase = self.rng.choice([2, 3, 5])
            fam = self._family_for_phase(phase)
            if fam == "scout_contract":
                doc = self._gen_contract(idx, phase)
            elif fam == "scout_use":
                doc = self._gen_use(idx, phase)
            elif fam == "scout_ground":
                doc = self._gen_ground(idx, phase)
            else:
                doc = self._gen_build(idx, phase)
            idx += 1
            bytes_so_far += len(doc["text"].encode("utf-8")) + 200
            yield doc

    def _family_for_phase(self, phase: int) -> str:
        if phase == 2:
            # foundation: drills + single-step use + basic build
            return self.rng.choice(
                ["scout_contract", "scout_contract", "scout_use", "scout_build"]
            )
        if phase == 3:
            # reasoning: multi-step use, grounding/recovery, full build
            return self.rng.choice(
                ["scout_use", "scout_ground", "scout_ground", "scout_build"]
            )
        # p5 anneal: highest-quality verified builds + verified trajectories
        return self.rng.choice(["scout_build", "scout_build", "scout_use"])

    # ---- helpers -----------------------------------------------------------

    def _doctor_checks(self) -> list[dict[str, Any]]:
        """A realistic `system doctor` check list; ollama is 'down (expected
        local)' by design (the real doctor labels a missing local ollama not-ok
        but harmless)."""
        docker_ok = self.rng.random() < 0.6
        return [
            {"check": "python", "status": "3.13.1", "ok": True},
            {"check": "git", "status": "/usr/bin/git", "ok": True},
            {
                "check": "docker",
                "status": "/usr/bin/docker" if docker_ok else "missing",
                "ok": docker_ok,
            },
            {"check": "ollama", "status": "down (expected local)", "ok": False},
            {
                "check": "vault",
                "status": "~/.local/share/bigbang/secrets.json exists, mode 0600",
                "ok": True,
            },
        ]

    def _payload_for(self, plugin: str, command: str) -> Any:
        """Deterministic, realistic `data` for a given real command."""
        if plugin == "system" and command == "doctor":
            checks = self._doctor_checks()
            return {
                "message": "doctor complete",
                "checks": checks,
                "security": "vault 0600, policy caps, audit jsonl",
            }
        if plugin == "system" and command == "audit":
            n = self.rng.randint(2, 4)
            tail = [
                {
                    "seq": i,
                    "command": self.rng.choice(
                        ["skill show scout", "tasks list", "vector search"]
                    ),
                }
                for i in range(n)
            ]
            return {
                "audit_tail": tail,
                "count": n,
                "file": "~/.local/share/bigbang/audit.jsonl",
            }
        if plugin == "system" and command == "policy":
            return {
                "policies": [
                    {"name": "system", "network": False, "filesystem_write": False}
                ],
                "note": "each plugin declares capabilities; default deny",
            }
        if plugin == "skill" and command == "show":
            return {
                "skill": "scout",
                "commands": ["system doctor", "skill list", "tasks add"],
                "teaches": "how to drive scout end to end",
            }
        if plugin == "skill" and command == "list":
            return {
                "skills": sorted(["scout", "memory-mint", "jspace-context-engine"]),
                "count": 3,
            }
        if plugin == "tasks" and command == "add":
            return {
                "added": "re-run the eval gate after retrain",
                "id": self.rng.randint(10, 99),
            }
        if plugin == "tasks" and command == "list":
            return {
                "open": [{"id": 12, "text": "wire compression curriculum"}],
                "count": 1,
            }
        if plugin == "vector" and command == "search":
            k = self.rng.randint(1, 3)
            return {
                "query": "how does the eval gate score a checkpoint",
                "results": [
                    {
                        "id": 100 + i,
                        "score": round(0.9 - 0.1 * i, 3),
                        "text": "the harness scores per-rubric, anti-mock",
                    }
                    for i in range(k)
                ],
            }
        if plugin == "tools" and command == "list":
            return {"tools": sorted(["search", "read", "emit"]), "count": 3}
        if plugin == "tools" and command == "teach":
            return {
                "tool": "search",
                "how": "scout --json vector search '<query>'",
                "returns": "ranked results with scores",
            }
        return {"note": "ok"}

    # ---- families ----------------------------------------------------------

    def _gen_contract(self, idx: int, phase: int) -> dict:
        """Automatic drill on the envelope shape or the default-deny posture.
        The answer is a *computed* JSON envelope (or a one-word default)."""
        which = self.rng.choice(["ok_shape", "err_shape", "cap_default"])
        if which == "ok_shape":
            plugin, command, _ = self.rng.choice(_PLUGINS)
            cmd = f"{plugin} {command}"
            data = self._payload_for(plugin, command)
            env = _ok(data, command=cmd, discover="scout skill show scout")
            text = f"""Drill: the scout success envelope (bigbang.core.contract.ok)

Every scout command emits a JSON envelope under `--json`. A success is built by
`ok(data, command=..., discover=...)` and always carries `"ok": true` plus the
`"command"` string; the payload rides under `"data"`.

Q: what does `scout --json {cmd}` print on success?
A (computed):
```json
{_dumps(env)}
```

Rule to learn: branch on the top-level `"ok"`. If true, use `"data"`. The
`"command"` field echoes what ran, and `"discover"` (when present) points at the
next thing to read. Never parse human/rich output -- always pass `--json`.

Source: scout_cli/contract doc {idx} -- P{phase} automatic, envelope literacy.
"""
            concept = "scout_ok_envelope"
        elif which == "err_shape":
            plugin, command, _ = self.rng.choice(_PLUGINS)
            cmd = f"{plugin} bogus"
            env = _err(
                f"no such command 'bogus' under '{plugin}'",
                command=cmd,
                discover=f"scout {plugin} --help",
            )
            text = f"""Drill: the scout error envelope (bigbang.core.contract.err)

A failure is built by `err(error, command=..., discover=...)`: `"ok": false`,
an `"error"` string, and usually a `"discover"` hint for how to recover.

Q: what does `scout --json {cmd}` print when the subcommand doesn't exist?
A (computed):
```json
{_dumps(env)}
```

Rule to learn: on `"ok": false` you do NOT have a result. Read `"error"`, follow
`"discover"` (here `scout {plugin} --help`), and try again -- never invent the
output the command failed to produce.

Source: scout_cli/contract doc {idx} -- P{phase} automatic, failure literacy.
"""
            concept = "scout_err_envelope"
        else:
            # capability default-deny drill
            manifest = (
                "name: mytool\n"
                "version: 0.7.0\n"
                "capabilities:\n"
                "  network:\n    enabled: false\n    domains: []\n"
                "  filesystem:\n    write: false\n    paths: []\n"
                "  secrets:\n    allow: []\n"
            )
            text = f"""Drill: scout capability posture is default-deny

Every plugin ships a manifest.yaml declaring what it may touch. A freshly
scaffolded plugin declares NOTHING allowed:

```yaml
{manifest}```

Q: for a scaffolded plugin, what is `capabilities.network.enabled`?
A (computed): false. Likewise `filesystem.write` is false and `secrets.allow`
is the empty list. A plugin gets a capability only when its manifest opts in;
the default is deny. This is why `scout system policy` can audit exactly what
each surface is permitted to do.

Source: scout_cli/contract doc {idx} -- P{phase} automatic, security posture.
"""
            concept = "scout_capability_default_deny"
        return self.doc(
            text=text,
            task_type="automatic",
            concept=concept,
            phase=phase,
            source="scout_cli/contract",
        )

    def _gen_use(self, idx: int, phase: int) -> dict:
        """A task -> the correct `scout --json` invocation -> observe -> act.
        task_type=tool_selection: the skill is picking the right command."""
        plugin, command, purpose = self.rng.choice(_PLUGINS)
        cmd = f"{plugin} {command}"
        data = self._payload_for(plugin, command)
        env = _ok(data, command=cmd, discover="scout skill show scout")
        # a p3 doc chains a second, dependent step
        multistep = phase >= 3 and self.rng.random() < 0.6

        # derive an honest conclusion from the computed data
        conclusion = self._conclude(plugin, command, data)

        step2 = ""
        if multistep:
            p2, c2, _ = self.rng.choice([p for p in _PLUGINS if p[0] != plugin])
            data2 = self._payload_for(p2, c2)
            env2 = _ok(data2, command=f"{p2} {c2}")
            step2 = f"""
Thought: the first Observation tells me what I needed; now I follow up.
Action: scout --json {p2} {c2}
Observation:
```json
{_dumps(env2)}
```
Thought: {self._conclude(p2, c2, data2)}
"""

        text = f"""### Task: {purpose[0].upper() + purpose[1:]}.

The agent's only interface is the `scout` CLI. Pick the ONE command that answers
the task, run it with `--json`, and read the envelope.

Thought: this maps to `{cmd}`. I pass `--json` so I get a machine envelope, not
rich text.
Action: scout --json {cmd}
Observation:
```json
{_dumps(env)}
```
Thought: `"ok"` is true, so `"data"` is trustworthy. {conclusion}{step2}
Answer: {conclusion}

Why this shape: scout commands are chosen by task, not guessed. `--json` yields
`ok`/`command`/`data`; you branch on `ok` and act on `data`. Discover more with
`scout skill show scout`.

Source: scout_cli/use doc {idx} -- P{phase} tool selection{" + multi-step" if multistep else ""}.
"""
        tt = "tool_selection" if not multistep else "deliberate"
        return self.doc(
            text=text,
            task_type=tt,
            concept="scout_tool_use",
            phase=phase,
            source="scout_cli/use",
        )

    def _conclude(self, plugin: str, command: str, data: Any) -> str:
        """An honest, data-derived sentence -- computed from the payload."""
        if plugin == "system" and command == "doctor":
            failed = [c["check"] for c in data["checks"] if not c["ok"]]
            if failed:
                return (
                    f"{len(failed)} check(s) not ok: {', '.join(sorted(failed))}; "
                    f"the rest pass. Report exactly these, no more."
                )
            return "every check passed; the environment is healthy."
        if plugin == "system" and command == "audit":
            return f"the last {data['count']} tool calls are listed; nothing to fabricate beyond them."
        if plugin == "vector" and command == "search":
            n = len(data["results"])
            return (
                f"{n} match(es) returned; cite them by id and score, and claim nothing "
                f"the results don't contain."
            )
        if plugin == "tasks" and command == "add":
            return f"the task was recorded with id {data['id']}."
        if plugin == "skill" and command == "show":
            return f"the skill exposes {len(data['commands'])} commands; use those, not invented ones."
        if plugin == "skill" and command == "list":
            return f"{data['count']} skills are installed: {', '.join(data['skills'])}."
        if plugin == "tools" and command == "list":
            return f"{data['count']} tools are registered."
        if plugin == "tools" and command == "teach":
            return f"the how-to is `{data['how']}`."
        if plugin == "tasks" and command == "list":
            return f"{data['count']} open task(s)."
        if plugin == "system" and command == "policy":
            return "each plugin's declared capabilities are listed; default is deny."
        return "the command succeeded; use the returned data verbatim."

    def _gen_ground(self, idx: int, phase: int) -> dict:
        """The observation is a failure/empty; the model must report it, not
        fabricate. Mirrors react_tools' grounding family."""
        kind = self.rng.choice(["error", "down", "empty"])
        if kind == "error":
            fake = self.rng.choice(["frobnicate", "teleport", "summon"])
            cmd = f"{fake} run"
            env = _err(
                f"no such command '{fake}'", command=cmd, discover="scout --help"
            )
            conclusion = (
                f"`scout {fake}` does not exist -- the envelope says `ok: false`. "
                f"I will not describe what it 'would' return; I run `scout --help` "
                f"to find the real command."
            )
            body = f"""Action: scout --json {cmd}
Observation:
```json
{_dumps(env)}
```
Thought: {conclusion}
Answer: The command `{fake}` isn't a real scout surface; there is no result to
report. Next step: `scout --help` to discover the correct command."""
            concept = "scout_grounding_unknown"
        elif kind == "down":
            checks = self._doctor_checks()
            env = _ok(
                {"message": "doctor complete", "checks": checks},
                command="system doctor",
            )
            down = [c["check"] for c in checks if not c["ok"]]
            conclusion = (
                f"the envelope is `ok: true` but the payload shows {', '.join(sorted(down))} "
                f"not ok. Success of the *command* is not success of every *check*. "
                f"I report the down checks honestly instead of claiming all green."
            )
            body = f"""Action: scout --json system doctor
Observation:
```json
{_dumps(env)}
```
Thought: {conclusion}
Answer: doctor ran fine, but {", ".join(sorted(down))} is/are down; everything
else passes. (ollama down is expected for a local box.)"""
            concept = "scout_grounding_partial"
        else:
            env = _ok(
                {"query": "nonexistent topic xyzzy", "results": []},
                command="vector search",
            )
            conclusion = (
                "the results list is empty. There is nothing to summarize. I say 'no "
                "matches' rather than inventing a plausible-sounding hit."
            )
            body = f"""Action: scout --json vector search "nonexistent topic xyzzy"
Observation:
```json
{_dumps(env)}
```
Thought: {conclusion}
Answer: No matches were found for that query. I won't fabricate a result."""
            concept = "scout_grounding_empty"

        text = f"""### Task: use scout, and stay grounded in what it actually returns.

{body}

Rule: the Observation is the ground truth. `ok: false` means no result; an empty
`data` means nothing to report; a check that is `ok: false` inside a successful
command must still be surfaced. Never narrate behavior the tool did not emit.

Source: scout_cli/ground doc {idx} -- P{phase} grounding/recovery.
"""
        return self.doc(
            text=text,
            task_type="deliberate",
            concept=concept,
            phase=phase,
            source="scout_cli/ground",
        )

    def _gen_build(self, idx: int, phase: int) -> dict:
        """Build a foundation-shaped plugin from a spec: real template + manifest.
        This is the 'building WITH scout-cli' half."""
        name = self.rng.choice(_BUILD_NOUNS)
        cmdname = self.rng.choice(_BUILD_VERBS)
        help_text = f"{name} plugin -- {cmdname} things, capability-declared"
        # Build a sample success envelope the new command will emit, computed.
        sample_env = _ok(
            {"message": f"{name} {cmdname} ran", "count": 0},
            command=f"{name} {cmdname}",
        )

        cli_py = f'''"""{name} plugin -- foundation-shaped, capability-declared."""
from pathlib import Path

from bigbang.core.cli_ux import examples_epilog
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit

app = make_plugin_app(
    "{name}",
    "{help_text}",
    examples=["scout --json {name} {cmdname}", "scout {name} --help"],
)


@app.command(
    "{cmdname}",
    epilog=examples_epilog(["scout --json {name} {cmdname}"]),
)
def {cmdname}():
    """{cmdname.capitalize()} -- respects the foundation contract."""
    mf = Path(__file__).parent / "manifest.yaml"
    emit(
        ok(
            {{"message": "{name} {cmdname} ran", "count": 0}},
            command="{name} {cmdname}",
            example="scout --json {name} {cmdname}",
            discover="scout skill show scout",
        ),
        command="{name} {cmdname}",
    )


def register(root):
    root.add_typer(app, name="{name}")
'''

        manifest = f"""name: {name}
version: 0.7.0
description: {name} -- foundation-shaped Scout plugin
capabilities:
  network:
    enabled: false
    domains: []
  filesystem:
    write: false
    paths: []
  secrets:
    allow: []
"""

        verified_note = ""
        if phase == 5:
            # anneal: add the verification checklist that makes it high-quality
            verified_note = f"""
Verification (what a reviewer checks before this ships):
  1. `make_plugin_app(...)` builds the sub-app -- present.
  2. every command ends in `emit(ok(...), command=...)` -- present.
  3. `def register(root): root.add_typer(app, name="{name}")` -- present, so the
     loader (bigbang.core.plugin_loader) auto-discovers it.
  4. manifest declares capabilities default-deny -- network.enabled=false,
     filesystem.write=false, secrets.allow=[]. Opt in only what's needed.
  5. `scout --json {name} {cmdname}` emits a valid envelope:
```json
{_dumps(sample_env)}
```
"""

        text = f"""### Task: build a new scout plugin `{name}` with a `{cmdname}` command.

Scaffold it, then fill in the foundation contract. Start from:
    scout system scaffold {name}

That writes `bigbang/plugins/{name}/cli.py` and a default-deny manifest. The
finished `cli.py`:

```python
{cli_py}```

The manifest (`bigbang/plugins/{name}/manifest.yaml`) -- capabilities default to
deny; opt in only what the plugin truly needs:

```yaml
{manifest}```

Four load-bearing pieces every scout plugin needs:
  * `app = make_plugin_app(name, help, examples=[...])` -- the sub-app.
  * `@app.command("{cmdname}")` -- the command, emitting via the contract.
  * `emit(ok(data, command=...))` -- machine-readable success under `--json`.
  * `def register(root): root.add_typer(app, name="{name}")` -- how the loader
    mounts it, so `scout {name} {cmdname}` works.
{verified_note}
Run it: `scout --json {name} {cmdname}` -> a success envelope. Discover the
contract any time with `scout skill show scout`.

Source: scout_cli/build doc {idx} -- P{phase} deliberate, building with scout.
"""
        return self.doc(
            text=text,
            task_type="deliberate",
            concept="scout_plugin_build",
            phase=phase,
            source="scout_cli/build",
        )


if __name__ == "__main__":
    run_cli(ScoutCliGenerator)
