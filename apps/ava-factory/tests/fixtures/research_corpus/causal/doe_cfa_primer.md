---
title: 'DOE-style Causal Factor Analysis primer (synthetic fixture)'
license: mit
source_url: 'fixture://tests/fixtures/research_corpus/causal/doe_cfa_primer.md'
sha256: fixture
origin_file: 'doe_cfa_primer.md'
---

Causal Factor Analysis (CFA) is an accident-investigation method used to identify
events and conditions that contributed to an undesired outcome. An EVENT is a
happened occurrence drawn as a rectangle. A CONDITION is a state that enabled or
influenced events, drawn as an oval. The main event line is drawn left to right
in chronological order. Supporting conditions attach above or below that line.

Benefits include validating the sequence of events, linking facts to management
systems, and producing a visual summary for the investigation report. Investigators
should prefer system-level corrective actions over person-blame when conditions
show control failures (for example unlocked energy sources, missing procedures,
or absent alarms).

For agentic assistants, the same structure applies to tool failures: unreachable
status endpoints, missing provenance labels, and reward pressure to sound fluent
are CONDITIONS; emitting a fabricated metric is an EVENT. The honest repair is to
refuse and surface the unreachable source, not to invent a number.
