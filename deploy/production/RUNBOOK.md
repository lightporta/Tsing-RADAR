# Production deployment and rollback runbook

This directory is an offline deployment artifact, not evidence of a live
deployment. Real COS, DNS, TLS, ICP applicability, public routes and QXD/media
remain separate cloud/user/audit gates.

## Immutable local release handoff

The backend Python base and both frontend build/runtime bases are pinned to
verified `linux/amd64` manifest digests. The ignored local release manifest
records the upstream multi-architecture index, selected `linux/amd64` manifest
and config relationship plus the locally built application image IDs. The
target server must still pull and inspect every final image on `linux/amd64`;
the local manifest is not a registry or cloud verification.

`deploy-runner.py` accepts enumerated action IDs only. Its project name,
Compose files, services, environment-file location and secret roots are fixed
in code. It never accepts an extra Compose file, service, project, backup path,
environment override, public overlay or destructive volume operation. Plan
mode emits action IDs only. Execute mode captures subprocess output and emits
only stable status/reason codes. Execute mode accepts only the complete
`first-deploy-plan` and `upgrade-plan` workflows plus the non-mutating
`lock-probe`; every deployment step exposed for planning (including
`migration`) is rejected when executed directly.

## Default composition

Resolve only `compose.infra.yml` plus `compose.prod.yml`. This has no host port,
QXD gateway, media gateway or public edge. Optional overlay inclusion is the
single atomic enable operation; those overlays deliberately have no profiles
that could leave an override half-enabled. QXD must be combined with edge, and
media must be combined with both QXD and edge. `PUBLIC_BASE_URL` is empty and
stage has no Milvus endpoint.

## First deployment

Run only `deploy-runner.py --action first-deploy-plan --mode execute`; the
runner validates the exact immutable workflow before the first subprocess and
stops on the first failed step. The fixed sequence is:

1. Run the offline checker against dummy secret files and immutable Compose
   image digests. On the server run `secret_preflight.py` against restricted
   real secret roots; it emits labels and PASS/FAIL only. Never print values or
   fingerprints. Create the root-owned host job-lock file with group
   `JOB_LOCK_GID`, mode 0660, and prove every one-shot/stage process can lock it.
2. Start only infra and wait for every internal health check. PostgreSQL uses
   the bootstrap credential only for cluster initialization; nothing publishes
   a host port.
3. Run exactly one `prod-db-provision` job. It must create/converge the prod
   role/database, revoke PUBLIC connect, and grant only the prod owner and
   bootstrap identity. Any failure stops before migration or backend startup.
4. Run the fixed `prod-db-verification` job before migration. It uses bootstrap
   only to verify the target owner, PUBLIC/other-login ACL denial, application
   role NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION attributes, empty
   application-table set and prod/stage connection isolation when the stage
   namespace exists. It separately logs in as the prod application role and
   verifies prod database plus public-schema access. Missing provisioning,
   incomplete stage namespace, a non-empty target or any privilege mismatch
   fails before migration. No single-step migration execute path exists.
5. Acquire both the shared kernel job lock and the database advisory lock, then
   run exactly one `migration` job. A failed
   migration stops the process before any app starts.
6. Start backend without edge traffic. Run schema, local readiness, contract and
   honest zero-published-mentor checks.
7. Create the first backup and restore it into the isolated restore-check
   database. Do not restore over the source database.
   Whether the restore succeeds, fails or is interrupted, stop and remove only
   the two containers whose Compose labels exactly match project
   `tsing-radar-prod` and services `restore-check`/`restore-check-db`. Stop the
   restore client before its database, prove the shared lock can be reacquired,
   and leave all volumes untouched. Cleanup failure is non-zero and requires
   exact manual inspection; never use `down -v`.
8. Start frontend. Public edge remains absent until a later cloud batch closes
   domain, TLS, ICP applicability and user authorization.

## Upgrade

`deploy-runner.py --action upgrade-plan --mode execute` is intentionally a
pre-approval workflow, not an upgrade executor. It performs only steps 1-2 and
then exits 77 with `upgrade_compatibility_requires_separate_approval`.

1. Keep the old app serving while infra health is checked.
2. Under the shared kernel job lock, stream a database backup, verify its
   checksum and restore it to the isolated
   restore-check service.
3. Stop. Migration compatibility classification and any subsequent migration
   require a separate cloud batch, user authorization and independent audit.
   There is no approval flag or direct migration action in this runner.
   A later approved batch must classify expand/contract compatibility before
   acquiring the shared kernel and database migration locks;
   destructive/non-transactional work requires a maintenance page.
