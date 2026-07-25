# Solo personal project, no connection to employer, built with public/free-tier only
"""`scout ollama` — ChatGPT Plus / hosted LLM API replacement, local (openswap #17).

The subscription and the metered key, both deleted: inference happens against
an ollama daemon on THIS box's loopback interface, the transport is stdlib
urllib (no httpx, no SDK, no new dependency), and the manifest's secrets
allowlist is empty because a local daemon has no API key to hold. The one real
I/O lives here in _request; every judgment — endpoint resolution, catalog
parsing, model choice, degradation, the ledger, diagnostics — is in
bigbang/core/ollama.py so the pipeline is testable fully offline.

Two honesty rules drive the design and are enforced, not promised.

(1) When no daemon answers, `run` degrades to template assembly and SAYS so: the
completion's first line is the DEGRADED banner, the body carries the literal
"NOT ANSWERED" marker, `source` reads "template", `degraded` is true, and
--fail-on-degraded turns it into exit 1 for cron/CI. It never emits
model-shaped prose that no model produced.

(2) It never assumes GPU. This box runs qwen3:8b with NUM_GPU=0 — resident in
SYSTEM RAM — so placement is read only from /api/ps's size_vram and a missing
key reports "unknown", never "gpu" (core.ollama.placement). `models` also picks
cost-first: an explicit tag, else a model already resident, else the SMALLEST
installed one, because on CPU the biggest model is the one that never finishes.

Policy: every candidate endpoint is gated before the socket opens (_gate) —
against this plugin's manifest allowlist, which ships loopback-only, and
additionally against the operator's persisted allowlist for anything off
loopback, since an off-box endpoint is a hosted API in disguise. The native
tier is the real `ollama` binary on PATH; llama-cli and llamafile are surfaced
by `detect` for awareness and NEVER executed. Continuous liveness monitoring is
deliberately absent: uptime (#2) already probes /api/version as a fleet target
with damping and incidents, and a second monitor would be a parallel store of
the same fact.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import typer

from bigbang.core import ollama, openswap
from bigbang.core.cli_ux import examples_epilog, fail_agent, read_stdin_text
from bigbang.core.contract import make_plugin_app, ok
from bigbang.core.output import emit
from bigbang.core.policy import (
    enforce_or_raise,
    enforce_user_url_or_raise,
    load_manifest,
)

FALLBACK_SCOPE = (
    "the pure-stdlib tier CANNOT answer questions and does not pretend to: with "
    "no daemon reachable, `run` returns template assembly built only from the "
    "caller's own words (verbatim echo, keyword intent match, salient terms, a "
    "labelled scaffold) under a DEGRADED banner, marked degraded=true and "
    "gate-able with --fail-on-degraded; endpoint resolution with per-attempt "
    "evidence, catalog/residency parsing, placement honesty, the sqlite usage "
    "ledger and the family diagnostics all work in this tier — real inference "
    "does not, because no stdlib core can conjure it"
)
INSTALL_HINT = (
    "install ollama (ollama.com/download), `ollama pull qwen3:8b`, then "
    "`ollama serve` — it answers on 127.0.0.1:11434 and needs no API key, "
    "which is the entire point of #17"
)

app = make_plugin_app(
    "ollama",
    "Run prompts on the local ollama daemon (ChatGPT Plus-class), stdlib-only "
    "urllib to loopback — degrades to labelled template assembly, never to a "
    "hosted API",
    examples=[
        "scout --json ollama detect",
        "scout --json ollama models",
        "scout ollama run --prompt 'summarize the ratchet decision'",
        "scout --json ollama run --prompt 'why is step time 35 min' --fail-on-degraded",
        "scout --json ollama usage",
    ],
)

_MANIFEST: dict | None = None


def _manifest() -> dict:
    # lazy: plugin modules import on every CLI invocation, yaml only when used
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = load_manifest(Path(__file__).parent)
    return _MANIFEST


def _capability() -> dict:
    # The native tier here is REAL (unlike certmon/statuspage): the `ollama`
    # binary on PATH is a genuine superset of this core. It is still not the
    # same fact as "the daemon answers" — an installed binary with `serve`
    # stopped degrades — so detect() reports the tier and the endpoint probe
    # side by side and never lets one imply the other. llama-cli/llamafile are
    # surfaced for awareness and never executed.
    native = openswap.probe_binary("ollama", probe_args=("--version",))
    extras = {
        "llama-cli": openswap.probe_binary("llama-cli", probe_args=("--version",)),
        "llamafile": openswap.probe_binary("llamafile", probe_args=("--version",)),
    }
    return openswap.capability_report(
        "ollama",
        native=native,
        extras=extras,
        fallback_scope=FALLBACK_SCOPE,
        install_hint=INSTALL_HINT,
    )


def _db_path(db: str | None) -> Path:
    # its own file next to the other openswap stores, relative to CWD — no
    # HOME-layout assumption, so a repo checkout carries its own ledger
    return Path(db) if db else ollama.DB_REL


def _gate(base: str) -> None:
    """Default-deny before any socket opens, per candidate endpoint.

    Off-loopback bases clear the operator's persisted allowlist FIRST so the
    denial names the operator's own file (the certmon ad-hoc-host doctrine),
    then the manifest — which ships loopback-only — has the final say.
    """
    if not ollama.is_loopback(base):
        enforce_user_url_or_raise(base, context="ollama endpoint off loopback")
    enforce_or_raise(_manifest(), "network", base)


def _request(
    base: str,
    path: str,
    *,
    payload: dict | None = None,
    timeout: float = 10.0,
) -> dict:
    """The ONE real I/O in this plugin: urllib to the local daemon. Never raises.

    Returns {"status": int|None, "json": obj|None, "error": str|None}. A 4xx/5xx
    body is still parsed (ollama reports "model not found" that way) so the core
    can quote the daemon's own words instead of a bare status. Connection
    refused — the everyday case when `ollama serve` is not running — comes back
    as status None with the exception class visible, which is what separates a
    stopped daemon from a wrong port in the degradation reason.
    """
    url = f"{base}{path}"
    data = ollama.dumps(payload) if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": "scout-ollama"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    # S310: loopback http by design (ollama serves plain http); the scheme is
    # normalized to http(s) in core.normalize_base and every base is _gate()d
    req = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            raw = r.read(8_000_000)
            return {"status": int(r.status), "json": _decode(raw), "error": None}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(1_000_000)
        except Exception:
            raw = b""
        return {"status": int(e.code), "json": _decode(raw), "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": None, "json": None, "error": f"{type(e).__name__}: {e}"}


def _decode(raw: bytes) -> object | None:
    """Response bytes -> JSON, or None when the body is not JSON at all."""
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None


def _resolve(base: str | None, *, timeout: float, path: str, command: str) -> dict:
    """Gate then probe each candidate endpoint; the first 200 wins.

    An explicit --base is validated loudly (a typo there is a user error), while
    env-provided candidates are skipped silently by candidate_bases — an
    exported OLLAMA_HOST typo must not take out the loopback default.
    """
    if base:
        try:
            base = ollama.normalize_base(base)
        except ValueError as e:
            fail_agent(
                f"bad --base: {e}",
                command=command,
                example="scout --json ollama detect --base 127.0.0.1:11434",
            )
    bases = ollama.candidate_bases(base)

    def probe(b: str, p: str) -> dict:
        _gate(b)
        return _request(b, p, timeout=timeout)

    return ollama.resolve(probe, bases, path=path)


def _resident(base: str | None, *, timeout: float) -> list[dict]:
    """Resident models per /api/ps — the ONLY source of placement truth."""
    if not base:
        return []
    return ollama.parse_loaded(_request(base, ollama.PS_PATH, timeout=timeout).get("json"))


def _prompt_text(prompt: str | None, command: str) -> str:
    """--prompt, else stdin. An empty prompt is a user error, not an empty answer."""
    if prompt and prompt.strip():
        return prompt
    try:
        return read_stdin_text()
    except Exception as e:  # empty stdin, closed pipe, decode failure
        fail_agent(
            f"no prompt: pass --prompt or pipe text on stdin ({e})",
            command=command,
            example='scout --json ollama run --prompt "why is step time 35 min"',
            discover="scout ollama models",
        )
        raise typer.Exit(code=1) from e  # fail_agent already exited


def _options(num_predict: int | None) -> dict | None:
    """ollama's own option block, or None when the caller tuned nothing."""
    return {"num_predict": int(num_predict)} if num_predict else None


