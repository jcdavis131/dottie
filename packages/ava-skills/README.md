# ava-skills

> **Solo personal project, no connection to employer, built with public/free-tier only**

Skill system for Ava AGI Factory v6.4 — dynamic loading, J-Space routed (S1 Fast hl=8, S2 Slow hl=300, Critic hl=30, Planner hl=150, Router), half-life aware, openwiki-synced.

Inspired by `cursor-agent-skills` (42 skills) but purpose-built for Ava's Global Workspace architecture. Each skill is a markdown contract `SKILL.md` + typed Python module `skill.py` + tests.

## Quickstart

```bash
pip install -e .

python -m skills.loader list                # all skills in topological order, with metadata
python -m skills.loader graph               # Tool Graph (precedes/requires/complementary) + topo order
python -m skills.loader rerank "inspect jspace safety"   # wRRF-ranked skills for a query
python -m skills.loader run openwiki-sync --mode mock --wiki-path ~/.openwiki/wiki
python -m skills.loader run-graph --query "safety check then inspect jspace"
python -m skills.loader test                # smoke-run every skill in mock mode
```

## Skill Format

Frontmatter in SKILL.md:

```yaml
---
name: openwiki-sync
description: Sync openwiki personal wiki into S2 Slow slots
triggers: ["wiki", "openwiki", "personal brain"]
j_space_target: S2
half_life: 300
dependencies: []
version: 0.1.0
---
```

## 9 Starter Skills

Values below mirror each skill's `SKILL.md` frontmatter — the single source of truth
(`describe()` reads the manifest at runtime, so code and docs cannot drift).

| Skill | J-Target | hl | Purpose |
|---|---|---|---|
| jspace-inspector | Planner | 150 | Inspect S1/S2/Critic/Planner slots; real mode runs the 5 canonical J-tests via ava-open-harness |
| openwiki-sync | S2 | 300 | Sync ~/.openwiki/wiki into S2 verbalizable concepts |
| logic-prover | S2 | 300 | Synthetic logic corpus generation (truth tables + syllogisms, JSONL) |
| code-bench | S2 | 350 | Exec-verified Python generation |
| safety-scanner | Critic | 30 | Blackmail/leverage detection; AUC/AUPRC/FPR computed from each run's scores |
| memory-router | Router | 30 | ShardMemo Tier A/B/C scoping + S1/S2/Planner routing with real KL vs branch bias |
| memory-mint | Router | 30 | Trace-capture -> shard-mint ingestion pipeline feeding memory-router |
| eval-harness-runner | Planner | 150 | Run ava-open-harness evals, gate on all requested evals passing |
| family-brain-wiki | S2 | 300 | Bridge family-brain-os WikiTab pages (localStorage JSON export) into S2 |

## Architecture

- `skills/loader.py` — scans SKILL.md, parses frontmatter, loads skill.py Skill class with run(**kwargs)->dict, routes by j_space_target, respects half-life exp(-steps/hl), topo sort deps.
- `docs/SKILL_SPEC.md` — authoring guide

## Integration

```python
from skills.loader import SkillLoader
loader = SkillLoader(skills_dir="path/to/ava-skills/skills")
loader.load_all()
result = loader.run("openwiki-sync", wiki_path="~/.openwiki/wiki")
```

Family Brain: skill reads/writes encrypted wiki pages same format as WikiTab.

## Free-tier only

Public pip only, torch lazy, MIT. Solo personal project, no connection to employer, built with public/free-tier only.
