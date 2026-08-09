---
generated_by: scripts/business/generators/ops_digest.py
generated_at: "2026-08-09T03:06:48+00:00"
classification: REAL
method: >-
  Counts and copied figures from the monitor scoreboard JSON, open-checkbox
  count from TODO.md, and a repo-root self-test file count; no item is
  enumerated or ranked and no absent value is filled.
measured: true
sources:
  - path: "workspace/artifacts/monitor/scoreboard.json"
    sha256: "48d92653c741d8b22898aa882ede7ce2a92b3b151bfe857f2861c0a3764facd6"
  - path: "TODO.md"
    sha256: "693727124a5126ca38f47af889c0209900c2f032401eca9aada966acda8ef524"
---

# Operations digest

## Scoreboard summary

Agents recorded: 5. Total events: 15.
OK-rate range: 1.0 (minimum) to 1.0 (maximum). Figures are copied from the scoreboard artifact; only the minimum and maximum are derived.

## Open work

Open checkbox lines (`- [ ]`) in TODO.md: 123.
TODO.md directs open-work triage to HANDOFF.md ("Open, needing an operator decision").

## Test inventory

repo-root self-test files: 5 (scripts/test_*.py, counted at generation time)
