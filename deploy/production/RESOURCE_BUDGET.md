# 4C / measured 7.4 GiB resource contract

The measured host capacity is 7,578 MiB. Swap is an OOM guard and is not
counted as capacity. Default production services resolve to 5,184 MiB and leave
2,394 MiB of non-swap capacity. The separately enabled public edge raises the
capacity-planning baseline to 5,312 MiB and leaves 2,266 MiB to the kernel,
Docker daemon, page tables, logs, certificates, health checks and bursts.

| Service | Limit MiB | Reservation MiB | CPU ceiling | shares |
|---|---:|---:|---:|---:|
| PostgreSQL | 768 | 384 | 1.00 | 1024 |
| Redis | 192 | 96 | 0.25 | 512 |
| etcd | 256 | 128 | 0.25 | 512 |
| Milvus | 1024 | 512 | 1.25 | 768 |
| Milvus-only MinIO | 384 | 192 | 0.40 | 512 |
| ClamAV | 1408 | 768 | 1.25 | 512 |
| backend | 1024 | 512 | 1.50 | 1024 |
| frontend | 128 | 64 | 0.15 | 256 |
| public edge (when separately enabled) | 128 | 64 | 0.20 | 512 |

The 5,312 MiB default total includes the 128 MiB edge budget for conservative
capacity planning even though the public-edge overlay is absent by default.
Without that separately authorized overlay the actually resolved default is
5,184 MiB.
Typical combined container use is a measurement target of 3.5–4.2 GiB, not an
acceptance substitute for hard-limit arithmetic.

The checker enforces this resolved combination matrix. Supported combinations
must retain at least 1,280 MiB non-swap headroom; explicit concurrency policy
may reject a combination even when arithmetic alone would fit.

| Combination | Resolved limit MiB | Headroom MiB | Policy |
|---|---:|---:|---|
| default prod | 5,184 | 2,394 | allow |
| prod + edge | 5,312 | 2,266 | allow |
| prod + edge + QXD | 5,440 | 2,138 | allow |
| prod + edge + QXD + media | 5,568 | 2,010 | allow |
| prod + database setup | 5,312 | 2,266 | allow, locked |
| prod + migration | 5,440 | 2,138 | allow, locked |
| prod + backup | 5,696 | 1,882 | allow, locked |
| prod + restore check (384 + 512 MiB) | 6,080 | 1,498 | allow, locked |
| stage-only + shared infra | 4,640 | 2,938 | allow, stage holds lock |
| prod + stage | 5,792 | 1,786 | reject by concurrency policy |
| stage + backup | 6,304 | 1,274 | reject |
| backup + restore check | 6,592 | 986 | reject |

Only one setup/migration/backup/restore/stage workload may hold the shared
kernel job lock. Full stage Milvus is never co-resident on this 4C8G host. Stage
uses lexical fallback, an isolated on-demand vector stack in a maintenance
window, or a separate node. Enabling QXD, media, stage or a job requires the
resource checker to recalculate the resolved service set first.

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
