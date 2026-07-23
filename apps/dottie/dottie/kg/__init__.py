# Solo personal project, no connection to employer, built with public/free-tier only
"""dottie.kg — a stdlib-only knowledge-graph layer over the org's own telemetry.

Entities and typed edges over substrate that already exists on this box:

    * trainer/factory event streams (JSONL metrics: phase transitions,
      checkpoints, resumes, done events, loss-spike anomalies)
    * the research ledger (experiments, failure classes, repair hints,
      promotions) — ALWAYS read from a safe COPY, never the live ledger
    * the published live-status feed (pipeline snapshot, site probes + history,
      fleet, research baseline)
    * steer directives + acks (steer_audit.jsonl, absent-tolerant)
    * the documented incident history (CURSOR_HANDOFF.md / HANDOFF.md), each
      incident carrying a doc:line citation that ingest re-verifies against
      the doc text (provenance-honest: unverifiable anchors are flagged,
      never silently dropped)

Design borrowed deliberately (see tasks/artifacts/kg_native_design.md):
    graphify   -> answers are graph paths with real file:line citations;
                  on-device, no accounts, no telemetry
    rootly     -> incidents as first-class nodes linked to services,
                  fixes, and policies; "what happened last time X broke?"
    deeprefine -> refinement of the hint/skill layer driven by mined
                  failure->fix paths, dry-run-first, operator-approved

Everything here is stdlib-only (sqlite3, json, re, argparse). Ingest is
strictly read-only over its sources; the graph is written to
apps/dottie/data/kg/ (gitignored, derived, rebuildable).
"""

from dottie.kg.store import GraphStore  # noqa: F401

__all__ = ["GraphStore"]
