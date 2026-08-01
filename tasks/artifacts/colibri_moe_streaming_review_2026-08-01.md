# Colibrì (disk-streamed MoE experts) — reviewed, NOT adopted, on measured grounds

Solo personal project, no connection to employer, built with public/free-tier only

Operator forwarded a social post claiming a 2.8T-parameter model runs on "a normal PC
with only 25GB of RAM" via a pure-C engine that streams MoE experts from disk. Reviewed
rather than adopted, and the review is recorded so it is not re-litigated from the next
screenshot.

## 1. The project is real; the technique is real

Verified, not assumed: <https://github.com/JustVugg/colibri>. Zero-dependency C engine
that keeps the dense core resident and pulls experts from disk on demand (per-layer LRU,
learned pinning, prefetch). Four supported families: GLM-5.2 (744B), Inkling (975B),
Kimi K3 (2.8T), OLMoE (7B). The underlying idea — treat VRAM/RAM/disk as one memory
hierarchy and only materialise the experts the router actually selects — is sound and is
the same family of trick as existing MoE-offload runtimes. **Nothing here is dismissed as
hype.**

## 2. It does not fit THIS box, and the gap is not close

Measured 2026-08-01 on the dev box, not quoted from an older note:

| resource | this box | Colibrì's stated need | verdict |
|---|---|---|---|
| RAM | **16.9 GB total** (6.7 GB available, 60% load) | 25 GB for GLM-5.2 | short by 8 GB **of total, not free** |
| disk free | **59 GB** (932 G volume, 94% used) | 1.6 TB for the full Kimi K3 checkpoint | short by **~27x** |
| GPU | RTX 4080 12 GB | optional | n/a |

The 25 GB figure is the *floor* for the smallest frontier family, and this machine cannot
reach it even with every other process killed. The Kimi headline is off by more than an
order of magnitude on storage alone. This is the same constraint already recorded in
`apps/ava-factory/scripts/ast_pairs.py`, which declines to fake a pipeline that cannot
run here: *"Measured on this box: 1,896 MB RAM free, 23.6 GB disk, ONE 12 GB GPU. Neither
is possible here, and pretending otherwise would produce a pipeline that cannot run."*

## 3. The one model that WOULD fit is a downgrade from what is already installed

OLMoE (7B) is within budget. But this box already runs **Ollama 0.31.1 with `qwen3:8b`
(5.2 GB)** — a comparable-or-stronger small model, already serving, already integrated,
zero new C toolchain and zero new attack surface. Adopting Colibrì to run a *smaller*
model than the one already working would be strictly negative.

So the honest framing is not "Colibrì is bad", it is: **on this hardware Colibrì's
supported set partitions into models that do not fit and one that is worse than the
incumbent.** There is no configuration in between.

## 4. What this does NOT unblock (checked, because it was the strongest candidate)

The best case for adopting it was the documented Phase-5 gap in `ast_pairs.py` — V2
SEMANTIC GAP, *"requires synthetic query generation (Phase 5, needs a GPU-served LLM)"* —
which is a real, still-open blocker. A local frontier model would be the natural unblock.
It does not apply: the models large enough to be worth it are the ones that do not fit,
and the one that fits is already beaten by `qwen3:8b`. If that gap gets closed, it will be
closed with the Ollama path already on the box, not with a new engine.

## 5. Adopting it now would also cost disk this box does not have

Disk is at **94% (59 GB free)**. HANDOFF still lists disk-watchdog registration as an
unactioned open item. Pulling a multi-hundred-GB MoE checkpoint is not merely unhelpful,
it is the specific failure mode ("WSL/disk crash: free disk, `wsl --shutdown` ...") the
runbook already has a recovery procedure for.

## 6. DECISION and the trigger that would reverse it

**Not adopted. No code, no dependency, no download.** Recorded rather than silently
dropped, because the idea is good and will come back.

Revisit if **all** of these become true, and re-measure rather than trusting this table:

1. RAM ≥ 32 GB (so the 25 GB floor is reachable with headroom), **and**
2. ≥ 500 GB free on a fast NVMe (the smallest frontier checkpoint, not the 1.6 TB Kimi
   one), **and**
3. a task exists that `qwen3:8b` measurably fails and a 744B model measurably passes —
   stated as a number on a fixed set *before* the run, per the pre-registration discipline
   this repo already applies to model work (see
   `tasks/artifacts/embedding_train_plan_2026-07-31.md`).

Condition 3 matters most. The estate's binding constraint has never been model capability
— it is the ability to tell whether a change helped, which is exactly what the
domain-embedding review (`42db5a0`) concluded: *"Training N models into that gap yields N
unfalsifiable claims, not N capabilities."* A bigger local model bought before that
measurement exists would buy N more.

## 7. The transferable insight, kept even though the tool is not

*"The real constraint was never the model size — it was the assumption that every
parameter had to live in fast memory at the same time."*

That is a genuine systems observation and it generalises past inference. It was checked
against this repo for a current application and none was found: the factory's memory
pressure is a test-runner and trainer-process problem, not a resident-weights problem, and
the MTNN matrices are small enough to hold comfortably. Noting the check happened, so a
future reader knows the idea was applied and came back empty here rather than being
ignored.
