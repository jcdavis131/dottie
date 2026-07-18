---
name: openwiki-sync
description: Sync OpenWiki personal wiki (~/.openwiki/wiki) into S2 Slow hl300 verbalizable
  memory
triggers:
- openwiki
- wiki
- personal brain
- sync wiki
- ~/.openwiki
j_space_target: S2
half_life: 300
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes:
- family-brain-wiki
- jspace-inspector
requires:
- memory-router
- safety-scanner
complementary:
- family-brain-wiki
---

# OpenWiki Sync

Scans `~/.openwiki/wiki` (or a supplied `wiki_path`) for markdown, extracts heading and
`[[wikilink]]` concepts, and reports concept counts for S2 ingestion. The live S2
reportability-mass readout is not wired, so real mode fails honestly with filesystem
diagnostics only. Run with `python -m skills.loader run openwiki-sync --wiki-path <dir>`.

Solo personal project, no connection to employer, built with public/free-tier only.
