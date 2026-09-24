"""atlas-outcomes: System One place decisions labelled by recorded futures.

Stdlib only. Stages: harvest (USGS daily flow + IEM VTEC flood-warning
polygons) -> features (per gauge-day, only what was known at the end of day t)
-> curate (strict jev records, time-split holdout, manifest) -> baseline
(CPU logistic regression vs persistence and climatology). Labels are what
happened next (provenance tier outcome-real); see README.md.
"""

SCHEMA_ID = "jev-decision-schema-1.0.0"
PACK_VERSION = "atlas-outcomes-1"
PROVENANCE_TIER = "outcome-real"
