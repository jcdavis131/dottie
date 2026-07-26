# Solo personal project, no connection to employer, built with public/free-tier only
"""Read-only ingesters: real substrate -> typed nodes/edges.

Every ingester (a) opens its source strictly read-only, (b) tolerates an
absent source honestly (returns zero counts, never fabricates), and (c) stamps
each node/edge with a citation back into the source (``source_ref``).

Sources and what they become:

    trainer JSONL metrics   -> run / phase / checkpoint / event nodes,
                               ``preceded_by`` temporal chains
    live-status feed        -> snapshot / run / site / container / event /
                               promotion / baseline nodes; loss-spike and
                               step-reemit anomaly events mined from the
                               real lm_loss series
    ledger COPY (sqlite)    -> experiment / state / failure_class / hint /
                               vlevel / verdict nodes (the DeepRefine target)
    steer_audit.jsonl       -> steer_directive / steer_ack nodes
    incident seed + docs    -> incident / fix / policy / container nodes,
                               with doc:line anchors re-verified at ingest
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dottie.kg import taxonomy
from dottie.kg.store import GraphStore, open_source_ro

# Ledger states that mean "validation eventually passed" (the candidate reached
# training). attempts>0 on such a row = the self-correction loop RESOLVED a
# validation failure — but which class it resolved is not logged today. That
# observability gap is exactly what the DeepRefine patch proposal closes.
_PAST_VALIDATION_STATES = frozenset(
    {"rejected", "sota", "failed_training", "ready_for_training", "evaluation_pending"}
)

#: Trainer JSONL events that become graph nodes (steps are summarized, not
#: exploded into thousands of nodes — computational efficiency is the point).
_NODE_EVENTS = frozenset(
    {
        "model_built",
        "phase_enter",
        "checkpoint",
        "done",
        "branch_forked",
        "resumed",
        "ckpt_rotated",
        "error",
        "crash",
    }
)


# ---------------------------------------------------------------------------
# trainer/factory JSONL event stream
# ---------------------------------------------------------------------------


def ingest_trainer_metrics(
    store: GraphStore, path: str | Path, run_key: str | None = None
) -> dict[str, int]:
    """One JSONL metrics file -> a run node + event/phase/checkpoint subgraph."""
    p = Path(path)
    if not p.exists():
        return {"runs": 0, "events": 0, "skipped_missing": 1}
    run_key = run_key or p.parent.name or p.stem
    run_id = f"run:{run_key}"
    src = "trainer_metrics"
    n_events = 0
    n_steps = 0
    first_lm: float | None = None
    last_lm: float | None = None
    last_step: int | None = None
    prev_event_id: str | None = None
    current_phase: str | None = None
    store.upsert_node(
        run_id, "run", f"training run {run_key}", {"metrics_file": str(p)}, src, p.name
    )
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = ev.get("event", "")
            ref = f"{p.name}:{lineno}"
            if name == "step":
                n_steps += 1
                lm = ev.get("lm")
                if isinstance(lm, (int, float)):
                    last_lm = float(lm)
                    if first_lm is None:
                        first_lm = float(lm)
                if isinstance(ev.get("step"), int):
                    last_step = ev["step"]
                continue
            if name not in _NODE_EVENTS:
                continue
            eid = f"event:{run_key}:{lineno}:{name}"
            props = {
                k: v
                for k, v in ev.items()
                if isinstance(v, (int, float, str, bool)) and k != "event"
            }
            props["event"] = name
            store.upsert_node(eid, "event", f"{name} ({run_key})", props, src, ref)
            store.add_edge(run_id, eid, "emitted", {}, src, ref)
            n_events += 1
            if name == "phase_enter":
                pname = str(ev.get("name") or f"p{ev.get('phase')}")
                phase_id = f"phase:{pname}"
                store.upsert_node(
                    phase_id, "phase", pname, {"seq": ev.get("seq")}, src, ref
                )
                store.add_edge(eid, phase_id, "entered_phase", {}, src, ref)
                current_phase = phase_id
            elif name == "checkpoint":
                step = ev.get("step")
                ck_id = f"checkpoint:{run_key}:step_{step}"
                store.upsert_node(
                    ck_id,
                    "checkpoint",
                    f"{run_key} step_{step}",
                    {"step": step},
                    src,
                    ref,
                )
                store.add_edge(eid, ck_id, "saved", {}, src, ref)
                if current_phase:
                    store.add_edge(ck_id, current_phase, "in_phase", {}, src, ref)
            elif name == "branch_forked":
                init = str(ev.get("init", ""))
                if init:
                    base = init.replace("\\", "/").rsplit("/", 1)[-1]
                    ck_id = f"checkpoint:artifact:{base}"
                    store.upsert_node(
                        ck_id, "checkpoint", base, {"path": init}, src, ref
                    )
                    store.add_edge(eid, ck_id, "forked_from", {}, src, ref)
            if current_phase and name != "phase_enter":
                store.add_edge(eid, current_phase, "in_phase", {}, src, ref)
            if prev_event_id:
                store.add_edge(eid, prev_event_id, "preceded_by", {}, src, ref)
            prev_event_id = eid
    store.upsert_node(
        run_id,
        "run",
        "",
        {
            "n_step_events": n_steps,
            "last_step": last_step,
            "first_lm_loss": first_lm,
            "last_lm_loss": last_lm,
        },
        src,
        p.name,
    )
    store.commit()
    return {"runs": 1, "events": n_events, "steps_summarized": n_steps}


# ---------------------------------------------------------------------------
# published live-status feed (pipeline + hub + research)
# ---------------------------------------------------------------------------


def _series_anomalies(steps: list[Any], losses: list[Any]) -> list[dict[str, Any]]:
    """Mine the real lm_loss series for resume boundaries and loss spikes.

    * a non-increasing step value = the trainer re-emitted a step it had
      already passed -> a restart/resume boundary (observed live: the
      documented resume spike rewinds lr and losses jump hard)
    * lm_loss > 8x the min of the previous 8 points (and above an absolute
      floor) = a loss spike worth a node
    """
    out: list[dict[str, Any]] = []
    prev_step: float | None = None
    window: list[float] = []
    for i, (s, l) in enumerate(zip(steps, losses)):
        if not isinstance(s, (int, float)) or not isinstance(l, (int, float)):
            continue
        if prev_step is not None and s <= prev_step:
            out.append(
                {
                    "kind": "step_reemitted",
                    "index": i,
                    "step": s,
                    "lm_loss": l,
                    "note": "step value repeated/regressed -> restart or resume boundary",
                }
            )
        if len(window) >= 4:
            floor = min(window[-8:])
            if l > max(0.5, 8.0 * floor):
                out.append(
                    {
                        "kind": "loss_spike",
                        "index": i,
                        "step": s,
                        "lm_loss": l,
                        "recent_min": floor,
                    }
                )
        window.append(float(l))
        prev_step = float(s)
    return out


def ingest_live_status(store: GraphStore, path: str | Path) -> dict[str, int]:
    p = Path(path)
    if not p.exists():
        return {"snapshots": 0, "skipped_missing": 1}
    src = "live_status"
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        j = json.load(fh)
    counts = {
        "snapshots": 1,
        "sites": 0,
        "containers": 0,
        "events": 0,
        "anomalies": 0,
        "promotions": 0,
    }
    snap_key = str(j.get("published_utc") or j.get("updated_at") or p.stat().st_mtime)
    snap_id = f"snapshot:{snap_key}"
    pipeline = j.get("pipeline") or {}
    store.upsert_node(
        snap_id,
        "snapshot",
        f"live status {snap_key}",
        {
            "source": j.get("source"),
            "hostname": j.get("hostname"),
            "run_id": j.get("run_id"),
            "preset": pipeline.get("preset"),
            "mode": pipeline.get("mode"),
            "disk_free_gb": pipeline.get("disk_free_gb"),
        },
        src,
        p.name,
    )

    # -- the live trainer run (host-side mirror of /reports/metrics_mini.jsonl)
    trainer = pipeline.get("trainer") or {}
    last = trainer.get("last") or {}
    if last:
        preset = str(last.get("preset", "unknown"))
        run_key = f"{preset}_live"
        run_id = f"run:{run_key}"
        store.upsert_node(
            run_id,
            "run",
            f"live {preset} run",
            {
                "metrics_path": trainer.get("metrics_path"),
                "n_points": trainer.get("n_points"),
                "last_step": last.get("step"),
                "last_lm_loss": last.get("lm_loss"),
                "phase": last.get("phase"),
                "tok_s": last.get("tok_s"),
                "gpu_mem_mb": last.get("gpu_mem_mb"),
                "gpu_sm_mhz": last.get("gpu_sm_mhz"),
            },
            src,
            f"{p.name}:pipeline.trainer.last",
        )
        store.add_edge(snap_id, run_id, "observed", {}, src, p.name)
        phase_id = f"phase:p{last.get('phase')}"
        store.upsert_node(
            phase_id,
            "phase",
            f"p{last.get('phase')}",
            {},
            src,
            f"{p.name}:pipeline.trainer.last.phase",
        )
        store.add_edge(run_id, phase_id, "in_phase", {}, src, p.name)
        series = trainer.get("series") or {}
        anomalies = _series_anomalies(
            series.get("step") or [], series.get("lm_loss") or []
        )
        prev_eid: str | None = None
        for a in anomalies:
            eid = f"event:{run_key}:series_{a['index']}:{a['kind']}"
            ref = f"{p.name}:pipeline.trainer.series[{a['index']}]"
            store.upsert_node(
                eid, "event", f"{a['kind']} @step {a['step']}", a, src, ref
            )
            store.add_edge(run_id, eid, "emitted", {}, src, ref)
            if prev_eid:
                store.add_edge(eid, prev_eid, "preceded_by", {}, src, ref)
            prev_eid = eid
        counts["anomalies"] = len(anomalies)

    # -- site probes + history
    hub = j.get("hub") or {}
    history = hub.get("site_history") or {}
    if isinstance(history, dict):
        pass
    else:  # defensive: some exports keyed it differently
        history = {}
    for site in hub.get("sites") or []:
        name = site.get("name")
        if not name:
            continue
        sid = f"site:{name}"
        hist = history.get(name) or []
        ups = [h for h in hist if isinstance(h, dict) and h.get("up")]
        mss = [
            h["ms"]
            for h in hist
            if isinstance(h, dict) and isinstance(h.get("ms"), (int, float))
        ]
        store.upsert_node(
            sid,
            "site",
            str(site.get("url") or name),
            {
                "url": site.get("url"),
                "history_n": len(hist),
                "history_up_n": len(ups),
                "history_avg_ms": round(sum(mss) / len(mss), 1) if mss else None,
                "history_max_ms": max(mss) if mss else None,
            },
            src,
            f"{p.name}:hub.sites",
        )
        store.add_edge(
            snap_id,
            sid,
            "probed",
            {
                "http": site.get("http"),
                "ms": site.get("ms"),
                "up": site.get("up"),
            },
            src,
            f"{p.name}:hub.sites",
        )
        counts["sites"] += 1

    # -- fleet snapshot (shape is docker's own; guard every field)
    fleet = hub.get("fleet")
    entries: list[dict[str, Any]] = []
    if isinstance(fleet, list):
        entries = [e for e in fleet if isinstance(e, dict)]
    elif isinstance(fleet, dict):
        inner = fleet.get("containers")
        if isinstance(inner, list):
            entries = [e for e in inner if isinstance(e, dict)]
        else:
            entries = [dict(v, name=k) for k, v in fleet.items() if isinstance(v, dict)]
    for e in entries:
        name = e.get("name") or e.get("Name") or e.get("Names") or e.get("container")
        if not name:
            continue
        cid = f"container:{name}"
        props = {k: v for k, v in e.items() if isinstance(v, (int, float, str, bool))}
        store.upsert_node(
            cid, "container", str(name), props, src, f"{p.name}:hub.fleet"
        )
        store.add_edge(snap_id, cid, "observed", {}, src, f"{p.name}:hub.fleet")
        counts["containers"] += 1

    # -- recent factory events
    prev_eid = None
    for i, ev in enumerate(j.get("recent_events") or []):
        if not isinstance(ev, dict):
            continue
        kind = ev.get("event_type") or ev.get("level") or "event"
        eid = f"event:status:{i}:{kind}"
        store.upsert_node(
            eid,
            "event",
            str(ev.get("message", ""))[:120],
            {
                "level": ev.get("level"),
                "source": ev.get("source"),
                "timestamp": ev.get("timestamp"),
            },
            src,
            f"{p.name}:recent_events[{i}]",
        )
        store.add_edge(snap_id, eid, "reported", {}, src, p.name)
        if prev_eid:
            store.add_edge(eid, prev_eid, "preceded_by", {}, src, p.name)
        prev_eid = eid
        counts["events"] += 1

    # -- research baseline + promotion history (joins to ledger experiment ids)
    research = j.get("research") or {}
    baseline = research.get("baseline") or {}
    if baseline.get("metric_name"):
        bid = f"baseline:{baseline['metric_name']}"
        store.upsert_node(
            bid,
            "baseline",
            baseline["metric_name"],
            {
                "value": baseline.get("metric_value"),
                "sem": baseline.get("metric_sem"),
                "provenance": baseline.get("provenance"),
                "notes": str(baseline.get("notes", ""))[:200],
            },
            src,
            f"{p.name}:research.baseline",
        )
        store.add_edge(snap_id, bid, "observed", {}, src, p.name)
    for s in research.get("sota_history") or []:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        pid = f"promotion:{s['id']}"
        store.upsert_node(
            pid,
            "promotion",
            str(s.get("name", s["id"])),
            {
                "metric": s.get("metric"),
                "metric_name": s.get("metric_name"),
                "baseline_value": s.get("baseline_value"),
                "updated_ts": s.get("updated_ts"),
            },
            src,
            f"{p.name}:research.sota_history",
        )
        store.add_edge(
            pid,
            f"experiment:{s['id']}",
            "promoted",
            {},
            src,
            f"{p.name}:research.sota_history",
        )
        if baseline.get("metric_name"):
            store.add_edge(
                pid,
                f"baseline:{baseline['metric_name']}",
                "moved_baseline",
                {},
                src,
                p.name,
            )
        counts["promotions"] += 1
    store.commit()
    return counts


# ---------------------------------------------------------------------------
# research ledger (the safe COPY — never the live file; build.py enforces)
# ---------------------------------------------------------------------------


def ingest_ledger(store: GraphStore, ledger_path: str | Path) -> dict[str, int]:
    p = Path(ledger_path)
    if not p.exists():
        return {"experiments": 0, "skipped_missing": 1}
    src = "ledger"
    con = open_source_ro(p)
    counts = {"experiments": 0, "failure_classes": 0, "resolved_after_correction": 0}
    # hint + failure-class scaffolding (mirrors validate._HINTS; see taxonomy.py)
    for cid, pattern, hint_summary in taxonomy.FAILURE_CLASSES:
        fc_id = f"failure_class:{cid}"
        h_id = f"hint:{cid}"
        store.upsert_node(
            fc_id,
            "failure_class",
            cid,
            {"pattern": pattern},
            "taxonomy",
            "dottie/kg/taxonomy.py",
        )
        store.upsert_node(
            h_id,
            "hint",
            hint_summary,
            {"mirrors": "dottie.research.validate._HINTS"},
            "taxonomy",
            "dottie/kg/taxonomy.py",
        )
        store.add_edge(
            fc_id, h_id, "hinted_by", {}, "taxonomy", "dottie/kg/taxonomy.py"
        )
    store.upsert_node(
        "failure_class:unclassified",
        "failure_class",
        "unclassified",
        {"pattern": None},
        "taxonomy",
        "dottie/kg/taxonomy.py",
    )
    for row in con.execute(
        "SELECT id, state, created_ts, updated_ts, hypothesis, implementation,"
        "       eval_verdict, failure, attempts FROM experiments"
    ):
        exp_id = f"experiment:{row['id']}"
        ref = f"ledger:experiments:{row['id']}"
        hyp: dict[str, Any] = {}
        impl: dict[str, Any] = {}
        try:
            hyp = json.loads(row["hypothesis"]) if row["hypothesis"] else {}
        except json.JSONDecodeError:
            pass
        try:
            impl = json.loads(row["implementation"]) if row["implementation"] else {}
        except json.JSONDecodeError:
            pass
        validation = impl.get("validation") if isinstance(impl, dict) else {}
        store.upsert_node(
            exp_id,
            "experiment",
            str(hyp.get("hypothesis_name", row["id"]))[:80],
            {
                "state": row["state"],
                "attempts": row["attempts"],
                "created_ts": row["created_ts"],
                "updated_ts": row["updated_ts"],
                "search_domain": hyp.get("search_domain"),
                "module_name": impl.get("module_name")
                if isinstance(impl, dict)
                else None,
                "validation_ok": (validation or {}).get("ok"),
            },
            src,
            ref,
        )
        state_id = f"state:{row['state']}"
        store.upsert_node(state_id, "state", row["state"], {}, src, ref)
        store.add_edge(exp_id, state_id, "in_state", {}, src, ref)
        counts["experiments"] += 1
        # Per-attempt failure->fix trajectories. validation.history (persisted
        # by implementation.py) records every self-correction attempt: level,
        # status, detail. Classifying each failed attempt and checking whether
        # the trajectory later cleared that class gives REAL hint-efficacy
        # data — the DeepRefine "judge" input, mined natively.
        hist = (validation or {}).get("history") or []
        if isinstance(hist, list) and hist:
            final_ok = any(isinstance(h, dict) and h.get("ok") is True for h in hist)
            traj: list[tuple[int, str, str, str]] = []  # (idx, cls, level, sig)
            for idx, h in enumerate(hist):
                if not isinstance(h, dict) or h.get("ok") is not False:
                    continue
                detail = str(h.get("detail", ""))
                # Prefer a first-class hint_id when the validate.py patch
                # proposal lands; fall back to the regex taxonomy mirror.
                cls = str(h.get("hint_id") or "") or taxonomy.primary_class(detail)
                sig = taxonomy.normalize_signature(taxonomy.salient_line(detail))
                traj.append((idx, cls, str(h.get("level", "")), sig))
            seen_classes: dict[str, dict[str, Any]] = {}
            for idx, cls, level, sig in traj:
                d = seen_classes.setdefault(
                    cls, {"attempt_indices": [], "level": level, "signature": sig}
                )
                d["attempt_indices"].append(idx)
            for cls, d in seen_classes.items():
                last_idx = max(d["attempt_indices"])
                later_other = any(i > last_idx for i, c, _, _ in traj if c != cls)
                cleared = final_ok or later_other
                # a first-class hint_id may name a class the scaffold didn't
                # (e.g. general_dry_run) — make sure its node exists
                store.upsert_node(
                    f"failure_class:{cls}", "failure_class", cls, {}, src, ref
                )
                store.add_edge(
                    exp_id,
                    f"failure_class:{cls}",
                    "struggled_with",
                    {
                        "attempt_indices": d["attempt_indices"],
                        "level": d["level"],
                        "signature": d["signature"],
                        "cleared": cleared,
                        "final_ok": final_ok,
                    },
                    src,
                    ref,
                )
        failure = row["failure"] or ""
        if failure:
            level = taxonomy.failing_level(failure)
            lvl_id = f"vlevel:{level}"
            store.upsert_node(lvl_id, "vlevel", level, {}, src, ref)
            store.add_edge(
                exp_id, lvl_id, "died_at", {"attempts": row["attempts"]}, src, ref
            )
            # The ledger's failure column is head-truncated ("...[head
            # truncated]..." observed live), which guts regex signal. The
            # FULL last-attempt detail survives in implementation.validation
            # .per_level — classify over both, faithful to the source.
            texts = [failure]
            per_level = (validation or {}).get("per_level") or {}
            if isinstance(per_level, dict):
                texts += [
                    str(v.get("detail", ""))
                    for v in per_level.values()
                    if isinstance(v, dict)
                ]
            corpus = "\n".join(texts)
            primary = taxonomy.primary_class(corpus)
            sig = taxonomy.normalize_signature(taxonomy.salient_line(corpus))
            store.add_edge(
                exp_id,
                f"failure_class:{primary}",
                "classified_as",
                {"signature": sig, "primary": True},
                src,
                ref,
            )
            for extra in taxonomy.classify(corpus)[1:]:
                store.add_edge(
                    exp_id,
                    f"failure_class:{extra}",
                    "classified_as",
                    {"primary": False},
                    src,
                    ref,
                )
            counts["failure_classes"] += 1
        elif row["state"] in _PAST_VALIDATION_STATES and (row["attempts"] or 0) > 0:
            # Validation failed at least once, then self-correction fixed it.
            # WHICH class was fixed is not recorded by today's ledger —
            # the observability gap the DeepRefine proposal closes.
            out_id = "outcome:validation_resolved_class_unlogged"
            store.upsert_node(
                out_id,
                "outcome",
                "validation resolved by self-correction (failure class unlogged)",
                {},
                src,
                ref,
            )
            store.add_edge(
                exp_id,
                out_id,
                "resolved_by_correction",
                {"attempts": row["attempts"]},
                src,
                ref,
            )
            counts["resolved_after_correction"] += 1
        verdict_raw = row["eval_verdict"]
        if verdict_raw:
            try:
                v = json.loads(verdict_raw)
            except json.JSONDecodeError:
                v = {}
            if isinstance(v, dict) and "promote" in v:
                v_id = "verdict:promoted" if v.get("promote") else "verdict:rejected"
                store.upsert_node(v_id, "verdict", v_id.split(":")[1], {}, src, ref)
                store.add_edge(
                    exp_id,
                    v_id,
                    "evaluated",
                    {
                        "metric": v.get("metric"),
                        "delta": v.get("delta"),
                        "baseline_value": v.get("baseline_value"),
                        "new_value": v.get("new_value"),
                    },
                    src,
                    ref,
                )
    row = con.execute("SELECT * FROM baseline WHERE singleton=1").fetchone()
    if row is not None:
        bid = f"baseline:{row['metric_name']}"
        store.upsert_node(
            bid,
            "baseline",
            row["metric_name"],
            {
                "value": row["metric_value"],
                "sem": row["metric_sem"],
                "notes": str(row["notes"] or "")[:200],
            },
            src,
            "ledger:baseline",
        )
    con.close()
    store.commit()
    return counts


# ---------------------------------------------------------------------------
# steer directives + acks (absent-tolerant: the audit log appears on first act)
# ---------------------------------------------------------------------------


def ingest_steer(store: GraphStore, path: str | Path) -> dict[str, int]:
    p = Path(path)
    if not p.exists():
        return {"directives": 0, "acks": 0, "skipped_missing": 1}
    src = "steer_audit"
    counts = {"directives": 0, "acks": 0}
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ref = f"{p.name}:{lineno}"
            key = str(obj.get("id") or obj.get("comment_id") or lineno)
            body = str(obj.get("body") or obj.get("directive") or "")
            is_ack = str(obj.get("type", "")).lower() == "ack" or body.startswith(
                "\U0001f916"
            )  # the 🤖 ack prefix
            ntype = "steer_ack" if is_ack else "steer_directive"
            nid = f"{ntype}:{key}"
            store.upsert_node(
                nid,
                ntype,
                body[:120],
                {
                    "status": obj.get("status"),
                    "ts": obj.get("ts"),
                    "action": obj.get("action"),
                },
                src,
                ref,
            )
            parent = obj.get("ack_of") or obj.get("in_reply_to")
            if is_ack and parent:
                store.add_edge(nid, f"steer_directive:{parent}", "acks", {}, src, ref)
            counts["acks" if is_ack else "directives"] += 1
    store.commit()
    return counts


# ---------------------------------------------------------------------------
# documented incident history (seed file + doc-anchor verification)
# ---------------------------------------------------------------------------


def find_anchor(doc_text: str, anchor: str) -> tuple[bool, int]:
    """Whitespace-normalized search for ``anchor`` in ``doc_text``.

    Returns (found, 1-based line number of the match start). Wrapped markdown
    lines are handled by matching against the space-joined normalized text.
    """
    lines = doc_text.splitlines()
    offsets: list[tuple[int, int]] = []
    parts: list[str] = []
    pos = 0
    for i, ln in enumerate(lines, 1):
        norm = " ".join(ln.split())
        offsets.append((pos, i))
        parts.append(norm)
        pos += len(norm) + 1
    norm_doc = " ".join(parts)
    target = " ".join(anchor.split())
    if not target:
        return False, 0
    idx = norm_doc.find(target)
    if idx < 0:
        return False, 0
    line_no = 1
    for start, ln_no in offsets:
        if start <= idx:
            line_no = ln_no
        else:
            break
    return True, line_no


def ingest_incidents(
    store: GraphStore, seed_path: str | Path, docs_root: str | Path
) -> dict[str, int]:
    """Curated incident seed -> incident subgraph, anchors re-verified in docs.

    The seed records WHAT the handoff docs say, with an exact quote (anchor).
    Ingest re-reads the doc and confirms the quote still exists; a failed
    match sets ``anchor_verified: false`` on the node — flagged, never
    silently dropped (confirm-why doctrine).
    """
    sp = Path(seed_path)
    root = Path(docs_root)
    if not sp.exists():
        return {"incidents": 0, "skipped_missing": 1}
    with sp.open("r", encoding="utf-8") as fh:
        seed = json.load(fh)
    src = "incidents"
    counts = {"incidents": 0, "policies": 0, "verified": 0, "unverified": 0}
    doc_cache: dict[str, str] = {}

    def _doc_text(rel: str) -> str:
        if rel not in doc_cache:
            fp = root / rel
            doc_cache[rel] = (
                fp.read_text(encoding="utf-8", errors="replace") if fp.exists() else ""
            )
        return doc_cache[rel]

    def _cite(rel: str, anchor: str) -> tuple[str, bool]:
        found, line = find_anchor(_doc_text(rel), anchor)
        return (f"{rel}:L{line}" if found else rel), found

    for inc in seed.get("incidents", []):
        key = inc["key"]
        iid = f"incident:{key}"
        ref, ok = _cite(inc["doc"], inc.get("anchor", ""))
        counts["verified" if ok else "unverified"] += 1
        store.upsert_node(
            iid,
            "incident",
            inc.get("title", key),
            {
                "class": inc.get("class"),
                "severity": inc.get("severity"),
                "date": inc.get("date"),
                "root_cause": inc.get("root_cause"),
                "quote": inc.get("anchor"),
                "anchor_verified": ok,
            },
            src,
            ref,
        )
        counts["incidents"] += 1
        if inc.get("container"):
            cid = f"container:{inc['container']}"
            store.upsert_node(cid, "container", inc["container"], {}, src, ref)
            store.add_edge(iid, cid, "affects", {}, src, ref)
        if inc.get("phase"):
            pid = f"phase:{inc['phase']}"
            store.upsert_node(pid, "phase", inc["phase"], {}, src, ref)
            store.add_edge(iid, pid, "in_phase", {}, src, ref)
        if inc.get("checkpoint"):
            ck = f"checkpoint:{inc['checkpoint']}"
            store.upsert_node(ck, "checkpoint", inc["checkpoint"], {}, src, ref)
            store.add_edge(iid, ck, "parked_at", {}, src, ref)
        if inc.get("resolution"):
            fid = f"fix:{key}"
            store.upsert_node(
                fid,
                "fix",
                inc["resolution"][:120],
                {"commit": inc.get("fix_commit"), "detail": inc.get("resolution")},
                src,
                ref,
            )
            store.add_edge(iid, fid, "resolved_by", {}, src, ref)
        if inc.get("failed_fix"):
            nfid = f"fix:{key}:failed"
            store.upsert_node(
                nfid,
                "fix",
                inc["failed_fix"][:120],
                {"outcome": "failed", "detail": inc["failed_fix"]},
                src,
                ref,
            )
            store.add_edge(iid, nfid, "fix_attempt_failed", {}, src, ref)
        if inc.get("steer"):
            steer_ref, steer_ok = _cite(inc["doc"], inc.get("steer_anchor", ""))
            sid = f"steer_directive:doc:{key}"
            store.upsert_node(
                sid,
                "steer_directive",
                inc["steer"][:120],
                {"pending": True, "anchor_verified": steer_ok},
                src,
                steer_ref,
            )
            store.add_edge(iid, sid, "steered_by", {}, src, steer_ref)
    for pol in seed.get("policies", []):
        key = pol["key"]
        pid = f"policy:{key}"
        ref, ok = _cite(pol["doc"], pol.get("anchor", ""))
        counts["verified" if ok else "unverified"] += 1
        store.upsert_node(
            pid,
            "policy",
            pol.get("title", key),
            {
                "quote": pol.get("anchor"),
                "anchor_verified": ok,
                "rule": pol.get("rule"),
            },
            src,
            ref,
        )
        counts["policies"] += 1
        for target in pol.get("governs", []):
            store.upsert_node(
                target, target.split(":", 1)[0], target.split(":", 1)[1], {}, src, ref
            )
            store.add_edge(pid, target, "governs", {}, src, ref)
    store.commit()
    return counts
