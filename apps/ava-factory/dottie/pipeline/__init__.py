"""Continuous shard-flow pipeline: collector -> curator -> trainer, plus janitor.

Shard lifecycle, enforced by ava.pipeline.manifest:

    RAW -> CLAIMED_CURATE -> PACKED -> CLAIMED_TRAIN -> CONSUMED -> DELETED
                                                          (+ FAILED)

Claims are leased; a worker that dies has its shard requeued once the lease
expires. The SQLite manifest is the single source of truth for every state
transition -- no filesystem scanning.
"""
