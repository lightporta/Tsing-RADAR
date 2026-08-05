from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "scripts" / "check_l3_handoff.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("tsing_radar_l3_test_checker", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


C = _load_checker()
B = C.B
V = C.V


def test_l3_slot_set_is_exact_and_vendor_delivery_is_digest_pull():
    assert [item["slot"] for item in B.SLOT_SPECS] == [
        "POSTGRES_IMAGE",
        "REDIS_IMAGE",
        "ETCD_IMAGE",
        "MINIO_IMAGE",
        "MILVUS_IMAGE",
        "CLAMAV_IMAGE",
        "BACKEND_IMAGE",
        "FRONTEND_IMAGE",
        "CADDY_IMAGE",
        "NGINX_UNPRIVILEGED_IMAGE",
    ]
    assert all(
        item["source_tag"] not in {"latest", "mainline", "stable", "alpine"}
        for item in B.SLOT_SPECS
    )


def test_handoff_schema_allows_exactly_two_application_archives():
    schema = json.loads(B.HANDOFF_SCHEMA.read_text(encoding="utf-8"))
    archives = schema["properties"]["image_archives"]
    assert archives["minItems"] == archives["maxItems"] == 2
    assert archives["items"] is False
    assert [
        item["allOf"][1]["properties"]["slot"]["const"]
        for item in archives["prefixItems"]
    ] == ["BACKEND_IMAGE", "FRONTEND_IMAGE"]
    assert schema["properties"]["bundle_policy"]["properties"][
        "vendor_archive_count"
    ]["const"] == 0


def test_synthetic_bundle_verifies_with_two_app_archives(tmp_path: Path):
    bundle = C.synthetic_bundle(tmp_path)
    manifest, lock = V.verify_bundle(bundle)
    assert [item["slot"] for item in manifest["image_archives"]] == [
        "BACKEND_IMAGE",
        "FRONTEND_IMAGE",
    ]
    assert [
        item["delivery_mode"]
        for item in lock["slots"]
        if item["kind"] == "application"
    ] == ["oci_archive", "oci_archive"]
    assert all(
        item["delivery_mode"] == "digest_pull"
        for item in lock["slots"]
        if item["kind"] == "vendor"
    )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "duplicate", "slot_swap", "path_swap", "vendor_injection"),
)
def test_application_archive_contract_rejects_missing_duplicate_swap_and_vendor(
    tmp_path: Path,
    mutation: str,
):
    bundle = C.synthetic_bundle(tmp_path)
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    archives = manifest["image_archives"]
    if mutation == "missing":
        archives.pop()
    elif mutation == "duplicate":
        archives[1] = deepcopy(archives[0])
    elif mutation == "slot_swap":
        archives[0]["slot"], archives[1]["slot"] = (
            archives[1]["slot"],
            archives[0]["slot"],
        )
    elif mutation == "path_swap":
        archives[0]["path"], archives[1]["path"] = (
            archives[1]["path"],
            archives[0]["path"],
        )
    else:
        archives[0]["slot"] = "POSTGRES_IMAGE"
    manifest_path.write_bytes(B.canonical_json_bytes(manifest))
    C._write_detached(bundle)
    with pytest.raises(V.HandoffError):
        V.verify_bundle(bundle)


def test_detached_manifest_hash_and_manifest_tamper_fail(tmp_path: Path):
    bundle = C.synthetic_bundle(tmp_path)
    manifest_path = bundle / "bundle-manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
    with pytest.raises(V.HandoffError, match="detached_hash_mismatch"):
        V.verify_bundle(bundle)

    bundle = C.synthetic_bundle(tmp_path / "second")
    (bundle / "bundle-manifest.sha256").write_text(
        "0" * 64 + "  bundle-manifest.json\n",
        encoding="ascii",
    )
    with pytest.raises(V.HandoffError, match="detached_hash_mismatch"):
        V.verify_bundle(bundle)


