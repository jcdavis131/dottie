# Provenance

- **Source**: `~/workspace/your_files/selective-training-annealing-init-full-writeup.md`
- **Source SHA-256**: `c29587ffe0ad936c3040a3c83856a22a43ae31c1eb61b9ba56ec8bed530acdb2`
- **Source compiled**: 2026-09-07 (per the writeup header; expands two
  deep-research reports into a publication-style writeup).
- **Source size**: 10,336 words / 1,532 lines.
- **Skill built**: 2026-09-16, prototype of a markdown-first
  paper-to-skill pipeline adapted from Paper2Agent's Paper2Skill
  (MIT-licensed reference; no reference code or text copied - method
  adapted, all prose original).
- **Method**: single distillation pass by the coordinator (Scout),
  then an independent verification pass by a fresh agent that did not
  write the package. Verification report: see verification notes
  below.
- **Compression**: ~10.3k source words -> ~4.9k skill words across
  SKILL.md + 5 reference files. Detail intentionally shed; the source
  writeup remains authoritative for fine numbers.

## Verification

- Verifier: fresh subagent, distinct from the author, given the
  source path and the package path.
- Checks: every factual claim/number traces to the source; coverage
  of all four parts plus the executive summary; no invented content;
  evidence ratings not upgraded.
- **Status: PASS (2026-09-16).** ~60 spot-checked numbers across all
  four reference files traced to the source with no invented or wrong
  values; no evidence rating upgraded; coverage spans the executive
  summary and Parts I-IV. Two minor findings (one dropped rating on
  warmup-free training, one dropped four-part program enumeration in
  the closing) were fixed after the report.

## Limits

- Markdown-first adaptation: the reference Paper2Skill is PDF-centric
  with human review loops; this prototype skips that machinery.
- Single source document, not the ~90 underlying papers. Claims rest
  on the writeup's synthesis, not on re-read primary sources.
- Fine numerical detail should be checked against the source
  writeup, not quoted from this skill alone.
