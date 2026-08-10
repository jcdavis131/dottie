---
generated_by: scripts/business/generators/ops_digest.py
generated_at: "2026-08-10T02:28:02+00:00"
classification: REAL
method: >-
  Counts and copied figures from the monitor scoreboard JSON, open-checkbox
  count from TODO.md, and a repo-root self-test file count; no item is
  enumerated or ranked and no absent value is filled.
measured: true
sources:
  - path: "workspace/artifacts/monitor/scoreboard.json"
    sha256: "9c7c2e015dcdaa1f588a9631fcf56db4425de1316ea59e803153f351c828d6e6"
  - path: "TODO.md"
    sha256: "693727124a5126ca38f47af889c0209900c2f032401eca9aada966acda8ef524"
---

# Operations digest

## Scoreboard summary

Agents recorded: 11. Total events: 749.
OK-rate range: 0.68 (minimum) to 1.0 (maximum). Figures are copied from the scoreboard artifact; only the minimum and maximum are derived.

## Open work

Open checkbox lines (`- [ ]`) in TODO.md: 123.
TODO.md directs open-work triage to HANDOFF.md ("Open, needing an operator decision").

## Test inventory

repo-root self-test files: 5 (scripts/test_*.py, counted at generation time)
