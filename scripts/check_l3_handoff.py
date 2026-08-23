#!/usr/bin/env python3
"""Static, mutation, and optional local-artifact checks for L3 handoff."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "deploy" / "production" / "scripts" / "build-handoff.py"
VERIFIER_PATH = ROOT / "deploy" / "production" / "scripts" / "verify-handoff.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


B = _load("tsing_radar_l3_builder_check", BUILDER_PATH)
V = _load("tsing_radar_l3_verifier_check", VERIFIER_PATH)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _add_bytes(target: tarfile.TarFile, name: str, data: bytes, *, typeflag: bytes = tarfile.REGTYPE) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data) if typeflag in {tarfile.REGTYPE, tarfile.AREGTYPE} else 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.mtime = 0
    info.type = typeflag
    target.addfile(info, io.BytesIO(data) if info.size else None)


def synthetic_oci(path: Path, *, repository: str, tag: str = "l3-locked") -> B.ImageChain:
    layer = b"synthetic-l3-layer\n"
    layer_descriptor = {
        "mediaType": "application/vnd.oci.image.layer.v1.tar",
        "digest": _digest(layer),
        "size": len(layer),
    }
    config_value = {
        "architecture": "amd64",
        "os": "linux",
        "rootfs": {"type": "layers", "diff_ids": [_digest(layer)]},
        "config": {},
    }
    config = B.canonical_json_bytes(config_value)
    config_descriptor = {
        "mediaType": "application/vnd.oci.image.config.v1+json",
        "digest": _digest(config),
        "size": len(config),
    }
    manifest_value = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": config_descriptor,
        "layers": [layer_descriptor],
    }
    manifest = B.canonical_json_bytes(manifest_value)
    manifest_descriptor = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": _digest(manifest),
        "size": len(manifest),
        "platform": B.TARGET_PLATFORM,
        "annotations": {
            "io.containerd.image.name": f"docker.io/{repository}:{tag}",
            "org.opencontainers.image.ref.name": tag,
        },
    }
    source_index = B.canonical_json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": manifest_descriptor["mediaType"],
                    "digest": manifest_descriptor["digest"],
                    "size": manifest_descriptor["size"],
                    "platform": B.TARGET_PLATFORM,
                }
            ],
        }
    )
    source_index_descriptor = {
        "media_type": "application/vnd.oci.image.index.v1+json",
        "digest": _digest(source_index),
        "size": len(source_index),
    }
    index = B.canonical_json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [manifest_descriptor],
        }
    )
    blobs = {
        "blobs/sha256/" + manifest_descriptor["digest"].removeprefix("sha256:"): manifest,
        "blobs/sha256/" + config_descriptor["digest"].removeprefix("sha256:"): config,
        "blobs/sha256/" + layer_descriptor["digest"].removeprefix("sha256:"): layer,
        "blobs/sha256/" + source_index_descriptor["digest"].removeprefix("sha256:"): source_index,
    }
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as target:
        for name in sorted(blobs):
            _add_bytes(target, name, blobs[name])
        _add_bytes(target, "index.json", index)
        _add_bytes(target, "oci-layout", B.canonical_json_bytes({"imageLayoutVersion": "1.0.0"}))
    return B.parse_oci_archive(path)


def synthetic_lock(chain: B.ImageChain) -> dict[str, object]:
    synthetic_index = B.canonical_json_bytes(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": chain.manifest["media_type"],
                    "digest": chain.manifest["digest"],
                    "size": chain.manifest["size"],
                    "platform": B.TARGET_PLATFORM,
                }
            ],
        }
    )
    source_chain = B.ImageChain(
        root={
            "media_type": "application/vnd.oci.image.index.v1+json",
            "digest": _digest(synthetic_index),
            "size": len(synthetic_index),
        },
        manifest=chain.manifest,
        config=chain.config,
        layers=chain.layers,
        members=chain.members,
    )
    slots = []
    for spec in B.SLOT_SPECS:
        slots.append(B._slot_from_chain(spec, source_chain))
    lock = {
        "schema_version": "l3-image-lock-v1",
        "captured_at": "2026-08-03T00:00:00Z",
        "target_platform": B.TARGET_PLATFORM,
        "freshness_policy": "source-tag-drift-is-recorded-separately-from-content-integrity",
        "slots": slots,
    }
    B.validate_image_lock(lock)
    return lock


def _descriptor(path: Path, relative: str) -> dict[str, object]:
    return {"path": relative, "size": path.stat().st_size, "sha256": B.sha256_file(path)}


def _write_detached(bundle: Path) -> None:
    manifest = bundle / "bundle-manifest.json"
    (bundle / "bundle-manifest.sha256").write_text(
        B.sha256_file(manifest).removeprefix("sha256:") + "  bundle-manifest.json\n",
        encoding="ascii",
        newline="\n",
    )


def synthetic_bundle(root: Path) -> Path:
    bundle = root / "bundle"
    images = bundle / "images"
    images.mkdir(parents=True)
    backend = images / "backend.oci.tar"
    frontend = images / "frontend.oci.tar"
    chain = synthetic_oci(backend, repository="tsing-radar-offline/backend")
    synthetic_oci(frontend, repository="tsing-radar-offline/frontend")
    lock = synthetic_lock(chain)
    # Both synthetic app archives intentionally carry the same CAS chain; identity
    # still differs through fixed lock role/path/reference contracts.
    (bundle / "image-lock.json").write_bytes(B.canonical_json_bytes(lock))
    source_payload = b"synthetic source\n"
    source_digest = _digest(source_payload)
    l2_module = B._load_l2_module()
    application_slots = [
        item for item in lock["slots"] if item["kind"] == "application"
    ]
    l2 = {
        "schema_version": "l2-release-manifest-v1",
        "target_platform": B.TARGET_PLATFORM,
        "base_images": [dict(item) for item in l2_module.BASE_IMAGES],
        "application_images": [
            {
                "role": item["role"],
                "local_reference": item["source_reference"],
                "image_id": item["engine_observation"]["image_id"],
                "os": "linux",
                "architecture": "amd64",
            }
            for item in application_slots
        ],
        "source_files": [
            {"path": "backend/app/synthetic.py", "size": len(source_payload), "sha256": source_digest}
        ],
        "compose_image_slots": [
            {"name": name, "cloud_resolution_required": True}
            for name in l2_module.COMPOSE_IMAGE_SLOTS
        ],
        "cloud_gates": list(l2_module.CLOUD_GATES),
    }
    (bundle / "l2-release-manifest.json").write_bytes(B.canonical_json_bytes(l2))
    with tarfile.open(bundle / "source.tar", "w", format=tarfile.USTAR_FORMAT) as target:
        _add_bytes(target, "backend/app/synthetic.py", source_payload)
    lines = [
        "# Generated L3 offline image references; contains no credentials.",
        "# Loading and using these images on a server remains a separately approved cloud gate.",
        *(f"{item['slot']}={item['compose_reference']}" for item in lock["slots"]),
    ]
    (bundle / "compose-images.env").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": "l3-handoff-manifest-v1",
        "generation_id": "l3-20260803T000000Z-0123abcd",
        "captured_at": "2026-08-03T00:00:00Z",
        "target_platform": B.TARGET_PLATFORM,
        "image_lock": _descriptor(bundle / "image-lock.json", "image-lock.json"),
        "l2_release_manifest": _descriptor(bundle / "l2-release-manifest.json", "l2-release-manifest.json"),
        "compose_environment": _descriptor(bundle / "compose-images.env", "compose-images.env"),
        "source_archive": _descriptor(bundle / "source.tar", "source.tar"),
        "image_archives": [
            {"slot": "BACKEND_IMAGE", **_descriptor(backend, "images/backend.oci.tar")},
            {"slot": "FRONTEND_IMAGE", **_descriptor(frontend, "images/frontend.oci.tar")},
        ],
        "bundle_policy": dict(V.FIXED_POLICY),
        "integrity_policy": dict(V.FIXED_INTEGRITY),
        "cloud_gates": list(B.CLOUD_GATES),
    }
    (bundle / "bundle-manifest.json").write_bytes(B.canonical_json_bytes(manifest))
    _write_detached(bundle)
    return bundle


def _refresh_manifest_descriptor_and_hash(bundle: Path, relative: str) -> None:
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for field in ("image_lock", "l2_release_manifest", "compose_environment", "source_archive"):
        if manifest[field]["path"] == relative:
            manifest[field] = _descriptor(bundle / relative, relative)
    for index, item in enumerate(manifest["image_archives"]):
        if item["path"] == relative:
            manifest["image_archives"][index] = {"slot": item["slot"], **_descriptor(bundle / relative, relative)}
    manifest_path.write_bytes(B.canonical_json_bytes(manifest))
    _write_detached(bundle)


def _expect_failure(operation: Callable[[], object], reason: str) -> None:
    try:
        operation()
    except (B.HandoffError, V.HandoffError):
        return
    raise AssertionError(reason)


def _rewrite_first_header_checksum(path: Path) -> None:
    with path.open("r+b") as handle:
        header = bytearray(handle.read(512))
        if len(header) != 512:
            raise AssertionError("tar header missing")
        header[148:156] = b"        "
        header[148:156] = f"{sum(header):06o}\0 ".encode("ascii")
        handle.seek(0)
        handle.write(header)


def _mutate_first_header(path: Path, offset: int, payload: bytes) -> None:
    with path.open("r+b") as handle:
        handle.seek(offset)
        handle.write(payload)
    _rewrite_first_header_checksum(path)


def check_schema_contracts() -> None:
    image_schema = json.loads(B.IMAGE_LOCK_SCHEMA.read_text(encoding="utf-8"))
    handoff_schema = json.loads(B.HANDOFF_SCHEMA.read_text(encoding="utf-8"))
    slots = image_schema["properties"]["slots"]
    archives = handoff_schema["properties"]["image_archives"]
    if slots["minItems"] != 7 or slots["maxItems"] != 7:
        raise AssertionError("image_lock_schema_slot_count")
    if archives["minItems"] != 2 or archives["maxItems"] != 2:
        raise AssertionError("handoff_schema_archive_count")
    if archives.get("items") is not False:
        raise AssertionError("handoff_schema_extra_archive_allowed")
    archive_identities = [
        (
            item["allOf"][1]["properties"]["slot"]["const"],
            item["allOf"][1]["properties"]["path"]["const"],
        )
        for item in archives.get("prefixItems", [])
    ]
    if archive_identities != list(V.APP_ARCHIVES):
        raise AssertionError("handoff_schema_application_archive_identity")
    if slots.get("items") is not False or len(slots.get("prefixItems", [])) != 7:
        raise AssertionError("image_lock_schema_extra_slot_allowed")
    engine_observation = image_schema["$defs"]["imageSlot"]["properties"].get(
        "engine_observation"
    )
    if (
        not isinstance(engine_observation, dict)
        or engine_observation.get("additionalProperties") is not False
        or set(engine_observation.get("required", [])) != B.ENGINE_OBSERVATION_FIELDS
        or image_schema["$defs"]["backendSlot"].get("required")
        != ["engine_observation"]
        or image_schema["$defs"]["frontendSlot"].get("required")
        != ["engine_observation"]
    ):
        raise AssertionError("application_engine_observation_schema_invalid")
    slot_refs = [item["allOf"][1]["$ref"] for item in slots["prefixItems"]]
    if slot_refs != [
        "#/$defs/postgresSlot",
        "#/$defs/redisSlot",
        "#/$defs/clamavSlot",
        "#/$defs/backendSlot",
        "#/$defs/frontendSlot",
        "#/$defs/caddySlot",
        "#/$defs/nginxUnprivilegedSlot",
    ]:
        raise AssertionError("image_lock_schema_slot_identity")


def check_slot_contract() -> None:
    if len(B.SLOT_SPECS) != 7 or len({item["slot"] for item in B.SLOT_SPECS}) != 7:
        raise AssertionError("slot_contract_count")
    if [item["slot"] for item in B.SLOT_SPECS] != [
        "POSTGRES_IMAGE",
        "REDIS_IMAGE",
        "CLAMAV_IMAGE",
        "BACKEND_IMAGE",
        "FRONTEND_IMAGE",
        "CADDY_IMAGE",
        "NGINX_UNPRIVILEGED_IMAGE",
    ]:
        raise AssertionError("slot_contract_order")
    if next(item for item in B.SLOT_SPECS if item["slot"] == "CADDY_IMAGE")["source_tag"] != "2.10.2-alpine":
        raise AssertionError("caddy_tag_not_fixed")
    if next(item for item in B.SLOT_SPECS if item["slot"] == "NGINX_UNPRIVILEGED_IMAGE")["source_tag"] != "1.31.3-alpine3.24":
        raise AssertionError("nginx_unprivileged_tag_not_fixed")


def check_synthetic_bundle_and_mutations() -> None:
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l3-check-") as temporary:
        root = Path(temporary)
        bundle = synthetic_bundle(root)
        V.verify_bundle(bundle)

        original_manifest = (bundle / "bundle-manifest.json").read_bytes()
        original_detached = (bundle / "bundle-manifest.sha256").read_bytes()
        (bundle / "bundle-manifest.json").write_bytes(original_manifest + b" ")
        _expect_failure(lambda: V.verify_bundle(bundle), "manifest tamper accepted")
        (bundle / "bundle-manifest.json").write_bytes(original_manifest)
        (bundle / "bundle-manifest.sha256").write_bytes(b"0" * 64 + b"  bundle-manifest.json\n")
        _expect_failure(lambda: V.verify_bundle(bundle), "detached hash tamper accepted")
        (bundle / "bundle-manifest.sha256").write_bytes(original_detached)

        manifest = json.loads(original_manifest)
        manifest["image_archives"].pop()
        (bundle / "bundle-manifest.json").write_bytes(B.canonical_json_bytes(manifest))
        _write_detached(bundle)
        _expect_failure(lambda: V.verify_bundle(bundle), "missing app archive descriptor accepted")

        manifest = json.loads(original_manifest)
        manifest["image_archives"][1] = deepcopy(manifest["image_archives"][0])
        (bundle / "bundle-manifest.json").write_bytes(B.canonical_json_bytes(manifest))
        _write_detached(bundle)
        _expect_failure(lambda: V.verify_bundle(bundle), "duplicate app archive accepted")

        manifest = json.loads(original_manifest)
        manifest["image_archives"][0]["slot"] = "FRONTEND_IMAGE"
        manifest["image_archives"][1]["slot"] = "BACKEND_IMAGE"
        (bundle / "bundle-manifest.json").write_bytes(B.canonical_json_bytes(manifest))
        _write_detached(bundle)
        _expect_failure(lambda: V.verify_bundle(bundle), "role swap accepted")

        manifest = json.loads(original_manifest)
        manifest["image_archives"][0]["slot"] = "POSTGRES_IMAGE"
        (bundle / "bundle-manifest.json").write_bytes(B.canonical_json_bytes(manifest))
        _write_detached(bundle)
        _expect_failure(lambda: V.verify_bundle(bundle), "vendor archive injection accepted")


def check_l2_manifest_mutations() -> None:
    mutations = {
        "app-role": lambda value: value["application_images"][0].__setitem__("role", "frontend"),
        "app-ref": lambda value: value["application_images"][0].__setitem__(
            "local_reference", "tsing-radar-backend:other"
        ),
        "app-digest": lambda value: value["application_images"][0].__setitem__(
            "image_id", "sha256:" + "1" * 64
        ),
        "base-image": lambda value: value["base_images"][0].__setitem__(
            "linux_amd64_manifest_digest", "sha256:" + "2" * 64
        ),
        "compose-slot": lambda value: value["compose_image_slots"][0].__setitem__(
            "name", "OTHER_IMAGE"
        ),
        "cloud-gate": lambda value: value["cloud_gates"].__setitem__(0, "weaker_gate"),
    }
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l3-l2-") as temporary:
        for name, mutate in mutations.items():
            bundle = synthetic_bundle(Path(temporary) / name)
            path = bundle / "l2-release-manifest.json"
            value = json.loads(path.read_bytes())
            mutate(value)
            path.write_bytes(B.canonical_json_bytes(value))
            _refresh_manifest_descriptor_and_hash(bundle, "l2-release-manifest.json")
            _expect_failure(
                lambda bundle=bundle: V.verify_bundle(bundle),
                f"{name} accepted",
            )


def check_archive_header_mutations() -> None:
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l3-tar-") as temporary:
        root = Path(temporary)
        for name, writer in (
            (
                "traversal.tar",
                lambda target: _add_bytes(target, "../escape", b"x"),
            ),
            (
                "symlink.tar",
                lambda target: _add_bytes(target, "link", b"", typeflag=tarfile.SYMTYPE),
            ),
            (
                "hardlink.tar",
                lambda target: _add_bytes(target, "hard", b"", typeflag=tarfile.LNKTYPE),
            ),
            (
                "device.tar",
                lambda target: _add_bytes(target, "device", b"", typeflag=tarfile.CHRTYPE),
            ),
            (
                "fifo.tar",
                lambda target: _add_bytes(target, "fifo", b"", typeflag=tarfile.FIFOTYPE),
            ),
            (
                "sparse.tar",
                lambda target: _add_bytes(target, "sparse", b"", typeflag=tarfile.GNUTYPE_SPARSE),
            ),
        ):
            path = root / name
            with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as target:
                writer(target)
            _expect_failure(lambda path=path: B.scan_tar_headers(path, allow_directories=False), name)

        duplicate = root / "duplicate.tar"
        with tarfile.open(duplicate, "w", format=tarfile.USTAR_FORMAT) as target:
            _add_bytes(target, "same", b"1")
            _add_bytes(target, "same", b"2")
        _expect_failure(lambda: B.scan_tar_headers(duplicate, allow_directories=False), "duplicate accepted")

        collision = root / "collision.tar"
        with tarfile.open(collision, "w", format=tarfile.USTAR_FORMAT) as target:
            _add_bytes(target, "Case", b"1")
            _add_bytes(target, "case", b"2")
        _expect_failure(lambda: B.scan_tar_headers(collision, allow_directories=False), "case collision accepted")

        long_name = root / "gnu-long.tar"
        with tarfile.open(long_name, "w", format=tarfile.GNU_FORMAT) as target:
            _add_bytes(target, "a" * 180, b"x")
        _expect_failure(lambda: B.scan_tar_headers(long_name, allow_directories=False), "GNU longname accepted")

        pax = root / "pax.tar"
        with tarfile.open(pax, "w", format=tarfile.PAX_FORMAT) as target:
            _add_bytes(target, "b" * 180, b"x")
        _expect_failure(lambda: B.scan_tar_headers(pax, allow_directories=False), "PAX accepted")


def check_hidden_ustar_header_mutations() -> None:
    mutations = {
        "linkname": (157, b"X"),
        "version": (263, b"01"),
        "devmajor": (329, b"1"),
        "devminor": (337, b"1"),
        "reserved": (500, b"X"),
        "name-nul-tail": (len("backend/app/synthetic.py") + 1, b"X"),
        "prefix-nul-tail": (346, b"X"),
        "uname-nul-tail": (266, b"X"),
        "gname-nul-tail": (298, b"X"),
    }
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l3-hidden-") as temporary:
        for name, (offset, payload) in mutations.items():
            bundle = synthetic_bundle(Path(temporary) / name)
            source = bundle / "source.tar"
            _mutate_first_header(source, offset, payload)
            _refresh_manifest_descriptor_and_hash(bundle, "source.tar")
            _expect_failure(
                lambda bundle=bundle: V.verify_bundle(bundle),
                f"{name} accepted",
            )


def check_load_disk_budget_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l3-disk-") as temporary:
        bundle = synthetic_bundle(Path(temporary))
        bundle_bytes = sum(
            path.stat().st_size for path in bundle.rglob("*") if path.is_file()
        )
        required = V.required_load_free_bytes(bundle)
        if required != (
            V.LOAD_DISK_MULTIPLIER * bundle_bytes
            + V.LOAD_DISK_FIXED_HEADROOM_BYTES
        ):
            raise AssertionError("disk formula mismatch")
        V.check_load_disk_headroom(
            bundle,
            usage_provider=lambda _: SimpleNamespace(free=required),
            platform_name="win32",
        )
        _expect_failure(
            lambda: V.check_load_disk_headroom(
                bundle,
                usage_provider=lambda _: SimpleNamespace(free=required - 1),
                platform_name="win32",
            ),
            "insufficient disk accepted",
        )
        _expect_failure(
            lambda: V.check_load_disk_headroom(
                bundle,
                usage_provider=lambda _: SimpleNamespace(free=required),
                platform_name="linux",
                docker_root_provider=lambda: Path(temporary) / "missing-docker-root",
            ),
            "missing Linux Docker Root Dir accepted",
        )


def check_source_archive_determinism() -> None:
    l2 = B._load_l2_module().build_manifest()
    with tempfile.TemporaryDirectory(prefix="tsing-radar-l3-source-") as temporary:
        first = Path(temporary) / "first.tar"
        second = Path(temporary) / "second.tar"
        B.write_source_archive(l2, first)
        B.write_source_archive(l2, second)
        if B.sha256_file(first) != B.sha256_file(second):
            raise AssertionError("source archive not deterministic")
        members = B.scan_tar_headers(first, allow_directories=False, max_archive_bytes=2 * 1024 * 1024 * 1024)
        if set(members) != {item["path"] for item in l2["source_files"]}:
            raise AssertionError("source archive set mismatch")


def check_no_vendor_archive_or_pull_path() -> None:
    source = BUILDER_PATH.read_text(encoding="utf-8")
    forbidden = (
        '"docker", "image", "pull"',
        "immutable_manifest_pull_failed",
    )
    if any(value in source for value in forbidden):
        raise AssertionError("vendor pull path present in L3 builder")
    if "vendor_archive_capture_forbidden" not in source:
        raise AssertionError("vendor archive fail-closed guard missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", default=None)
    args = parser.parse_args()
    checks = [
        ("schema-contracts", check_schema_contracts),
        ("fixed-slot-contract", check_slot_contract),
        ("two-app-bundle-mutations", check_synthetic_bundle_and_mutations),
        ("l2-manifest-mutations", check_l2_manifest_mutations),
        ("archive-header-mutations", check_archive_header_mutations),
        ("hidden-ustar-header-mutations", check_hidden_ustar_header_mutations),
        ("deterministic-source-archive", check_source_archive_determinism),
        ("load-disk-budget", check_load_disk_budget_contract),
        ("vendor-digest-pull-only", check_no_vendor_archive_or_pull_path),
    ]
    results = []
    try:
        for name, operation in checks:
            operation()
            results.append({"name": name, "status": "passed"})
        if args.bundle:
            V.verify_bundle(Path(args.bundle))
            results.append({"name": "real-bundle-offline-verify", "status": "passed"})
        print(
            json.dumps(
                {
                    "schema_version": "l3-check-result-v1",
                    "status": "passed",
                    "checks": results,
                    "application_archives": 2,
                    "vendor_archives": 0,
                    "cloud_or_git_actions": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (AssertionError, B.HandoffError, V.HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
        reason = exc.args[0] if exc.args else "l3_check_failed"
        print(
            json.dumps(
                {
                    "schema_version": "l3-check-result-v1",
                    "status": "failed",
                    "reason": str(reason),
                    "cloud_or_git_actions": False,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