def _record(rec: dict, path: Path) -> None:
    """Persist one usage row — fs_write is enforced here, at the call site."""
    enforce_or_raise(_manifest(), "fs_write_arg", str(path))
    conn = ollama.open_ledger(path)
    rec["ledger_id"] = ollama.record_completion(conn, rec)
    conn.close()


def _answer_payload(
    rec: dict, *, why: str, loaded: list[dict], recorded: str | None, diags: list[dict]
) -> dict:
    """The `run` envelope: provenance first, then the text, then the receipts.

    source/degraded lead deliberately — an agent reading this must not have to
    infer from the prose whether a model was involved.
    """
    return {
        "source": rec["source"],
        "degraded": rec["degraded"],
        "text": rec["text"],
        "model": rec["model"],
        "base": rec["base"],
        "selection_reason": why,
        "resident": loaded,
        "tokens": {
            "prompt": rec["prompt_tokens"],
            "eval": rec["eval_tokens"],
            "tok_per_s": rec["tok_per_s"],
        },
        "elapsed_s": rec["elapsed_s"],
        "recorded": recorded,
        "prompt_sha256": rec["prompt_sha256"],
        "diagnostics": diags,
        "summary": openswap.summarize(diags),
    }


def _severity_gate(fail_on: str | None, command: str) -> int | None:
    """Validate --fail-on BEFORE any work; returns the rank to gate on, or None.

    Up front on purpose: emitting a success envelope and only then rejecting the
    flag would teach an agent that the run happened.
    """
    if fail_on is None:
        return None
    if fail_on not in openswap.SEVERITIES:
        fail_agent(
            f"--fail-on must be one of {'|'.join(openswap.SEVERITIES)}, got {fail_on!r}",
            command=command,
            example="scout --json ollama detect --fail-on warning",
        )
    return openswap.severity_rank(fail_on)