4. Start the new backend off-traffic; run contracts and read/write probes.
5. Atomically switch edge upstream and observe. Retain the old image digest and
   configuration through the rollback window.

Before migration, backup or restore-check failure aborts while the old version
continues. A transactional migration failure may return to the old version only
after proving the schema is unchanged. A new backend failure may use the old
backend only when the schema remains expand/contract compatible. Otherwise,
restore the verified backup into a new database instance and repoint the old
image; never overwrite the source database or run an automatic downgrade.
Contract/cleanup migrations are separate batches after the rollback window.

## Isolation and irreversible gates

- Stage uses a distinct PostgreSQL role/database, Redis container/volume/network
  and COS bucket/CAM identity. It never joins `prod-app` and never receives a
  production Milvus endpoint or credential.
- Stage setup order is infra healthy -> `stage-db-provision` -> verify both
  stage-to-prod and prod-to-stage connection denial -> start stage backend.
  Stage backend holds the same kernel job lock for its complete lifetime, so it
  cannot overlap migration, backup, restore-check or another setup job. The
  resource matrix rejects co-resident prod+stage on this host; stop prod app and
  public overlays before starting the supported stage-only composition.
- COS policy is object-prefix scoped Put/Get/Delete only. `ListBucket`, ACL,
  policy management and cross-bucket access are not pre-granted.
- QXD, media and public edge require their own complete overlays; a partial
  overlay combination fails Compose validation. Template presence is not a
  release statement.
- DNS, certificates, public ports, ICP decisions, key rotation, destructive
  migration/restore, bucket deletion, server reinstall and paid resources are
  cloud operations requiring fresh user authorization and independent audit.

## Secret file ownership gate

The backend image runs as numeric uid/gid `10001:10001`. Its host secret files
must be individually owned by uid 10001, mode 0400, inside a root-managed
directory that is not group/world traversable. Every production Compose secret
consumer uses an explicit long-syntax bind mount with `read_only: true` and
`bind.create_host_path: false`; no top-level Compose `secrets.file` object or
plaintext environment fallback is permitted. This makes the host file the
authoritative uid/gid/mode source and prevents Compose from silently creating a
missing source path. `docker compose config` proves only the mount declaration,
not the runtime permission result. Before any app starts, the cloud batch must
inspect every `/run/secrets/*` from the exact pinned image and prove the intended
container identity can read it while group/other cannot. The application startup
gate independently rejects relative, symlinked, missing or group/world-readable
secret files. If the target engine does not preserve this contract, deployment
stops; it must not fall back to direct environment values, top-level file secrets
or mode 0444.

The database bootstrap secret is an explicit exception mounted only into the
PostgreSQL initialization service and prod/stage database-provision jobs. It is
never mounted into prod or stage application runtime containers.

## Shared one-shot/stage lock

`JOB_LOCK_FILE` is a pre-created regular host file owned by root and group
`JOB_LOCK_GID`, mode 0660. Every database provision, migration, backup and
restore-check path executes through `job-lock.sh`; stage backend holds the same
lock while running. Lock contention exits 75 and invalid/missing lock setup
exits 78. The kernel releases the `flock` descriptor on normal failure,
SIGTERM or container death. No job may bypass this wrapper.

The host runner performs only a non-blocking lock availability probe and
immediately releases it. The Compose job's `job-lock.sh` entrypoint is the sole
owner while work executes. Holding the host lock while launching the container
would self-deadlock and is prohibited.

## Release candidate boundary

The release manifest uses canonical repository-relative paths. Absolute paths,
`..`, symlinks, duplicate/case-colliding paths, oversized files, private
uploads, secret material, root pytest temporary directories, legacy data and
`backend/data/mentors.evidence.json` are rejected. The backend Docker context
also excludes that evidence file and `backend/data/private_local/` explicitly;
the approved catalog ignore rules remain unchanged. This is a local candidate
allowlist only, not the later Git-history, license, PII or authorization audit.
Its validator also rejects unknown top-level/item fields and requires the exact
backend/frontend role-to-local-reference mapping, current `docker image
inspect` ID/platform values, Compose image-slot set and cloud-gate set. Both
build and verify-only re-inspect the two fixed local image references; a
well-formed but stale or substituted SHA-256 is not accepted.

## Container exceptions pending cloud verification

- Vendor PostgreSQL, Redis, etcd, MinIO, Milvus and ClamAV images retain their
  vendor entrypoint users until each pinned digest is verified on the server.
- The current frontend Nginx image needs a minimal capability set to bind port
  80 internally; it has no host port in the default composition.