@pytest.mark.parametrize("mutation", ("index_size", "config_size", "manifest_digest"))
def test_oci_descriptor_size_and_digest_tamper_fail(tmp_path: Path, mutation: str):
    bundle = C.synthetic_bundle(tmp_path)
    lock_path = bundle / "image-lock.json"
    lock = json.loads(lock_path.read_bytes())
    if mutation == "index_size":
        lock["slots"][6]["index"]["size"] += 1
    elif mutation == "config_size":
        lock["slots"][6]["config"]["size"] += 1
    else:
        lock["slots"][6]["manifest"]["digest"] = "sha256:" + "0" * 64
        lock["slots"][6]["compose_reference"] = (
            "tsing-radar-offline/backend@sha256:" + "0" * 64
        )
    lock_path.write_bytes(B.canonical_json_bytes(lock))
    C._refresh_manifest_descriptor_and_hash(bundle, "image-lock.json")
    with pytest.raises((V.HandoffError, B.HandoffError)):
        V.verify_bundle(bundle)


def test_compose_environment_tamper_fails_even_when_outer_hashes_are_updated(
    tmp_path: Path,
):
    bundle = C.synthetic_bundle(tmp_path)
    path = bundle / "compose-images.env"
    path.write_text(path.read_text(encoding="utf-8") + "EXTRA=forbidden\n", encoding="utf-8")
    C._refresh_manifest_descriptor_and_hash(bundle, "compose-images.env")
    with pytest.raises(V.HandoffError, match="compose_environment_contract_invalid"):
        V.verify_bundle(bundle)


def test_nonzero_tar_padding_and_metadata_fail(tmp_path: Path):
    archive = tmp_path / "padding.tar"
    with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as target:
        C._add_bytes(target, "one", b"x")
    with archive.open("r+b") as handle:
        handle.seek(512 + 1)
        handle.write(b"X")
    with pytest.raises(B.HandoffError, match="nonzero_member_padding"):
        B.scan_tar_headers(archive, allow_directories=False)

    metadata = tmp_path / "metadata.tar"
    info = tarfile.TarInfo("one")
    info.size = 1
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.mtime = 1
    with tarfile.open(metadata, "w", format=tarfile.USTAR_FORMAT) as target:
        target.addfile(info, io.BytesIO(b"x"))
    member = B.scan_tar_headers(metadata, allow_directories=False)["one"]
    with pytest.raises(B.HandoffError, match="metadata_not_deterministic"):
        B.validate_deterministic_member_metadata(member, expected_mode=0o644)


@pytest.mark.parametrize(
    "name,typeflag",
    [
        ("../escape", tarfile.REGTYPE),
        ("absolute", tarfile.SYMTYPE),
        ("device", tarfile.CHRTYPE),
        ("fifo", tarfile.FIFOTYPE),
    ],
)
def test_archive_header_parser_fails_closed_on_unsafe_types_and_paths(
    tmp_path: Path,
    name: str,
    typeflag: bytes,
):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as target:
        C._add_bytes(target, name, b"x", typeflag=typeflag)
    with pytest.raises(B.HandoffError):
        B.scan_tar_headers(archive, allow_directories=False)


def test_source_archive_is_byte_deterministic(tmp_path: Path):
    l2 = B._load_l2_module().build_manifest()
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    B.write_source_archive(l2, first)
    B.write_source_archive(l2, second)
    assert B.sha256_file(first) == B.sha256_file(second)
    assert B.scan_tar_headers(first, allow_directories=False)


def test_l3_builder_has_no_vendor_pull_or_vendor_archive_path():
    C.check_no_vendor_archive_or_pull_path()


def test_l2_manifest_semantic_mutations_fail_after_outer_hash_refresh():
    C.check_l2_manifest_mutations()


def test_hidden_ustar_header_fields_fail_after_checksum_and_outer_hash_refresh():
    C.check_hidden_ustar_header_mutations()


def test_load_disk_budget_boundary_and_linux_root_fail_closed():
    C.check_load_disk_budget_contract()


def test_l3_static_checker_passes():
    C.check_schema_contracts()
    C.check_slot_contract()
    C.check_synthetic_bundle_and_mutations()
    C.check_l2_manifest_mutations()
    C.check_archive_header_mutations()
    C.check_hidden_ustar_header_mutations()
    C.check_load_disk_budget_contract()
