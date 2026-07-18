# Plan: T9.2 mini launch (user GO 2026-07-10)

## Situation
- Nano closed (`eb66bb9`). Disk ~13.6 GB free (near `low_water_gb: 12`).
- Manifest frozen to **8k** nano tokenizer; packed shards (~2.9 GB) are hash-bound to it.
- Mini needs **32k** BPE + fresh PACKED; RAW text (~1.8 GB) is reusable.
- `packed_min_tokens: 200M` lead; eviction high-water 15 GB.

## Steps
1. Stop server + data plane briefly (GPU + avoid pack races).
2. Park nano ckpts under `/ckpt/nano/` (preserve `base_final` / stables).
3. Wipe PACKED files + mark shards DELETED; clear tokenizer freeze row (documented reset).
4. Train 32k on `/raw`, write `/state/tokenizer.json`, `--freeze`.
5. Set `AVA_PRESET=mini`; recreate collectors/curators/janitor; wait P0 runway ≥ lead.
6. Launch trainer (no `--resume`); verify steps + VRAM; leave running (3–5 days).
7. Update TODOS T9.2 in-progress notes; commit reset helper + plan.

## Non-goals
- Full 3M chat FT; base1b; wiping RAW/dedup; `docker system prune --volumes`.

## Risks
| Risk | Mitigation |
|------|------------|
| Disk < 12 GB stops collectors | Wipe nano packed first; eviction on |
| Re-freeze without wipe | Reset only after PACKED cleared |
| Mini overwrites nano `base_final` | Park under `/ckpt/nano/` first |
| `compile: true` unused in train.py | Document non-action; run without compile |
