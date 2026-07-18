---
name: family-brain-wiki
description: Bridge Family Brain OS WikiTab pages (JSON export of family-brain-wiki-pages:v1) into S2
triggers:
- family
- wiki
- family-brain
- davis
j_space_target: S2
half_life: 300
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes: []
requires:
- openwiki-sync
- memory-router
complementary:
- openwiki-sync
- jspace-inspector
---

# Family Brain Wiki Bridge

Ingests WikiTab pages from a JSON export of the browser localStorage key
`family-brain-wiki-pages:v1` (pass `export_path=/path/to/export.json`); without an export it
falls back to a filesystem scan, then to generated sample pages. Real S2 injection is not
wired, so real mode refuses honestly; mock mode reports a clearly simulated mass.

Solo personal project, no connection to employer, built with public/free-tier only.