def _tripped(diags: list[dict], rank: int | None) -> bool:
    """True when any diagnostic is at or above the gate's severity."""
    if rank is None:
        return False
    return any(openswap.severity_rank(d["severity"]) <= rank for d in diags)


@app.command("hello", epilog=examples_epilog(["scout --json ollama hello"]))
def hello():
    """Smoke check — is the ollama surface alive? (Says nothing about the daemon.)"""
    emit(
        ok(
            {"ready": True, "plugin": "ollama", "needs_api_key": False},
            command="ollama hello",
            example="scout --json ollama detect",
            discover="scout ollama models",
        ),
        command="ollama hello",
    )


@app.command(
    "detect",
    epilog=examples_epilog(
        [
            "scout --json ollama detect",
            "scout --json ollama detect --base 127.0.0.1:11434",
            "scout --json ollama detect --fail-on warning",
        ]
    ),
)
def detect(
    base: str | None = typer.Option(
        None, "--base", help=f"endpoint (default {ollama.DEFAULT_BASES[0]} or $OLLAMA_HOST)"
    ),
    timeout: float = typer.Option(5.0, "--timeout", help="probe timeout, seconds"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 at/above this severity (unreachable = warning)"
    ),
):
    """Capability tier AND whether the daemon answers — two different facts."""
    rank = _severity_gate(fail_on, "ollama detect")
    res = _resolve(base, timeout=timeout, path=ollama.VERSION_PATH, command="ollama detect")
    loaded = _resident(res["base"], timeout=timeout)
    diags = ollama.endpoint_diagnostics(res, loaded=loaded)
    emit(
        ok(
            {
                "capability": _capability(),
                "endpoint": {
                    "base": res["base"],
                    "reachable": res["reachable"],
                    "version": ollama.parse_version(res["payload"]),
                    "tried": res["tried"],
                    "note": "a binary on PATH is not a daemon that answers",
                },
                "resident": loaded,
                "monitoring": "continuous liveness lives in uptime (#2), not here",
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="ollama detect",
            example="scout --json ollama models",
            discover="scout ollama models",
        ),
        command="ollama detect",
    )
    if _tripped(diags, rank):
        raise typer.Exit(code=1)


@app.command(
    "models",
    epilog=examples_epilog(
        [
            "scout --json ollama models",
            "scout --json ollama models --fail-on warning",
        ]
    ),
)
def models_cmd(
    base: str | None = typer.Option(None, "--base", help="endpoint override"),
    timeout: float = typer.Option(10.0, "--timeout", help="request timeout, seconds"),
    fail_on: str | None = typer.Option(
        None, "--fail-on", help="exit 1 at/above this severity"
    ),
):
    """Installed models, what is resident (and where), and what `run` would pick."""
    rank = _severity_gate(fail_on, "ollama models")
    res = _resolve(base, timeout=timeout, path=ollama.TAGS_PATH, command="ollama models")
    catalog = ollama.parse_models(res["payload"])
    loaded = _resident(res["base"], timeout=timeout)
    if res["reachable"]:
        chosen, why = ollama.pick_model(catalog, loaded=loaded)
    else:
        # an empty catalog we never got to ask for is NOT "no models installed"
        chosen, why = None, ollama.unreachable_reason(res)
    diags = ollama.endpoint_diagnostics(res, loaded=loaded, models=catalog)
    emit(
        ok(
            {
                "base": res["base"],
                "reachable": res["reachable"],
                "tried": res["tried"],
                "models": catalog,
                "count": len(catalog),
                "resident": loaded,
                "would_pick": {"model": chosen, "reason": why},
                "placement_note": "placement comes from /api/ps only — never assumed",
                "diagnostics": diags,
                "summary": openswap.summarize(diags),
            },
            command="ollama models",
            example='scout --json ollama run --prompt "hello"',
            discover="scout ollama detect",
        ),
        command="ollama models",
    )
    if _tripped(diags, rank):
        raise typer.Exit(code=1)


@app.command(
    "run",
    epilog=examples_epilog(
        [
            "scout ollama run --prompt 'summarize the ratchet decision'",
            "echo 'why did fp32 lose?' | scout --json ollama run",
            "scout --json ollama run --prompt 'x' --model qwen3:8b --num-predict 256",
            "scout --json ollama run --prompt 'x' --fail-on-degraded",
        ]
    ),
)
def run_cmd(
    prompt: str | None = typer.Option(None, "--prompt", help="prompt (omit to read stdin)"),
    model: str | None = typer.Option(
        None, "--model", help="exact tag or unique prefix; default is chosen AND explained"
    ),
    system: str | None = typer.Option(None, "--system", help="system preamble"),
    base: str | None = typer.Option(None, "--base", help="endpoint override"),
    timeout: float = typer.Option(
        120.0, "--timeout", help="seconds — CPU-only boxes generate slowly"
    ),
    num_predict: int | None = typer.Option(
        None, "--num-predict", help="cap generated tokens (the CPU-box safety valve)"
    ),
    db: str | None = typer.Option(
        None, "--db", help=f"usage ledger (default {ollama.DB_REL})"
    ),
    record: bool = typer.Option(True, "--record/--no-record", help="persist the usage row"),
    fail_on_degraded: bool = typer.Option(
        False, "--fail-on-degraded", help="exit 1 when the answer was template assembly"
    ),
):
    """One completion — or an honestly labelled template when nothing answers."""
    text = _prompt_text(prompt, "ollama run")
    res = _resolve(base, timeout=timeout, path=ollama.TAGS_PATH, command="ollama run")
    chosen, why = None, ollama.unreachable_reason(res)
    loaded: list[dict] = []
    if res["reachable"]:
        loaded = _resident(res["base"], timeout=timeout)
        chosen, why = ollama.pick_model(
            ollama.parse_models(res["payload"]), want=model, loaded=loaded
        )
        if chosen is None and model:
            # a named-but-absent model is a wrong flag, not a degradation:
            # substituting a different model would be the quiet lie
            fail_agent(why, command="ollama run", example="scout --json ollama models")
    rec = ollama.complete(
        lambda b, p, body: _request(b, p, payload=body, timeout=timeout),
        text,
        model=chosen,
        base=res["base"],
        system=system,
        options=_options(num_predict),
        reason=why,
    )
    path = _db_path(db)
    if record:
        _record(rec, path)
    diags = ollama.to_diagnostics([rec])
    emit(
        ok(
            _answer_payload(
                rec,
                why=why,
                loaded=loaded,
                recorded=str(path) if record else None,
                diags=diags,
            ),
            command="ollama run",
            example="scout --json ollama usage",
            discover="scout ollama models",
        ),
        command="ollama run",
    )
    if fail_on_degraded and rec["degraded"]:
        raise typer.Exit(code=1)


@app.command(
    "usage",
    epilog=examples_epilog(
        [
            "scout --json ollama usage",
            "scout --json ollama usage --limit 5",
            "scout --json ollama usage --db .scout/ollama.db",
        ]
    ),
)
def usage_cmd(
    db: str | None = typer.Option(None, "--db", help="usage ledger path"),
    limit: int = typer.Option(10, "--limit", help="recent records to include"),
):
    """The honesty audit from the ledger: how often did this box actually think?

    No network, and no transcripts to read — the ledger stores prompt hashes and
    lengths, never prompt or completion text.
    """
    path = _db_path(db)
    if not path.exists():
        fail_agent(
            f"no usage ledger at {path} — run a completion first",
            command="ollama usage",
            example='scout --json ollama run --prompt "hello"',
        )
    conn = ollama.open_ledger(path)
    rollup = ollama.usage(conn)
    recent = ollama.history(conn, limit=limit)
    conn.close()
    emit(
        ok(
            {
                "db": str(path),
                "stores_prompts": False,
                "usage": rollup,
                "recent": recent,
            },
            command="ollama usage",
            example='scout --json ollama run --prompt "hello" --fail-on-degraded',
            discover="scout ollama detect",
        ),
        command="ollama usage",
    )


def register(root):
    root.add_typer(app, name="ollama")
