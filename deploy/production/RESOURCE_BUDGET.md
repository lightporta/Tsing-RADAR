# 4C / measured 7.4 GiB resource contract

The measured host capacity is 7,578 MiB. Swap is an OOM guard and is not
counted as capacity. Default production services resolve to 3,520 MiB and leave
4,058 MiB of non-swap capacity. The separately enabled public edge raises the
capacity-planning baseline to 3,648 MiB and leaves 3,930 MiB to the kernel,
Docker daemon, page tables, logs, certificates, health checks and bursts.

| Service | Limit MiB | Reservation MiB | CPU ceiling | shares |
|---|---:|---:|---:|---:|
| PostgreSQL | 768 | 384 | 1.00 | 1024 |
| Redis | 192 | 96 | 0.25 | 512 |
| ClamAV | 1408 | 768 | 1.25 | 512 |
| backend | 1024 | 512 | 1.50 | 1024 |
| frontend | 128 | 64 | 0.15 | 256 |
| public edge (when separately enabled) | 128 | 64 | 0.20 | 512 |

The 3,648 MiB default total includes the 128 MiB edge budget for conservative
capacity planning even though the public-edge overlay is absent by default.
Without that separately authorized overlay the actually resolved default is
3,520 MiB.
Typical combined container use is a measurement target of 3.5–4.2 GiB, not an
acceptance substitute for hard-limit arithmetic.

The checker enforces this resolved combination matrix. Supported combinations
must retain at least 1,280 MiB non-swap headroom; explicit concurrency policy
may reject a combination even when arithmetic alone would fit.

| Combination | Resolved limit MiB | Headroom MiB | Policy |
|---|---:|---:|---|
| default prod | 3,520 | 4,058 | allow |
| prod + edge | 3,648 | 3,930 | allow |
| prod + edge + QXD | 3,776 | 3,802 | allow |
| prod + edge + QXD + media | 3,904 | 3,674 | allow |
| prod + database setup | 3,648 | 3,930 | allow, locked |
| prod + migration | 3,776 | 3,802 | allow, locked |
| prod + backup | 4,032 | 3,546 | allow, locked |
| prod + restore check (384 + 512 MiB) | 4,416 | 3,162 | allow, locked |
| stage-only + shared infra | 2,976 | 4,602 | allow, stage holds lock |
| prod + stage | 4,128 | 3,450 | reject by concurrency policy |
| stage + backup | 4,640 | 2,938 | reject |
| backup + restore check | 4,928 | 2,650 | reject |

Only one setup/migration/backup/restore/stage workload may hold the shared
kernel job lock. Stage runs the same deterministic lexical recall path as
production and adds no co-resident vector stack on this 4C8G host. Enabling
QXD, media, stage or a job requires the resource checker to recalculate the
resolved service set first.

The L2 deployment runner invokes the same resource-combination checker before
every step in an exact executable workflow; individual deployment actions
cannot be executed directly. It probes and releases the host lock before
starting a locked Compose job; the container entrypoint alone holds the lock
during the operation. Restore-check teardown stops only its two fixed
label-verified containers, removes no volume, and must release the lock on
success, failure or interruption. These controls do not change any limit in
the table above.

Stop and upgrade/split when any OOM occurs; available physical memory remains
below 1 GiB for 15 minutes; sustained swap-in/out accompanies two >80% memory
events within seven days; or concurrent full production and stage is required.

## v4 agent component footprint (no service additions)

The v4 agent components add no new service, container, volume or job to this
host, so the resolved-limit table above is unchanged: the mentor-review
knowledge base is a read-only bind mount of repository files (a few MiB,
page-cache backed, mounted via `KNOWLEDGE_DATA_DIR`); `user_memories` and
`dialogue_sessions` are tables inside the existing PostgreSQL limit; the
tools registry, versioned prompt templates and expression gates execute
in-process inside the backend limit; the 60-case offline evaluation runs on
a developer machine, never on this host.

v4.3.0 adds the optional vector recall file
(`backend/data/knowledge/mentors.knowledge.vectors.json`, same read-only
knowledge mount). It changes no service or limit: it is one JSON read at
backend startup (page-cache backed; roughly 15 MiB at the 340-mentor scale),
and the pure-Python cosine pass over 339 vectors runs in-process only on a
lexical miss, inside the existing backend CPU/memory limits. The file is
built manually with a GLM key on a developer machine
(`python scripts/build_mentor_knowledge.py --rebuild-vectors`) and is never
produced on this host; when absent the recall path degrades to the lexical
baseline with identical behavior. Rebuilding the index is a human-triggered
batch, never a scheduled host job.