- Milvus reads its MinIO-only credential from mounted files in a wrapper and
  exports it only inside that process. Real image behavior and absence from
  inspect/logs remain a cloud gate.
- No container exception authorizes host ports, privileged mode, Docker socket,
  host PID/network or production secret values in environment declarations.

## L3 immutable handoff (local only)

L3 creates a local, ignored handoff candidate; it does not upload, publish or
deploy it. Run the builder only after the L1/L2 gates and the fixed local
`linux/amd64` backend/frontend images pass:

```text
python deploy/production/scripts/build-handoff.py
python deploy/production/scripts/verify-handoff.py --bundle .l3-handoff/<generation>/bundle
```

The bundle has exactly eight regular files and a hard 2 GiB total budget:
`bundle-manifest.json`, its detached SHA-256 file, `image-lock.json`, the L2
release manifest, a credential-free Compose image environment, deterministic
`source.tar`, and exactly two OCI archives for backend and frontend. It never
contains PostgreSQL, Redis, etcd, MinIO, Milvus, ClamAV, Caddy or unprivileged
Nginx archives. Those eight vendor slots use `delivery_mode=digest_pull`; a
future separately approved cloud batch must pull each exact
`repository@linux/amd64-manifest`, inspect it and prove the locked
manifest/config/layer chain. Adding a vendor archive is a contract failure, not
an offline fallback.

At capture time only, fixed vendor tags are resolved over the registry TLS
path into an index digest, the unique `linux/amd64` manifest, its config and
layer descriptors. Later tag movement is recorded as an upstream freshness
event and does not rewrite or invalidate the integrity of an already locked
bundle. A policy decision to reject an old lock is a separate gate. No
`latest`, floating Caddy or floating unprivileged-Nginx tag is accepted.

Before any extraction or `docker load`, verification scans every raw tar
header with a global byte/member budget. PAX/GNU path overrides, sparse files,
long-name extensions, absolute or parent paths, backslashes, duplicate or
case-colliding names, links, devices and FIFOs fail closed. Every OCI descriptor
media type, size and SHA-256 is rechecked. `source.tar` contains only the exact
L2 allowlisted regular files, in sorted USTAR order with fixed uid/gid,
owner names, mtime and path-based mode; source bytes are not rewritten. Each
regular/directory USTAR header must also equal its complete canonical 512-byte
reconstruction: magic/version, link name, device fields, reserved bytes and all
bytes following the first NUL in name/prefix/owner fields are fixed and cannot
carry hidden data even if an attacker recomputes the tar checksum.

The embedded L2 manifest is validated with the same strict portable structure
contract as L2 itself: exact top-level fields, base-image relationships,
backend/frontend roles and local references, ten Compose slots, four cloud
gates, normalized source entries and prohibited paths. Its two engine-specific
image IDs must equal the informational engine observations captured into the
corresponding L3 application slots. The observed Docker `Id` is not interpreted
as a config digest; the locked OCI descriptor chain remains authoritative.

`bundle-manifest.sha256` is detached and covers the exact canonical manifest
bytes, avoiding a self-referential digest. `captured_at` exists only in outer
JSON metadata and never changes the deterministic source archive. The L2/L3
allowlists are not a Git-history, license, PII or authorization audit. Before a
future transfer, that exact final candidate still requires a newly authorized
secret/PII/unauthorized-data scan.

The optional local import probe is:

```text
python deploy/production/scripts/verify-handoff.py \
  --bundle .l3-handoff/<generation>/bundle --load-images
```

Before the first load or re-export, free space on the bundle and temporary-work
filesystems must be at least `3 * actual_bundle_bytes + 2 GiB`. On a Linux
target the same threshold must be proven for Docker's actual Root Dir
filesystem; if the Root Dir or its filesystem cannot be resolved reliably, the
probe fails closed and the cloud batch must perform an explicit preflight. Swap
is not counted. The boundary value is accepted; one byte less is rejected.

It first validates the complete bundle, then imports only the two application
archives. It requires exact `repo@sha256:<manifest>` inspection, a matching
RepoDigest, `linux/amd64`, and—where exposed by the engine—a matching OCI
descriptor. It safely re-exports each imported image and revalidates the
original manifest/config/layers, then uses Compose `--pull never` to create but
never start two no-network/no-port/no-volume containers. Only its unique tags
and labelled temporary containers are removed afterwards.

Docker image `Id` is informational and engine-specific: a legacy graphdriver
may display the config digest, while Docker Desktop/containerd may display the
manifest digest. Neither is treated as the cross-engine config authority. The
OCI descriptor chain and rehashed blobs are authoritative. The local probe
does not replace the later target-server load/pull/inspect/Compose gate.
