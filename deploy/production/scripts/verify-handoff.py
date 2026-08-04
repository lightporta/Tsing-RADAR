#!/usr/bin/env python3
"""Verify an L3 handoff before any extraction, image import, or Compose create."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
BUILDER_PATH = Path(__file__).with_name("build-handoff.py")


def _load_builder():
    spec = importlib.util.spec_from_file_location("tsing_radar_l3_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("l3_builder_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


B = _load_builder()
HandoffError = B.HandoffError

MANIFEST_FIELDS = {
    "schema_version",
    "generation_id",
    "captured_at",
    "target_platform",
    "image_lock",
    "l2_release_manifest",
    "compose_environment",
    "source_archive",
    "image_archives",
    "bundle_policy",
    "integrity_policy",
    "cloud_gates",
}
FILE_DESCRIPTOR_FIELDS = {"path", "size", "sha256"}
APP_ARCHIVES = (
    ("BACKEND_IMAGE", "images/backend.oci.tar"),
    ("FRONTEND_IMAGE", "images/frontend.oci.tar"),
)
FIXED_BUNDLE_FILES = {
    "bundle-manifest.json",
    "bundle-manifest.sha256",
    "image-lock.json",
    "l2-release-manifest.json",
    "compose-images.env",
    "source.tar",
    "images/backend.oci.tar",
    "images/frontend.oci.tar",
}
FIXED_POLICY = {
    "fixed_regular_file_count": 8,
    "application_archive_count": 2,
    "vendor_archive_count": 0,
    "max_bundle_bytes": 2147483648,
}
FIXED_INTEGRITY = {
    "manifest_hash": "detached-sha256-of-exact-bundle-manifest-bytes",
    "archive_validation": "validate-all-headers-and-descriptors-before-extract-or-load",
    "tag_freshness": "separate-non-integrity-gate",
}
LOAD_DISK_MULTIPLIER = 3
LOAD_DISK_FIXED_HEADROOM_BYTES = 2 * 1024 * 1024 * 1024


def _read_json(path: Path, *, max_bytes: int = B.MAX_JSON_BYTES) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise HandoffError("bundle_json_file_invalid")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("bundle_json_invalid") from exc
    if not isinstance(value, dict):
        raise HandoffError("bundle_json_not_object")
    if raw != B.canonical_json_bytes(value):
        raise HandoffError("bundle_json_not_canonical")
    return value


def _safe_bundle_path(bundle: Path, relative: str) -> Path:
    if not relative or "\\" in relative or relative.startswith("/") or re.match(r"^[A-Za-z]:", relative):
        raise HandoffError("bundle_path_invalid")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise HandoffError("bundle_path_not_normalized")
    if parsed.as_posix() != relative:
        raise HandoffError("bundle_path_not_canonical")
    path = bundle.joinpath(*parsed.parts)
    if path.is_symlink() or not path.is_file():
        raise HandoffError("bundle_file_missing_or_symlink")
    try:
        path.resolve(strict=True).relative_to(bundle.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise HandoffError("bundle_file_escape") from exc
    return path


def _validate_file_descriptor(
    bundle: Path,
    descriptor: object,
    *,
    expected_path: str,
) -> Path:
    if not isinstance(descriptor, dict) or set(descriptor) != FILE_DESCRIPTOR_FIELDS:
        raise HandoffError("bundle_file_descriptor_fields_invalid")
    if descriptor.get("path") != expected_path:
        raise HandoffError("bundle_file_descriptor_path_invalid")
    size = descriptor.get("size")
    digest = descriptor.get("sha256")
    if not isinstance(size, int) or size <= 0:
        raise HandoffError("bundle_file_descriptor_size_invalid")
    if not isinstance(digest, str) or not B.DIGEST_RE.fullmatch(digest):
        raise HandoffError("bundle_file_descriptor_digest_invalid")
    path = _safe_bundle_path(bundle, expected_path)
    if path.stat().st_size != size or B.sha256_file(path) != digest:
        raise HandoffError("bundle_file_integrity_failed")
    return path


def _validate_detached_manifest_hash(bundle: Path) -> dict[str, object]:
    manifest_path = _safe_bundle_path(bundle, "bundle-manifest.json")
    detached_path = _safe_bundle_path(bundle, "bundle-manifest.sha256")
    try:
        detached = detached_path.read_text(encoding="ascii")
    except UnicodeDecodeError as exc:
        raise HandoffError("bundle_detached_hash_invalid") from exc
    matched = re.fullmatch(r"([0-9a-f]{64})  bundle-manifest\.json\n", detached)
    if matched is None:
        raise HandoffError("bundle_detached_hash_format_invalid")
    if B.sha256_file(manifest_path) != "sha256:" + matched.group(1):
        raise HandoffError("bundle_detached_hash_mismatch")
    return _read_json(manifest_path)


def _bundle_file_set(bundle: Path) -> None:
    if bundle.is_symlink() or not bundle.is_dir():
        raise HandoffError("bundle_directory_invalid")
    files: list[str] = []
    folded: set[str] = set()
    total = 0
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise HandoffError("bundle_symlink_forbidden")
        if path.is_dir():
            continue
        if not path.is_file():
            raise HandoffError("bundle_nonregular_file_forbidden")
        relative = path.relative_to(bundle).as_posix()
        if relative.casefold() in folded:
            raise HandoffError("bundle_case_collision")
        folded.add(relative.casefold())
        files.append(relative)
        total += path.stat().st_size
    if set(files) != FIXED_BUNDLE_FILES or len(files) != len(FIXED_BUNDLE_FILES):
        raise HandoffError("bundle_file_set_invalid")
    if total > FIXED_POLICY["max_bundle_bytes"]:
        raise HandoffError("bundle_size_budget_exceeded")


def _validate_l2_source_archive(l2: Mapping[str, object], archive: Path) -> None:
    entries = l2.get("source_files")
    if not isinstance(entries, list) or not entries:
        raise HandoffError("l2_source_entries_invalid")
    members = B.scan_tar_headers(archive, allow_directories=False, max_archive_bytes=2 * 1024 * 1024 * 1024)
    expected: dict[str, dict[str, object]] = {}
    ordered: list[str] = []
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise HandoffError("l2_source_entry_invalid")
        path = str(item["path"])
        B._normalize_archive_name(path, directory=False)
        if path in expected or path.casefold() in {value.casefold() for value in expected}:
            raise HandoffError("l2_source_path_duplicate")
        expected[path] = item
        ordered.append(path)
    if ordered != sorted(ordered) or list(members) != ordered:
        raise HandoffError("source_archive_file_set_invalid")
    for path, item in expected.items():
        member = members[path]
        B.validate_deterministic_member_metadata(
            member,
            expected_mode=B._source_mode(path),
        )
        if member.size != item["size"] or B.hash_member(archive, member) != item["sha256"]:
            raise HandoffError("source_archive_integrity_failed")


def _validate_l2_contract_and_lock_binding(
    l2: Mapping[str, object],
    lock: Mapping[str, object],
) -> None:
    module = B._load_l2_module()
    try:
        module.validate_manifest_contract(l2, ROOT)
    except (module.ReleaseManifestError, OSError, ValueError) as exc:
        reason = exc.args[0] if exc.args else "l2_manifest_contract_invalid"
        raise HandoffError(f"l2_manifest_contract_invalid:{reason}") from exc
    applications = l2.get("application_images")
    slots = [item for item in lock["slots"] if item["kind"] == "application"]
    if not isinstance(applications, list) or len(applications) != len(slots):
        raise HandoffError("l2_application_lock_binding_invalid")
    for application, slot in zip(applications, slots, strict=True):
        observation = slot.get("engine_observation")
        if (
            not isinstance(application, dict)
            or not isinstance(observation, dict)
            or application.get("role") != slot.get("role")
            or application.get("local_reference") != slot.get("source_reference")
            or application.get("image_id") != observation.get("image_id")
            or observation.get("descriptor_digest") != slot.get("index", {}).get("digest")
            or observation.get("semantic") != B.ENGINE_OBSERVATION_SEMANTIC
        ):
            raise HandoffError("l2_application_lock_binding_invalid")


def _expected_image_member_set(slot: Mapping[str, object]) -> set[str]:
    digests = [
        slot["index"]["digest"],
        slot["manifest"]["digest"],
        slot["config"]["digest"],
    ]
    digests.extend(layer["digest"] for layer in slot["layers"])
    return {
        "index.json",
        "oci-layout",
        *("blobs/sha256/" + str(digest).removeprefix("sha256:") for digest in digests),
    }


def validate_app_archive(archive: Path, slot: Mapping[str, object]) -> B.ImageChain:
    if slot.get("kind") != "application" or slot.get("delivery_mode") != "oci_archive":
        raise HandoffError("application_archive_delivery_mode_invalid")
    members = B.scan_tar_headers(archive, allow_directories=False)
    expected_members = _expected_image_member_set(slot)
    if list(members) != sorted(expected_members):
        raise HandoffError("application_archive_member_set_invalid")
    for member in members.values():
        B.validate_deterministic_member_metadata(member, expected_mode=0o644)
    source_index_descriptor = {
        "media_type": slot["index"]["media_type"],
        "digest": slot["index"]["digest"],
        "size": slot["index"]["size"],
    }
    source_index_member = B._descriptor_blob_member(
        archive,
        members,
        source_index_descriptor,
    )
    source_index = B._json_member(archive, source_index_member)
    if source_index.get("mediaType") not in B.INDEX_MEDIA_TYPES:
        raise HandoffError("application_source_index_media_type_invalid")
    source_candidates = [
        item
        for item in source_index.get("manifests", [])
        if isinstance(item, dict) and item.get("platform") == B.TARGET_PLATFORM
    ]
    if len(source_candidates) != 1:
        raise HandoffError("application_source_index_platform_not_unique")
    source_child = source_candidates[0]
    if (
        source_child.get("mediaType") != slot["manifest"]["media_type"]
        or source_child.get("digest") != slot["manifest"]["digest"]
        or source_child.get("size") != slot["manifest"]["size"]
    ):
        raise HandoffError("application_source_index_manifest_mismatch")
    index = B._json_member(archive, members["index.json"])
    top = index.get("manifests")
    if not isinstance(top, list) or len(top) != 1 or not isinstance(top[0], dict):
        raise HandoffError("application_archive_index_invalid")
    expected_annotations = {
        "io.containerd.image.name": (
            f"docker.io/{slot['import_repository']}:{slot['import_tag']}"
        ),
        "org.opencontainers.image.ref.name": str(slot["import_tag"]),
    }
    if (
        top[0].get("mediaType") != slot["manifest"]["media_type"]
        or top[0].get("digest") != slot["manifest"]["digest"]
        or top[0].get("size") != slot["manifest"]["size"]
        or top[0].get("platform") != B.TARGET_PLATFORM
        or top[0].get("annotations") != expected_annotations
    ):
        raise HandoffError("application_archive_index_contract_invalid")
    if B.read_member(archive, members["index.json"]) != B.canonical_json_bytes(index):
        raise HandoffError("application_archive_index_not_canonical")
    if B.read_member(archive, members["oci-layout"]) != B.canonical_json_bytes(
        {"imageLayoutVersion": "1.0.0"}
    ):
        raise HandoffError("application_archive_layout_not_canonical")
    chain = B.parse_oci_archive(archive)
    if chain.root["digest"] != slot["manifest"]["digest"]:
        raise HandoffError("application_archive_not_manifest_rooted")
    if chain.manifest != slot["manifest"]:
        raise HandoffError("application_archive_manifest_mismatch")
    if chain.config != slot["config"]:
        raise HandoffError("application_archive_config_mismatch")
    if list(chain.layers) != slot["layers"]:
        raise HandoffError("application_archive_layers_mismatch")
    return chain


def _validate_compose_environment(path: Path, lock: Mapping[str, object]) -> None:
    expected = [
        "# Generated L3 offline image references; contains no credentials.",
        "# Loading and using these images on a server remains a separately approved cloud gate.",
    ]
    expected.extend(
        f"{item['slot']}={item['compose_reference']}" for item in lock["slots"]
    )
    try:
        actual = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HandoffError("compose_environment_encoding_invalid") from exc
    if actual != "\n".join(expected) + "\n":
        raise HandoffError("compose_environment_contract_invalid")


def verify_bundle(bundle: Path) -> tuple[dict[str, object], dict[str, object]]:
    bundle = bundle.resolve(strict=True)
    _bundle_file_set(bundle)
    manifest = _validate_detached_manifest_hash(bundle)
    if set(manifest) != MANIFEST_FIELDS:
        raise HandoffError("handoff_manifest_fields_invalid")
    if manifest.get("schema_version") != "l3-handoff-manifest-v1":
        raise HandoffError("handoff_manifest_schema_invalid")
    if not isinstance(manifest.get("generation_id"), str) or not B.GENERATION_RE.fullmatch(str(manifest["generation_id"])):
        raise HandoffError("handoff_generation_id_invalid")
    if manifest.get("target_platform") != B.TARGET_PLATFORM:
        raise HandoffError("handoff_platform_invalid")
    if not isinstance(manifest.get("captured_at"), str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        str(manifest.get("captured_at")),
    ):
        raise HandoffError("handoff_capture_time_invalid")
    if manifest.get("bundle_policy") != FIXED_POLICY:
        raise HandoffError("handoff_bundle_policy_invalid")
    if manifest.get("integrity_policy") != FIXED_INTEGRITY:
        raise HandoffError("handoff_integrity_policy_invalid")
    if manifest.get("cloud_gates") != list(B.CLOUD_GATES):
        raise HandoffError("handoff_cloud_gates_invalid")

    lock_path = _validate_file_descriptor(bundle, manifest["image_lock"], expected_path="image-lock.json")
    l2_path = _validate_file_descriptor(
        bundle,
        manifest["l2_release_manifest"],
        expected_path="l2-release-manifest.json",
    )
    compose_environment_path = _validate_file_descriptor(
        bundle,
        manifest["compose_environment"],
        expected_path="compose-images.env",
    )
    source_path = _validate_file_descriptor(bundle, manifest["source_archive"], expected_path="source.tar")
    lock = _read_json(lock_path)
    B.validate_image_lock(lock)
    if lock["captured_at"] != manifest["captured_at"]:
        raise HandoffError("handoff_capture_time_mismatch")
    _validate_compose_environment(compose_environment_path, lock)
    l2 = _read_json(l2_path)
    _validate_l2_contract_and_lock_binding(l2, lock)
    _validate_l2_source_archive(l2, source_path)

    archives = manifest.get("image_archives")
    if not isinstance(archives, list) or len(archives) != 2:
        raise HandoffError("application_archive_count_invalid")
    slots_by_name = {item["slot"]: item for item in lock["slots"]}
    for index, (expected_slot, expected_path) in enumerate(APP_ARCHIVES):
        descriptor = archives[index]
        if not isinstance(descriptor, dict) or set(descriptor) != {"slot", "path", "size", "sha256"}:
            raise HandoffError("application_archive_descriptor_fields_invalid")
        if descriptor.get("slot") != expected_slot:
            raise HandoffError("application_archive_slot_order_invalid")
        archive = _validate_file_descriptor(
            bundle,
            {key: descriptor[key] for key in FILE_DESCRIPTOR_FIELDS},
            expected_path=expected_path,
        )
        validate_app_archive(archive, slots_by_name[expected_slot])
    if any(
        item["kind"] == "vendor" and item["delivery_mode"] != "digest_pull"
        for item in lock["slots"]
    ):
        raise HandoffError("vendor_delivery_mode_invalid")
    return manifest, lock


def _run(arguments: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(arguments),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandoffError("verification_subprocess_failed") from exc


def required_load_free_bytes(bundle: Path) -> int:
    total = sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())
    if total <= 0 or total > FIXED_POLICY["max_bundle_bytes"]:
        raise HandoffError("load_disk_bundle_size_invalid")
    return LOAD_DISK_MULTIPLIER * total + LOAD_DISK_FIXED_HEADROOM_BYTES


def _docker_root_dir() -> Path:
    completed = _run(
        ["docker", "info", "--format", "{{json .DockerRootDir}}"],
        timeout=30,
    )
    if completed.returncode != 0:
        raise HandoffError("docker_root_dir_unavailable")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HandoffError("docker_root_dir_unavailable") from exc
    if not isinstance(value, str) or not value:
        raise HandoffError("docker_root_dir_unavailable")
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise HandoffError("docker_root_dir_unavailable")
    return path


def check_load_disk_headroom(
    bundle: Path,
    *,
    usage_provider: Callable[[Path], object] = shutil.disk_usage,
    platform_name: str = sys.platform,
    docker_root_provider: Callable[[], Path] = _docker_root_dir,
) -> int:
    required = required_load_free_bytes(bundle)
    targets = [bundle.resolve(strict=True), Path(tempfile.gettempdir()).resolve(strict=True)]
    if platform_name.startswith("linux"):
        try:
            targets.append(docker_root_provider().resolve(strict=True))
        except (HandoffError, OSError, RuntimeError) as exc:
            raise HandoffError("docker_root_disk_headroom_unverifiable") from exc
    for target in targets:
        try:
            free = int(usage_provider(target).free)
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise HandoffError("load_disk_headroom_unverifiable") from exc
        if free < required:
            raise HandoffError("load_disk_headroom_insufficient")
    return required


def _inspect_loaded(reference: str, slot: Mapping[str, object]) -> None:
    completed = _run(
        ["docker", "image", "inspect", reference, "--format", "{{json .}}"],
        timeout=30,
    )
    if completed.returncode != 0:
        raise HandoffError("loaded_image_inspect_failed")
    try:
        inspected = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise HandoffError("loaded_image_inspect_invalid") from exc
    if inspected.get("Os") != "linux" or inspected.get("Architecture") != "amd64":
        raise HandoffError("loaded_image_platform_invalid")
    if reference not in inspected.get("RepoDigests", []):
        raise HandoffError("loaded_image_repo_digest_missing")
    descriptor = inspected.get("Descriptor")
    if isinstance(descriptor, dict) and descriptor.get("digest") != slot["manifest"]["digest"]:
        raise HandoffError("loaded_image_descriptor_mismatch")


def _reexport_and_verify(
    reference: str,
    slot: Mapping[str, object],
    output: Path,
) -> None:
    completed = _run(
        ["docker", "image", "save", "--output", str(output), reference],
        timeout=900,
    )
    if completed.returncode != 0:
        raise HandoffError("loaded_image_reexport_failed")
    chain = B.parse_oci_archive(output, require_canonical_header=False)
    if chain.manifest != slot["manifest"] or chain.config != slot["config"] or list(chain.layers) != slot["layers"]:
        raise HandoffError("loaded_image_reexport_chain_mismatch")


def _compose_create_probe(
    slots: Sequence[Mapping[str, object]],
    work: Path,
    project: str,
) -> None:
    compose_path = work / "compose.probe.yml"
    lines = ["services:"]
    for slot in slots:
        service = str(slot["role"])
        lines.extend(
            [
                f"  {service}:",
                f"    image: {slot['compose_reference']}",
                "    network_mode: none",
                "    read_only: true",
                "    cap_drop: [\"ALL\"]",
                "    security_opt: [\"no-new-privileges:true\"]",
            ]
        )
    compose_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    primary_error: BaseException | None = None
    try:
        completed = _run(
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_path),
                "create",
                "--pull",
                "never",
            ],
            timeout=120,
        )
        if completed.returncode != 0:
            raise HandoffError("compose_locked_create_failed")
        for slot in slots:
            service = str(slot["role"])
            found = _run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--filter",
                    f"label=com.docker.compose.service={service}",
                    "--format",
                    "{{.ID}}",
                ],
                timeout=30,
            )
            identifiers = [line for line in found.stdout.splitlines() if line.strip()]
            if found.returncode != 0 or len(identifiers) != 1:
                raise HandoffError("compose_probe_container_identity_invalid")
            inspected = _run(
                ["docker", "container", "inspect", identifiers[0]],
                timeout=30,
            )
            value = json.loads(inspected.stdout)[0]
            if value["HostConfig"]["NetworkMode"] != "none":
                raise HandoffError("compose_probe_network_forbidden")
            if value.get("Mounts"):
                raise HandoffError("compose_probe_mount_forbidden")
            ports = value.get("NetworkSettings", {}).get("Ports") or {}
            if ports:
                raise HandoffError("compose_probe_port_forbidden")
            if value.get("Image") != slot["manifest"]["digest"]:
                raise HandoffError("compose_probe_manifest_mismatch")
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleaned = _run(
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_path),
                "rm",
                "--force",
                "--stop",
            ],
            timeout=120,
        )
        if cleaned.returncode != 0 and primary_error is None:
            raise HandoffError("compose_probe_cleanup_failed")


def load_and_probe(bundle: Path, lock: Mapping[str, object]) -> None:
    check_load_disk_headroom(bundle)
    app_slots = [item for item in lock["slots"] if item["delivery_mode"] == "oci_archive"]
    if [item["slot"] for item in app_slots] != [item[0] for item in APP_ARCHIVES]:
        raise HandoffError("application_slot_set_invalid")
    for slot in app_slots:
        tag = f"{slot['import_repository']}:{slot['import_tag']}"
        existing = _run(["docker", "image", "inspect", tag], timeout=30)
        if existing.returncode == 0:
            raise HandoffError("offline_import_reference_preexists")

    work = Path(tempfile.gettempdir()) / f"tsing-radar-l3-verify-{uuid.uuid4().hex}"
    work.mkdir()
    marker = work / ".tsing-radar-l3-verify"
    marker.write_text("owned\n", encoding="ascii")
    loaded_tags: list[str] = []
    project = "tsingradar-l3-" + uuid.uuid4().hex[:12]
    primary_error: BaseException | None = None
    try:
        for slot, (_, relative) in zip(app_slots, APP_ARCHIVES, strict=True):
            archive = _safe_bundle_path(bundle, relative)
            tag = f"{slot['import_repository']}:{slot['import_tag']}"
            loaded_tags.append(tag)
            loaded = _run(
                ["docker", "image", "load", "--input", str(archive)],
                timeout=900,
            )
            if loaded.returncode != 0:
                raise HandoffError("offline_image_load_failed")
            reference = str(slot["compose_reference"])
            _inspect_loaded(reference, slot)
            _reexport_and_verify(reference, slot, work / f"{slot['role']}.reexport.oci.tar")
        _compose_create_probe(app_slots, work, project)
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_failed = False
        for tag in reversed(loaded_tags):
            removed = _run(["docker", "image", "rm", tag], timeout=120)
            if removed.returncode != 0:
                cleanup_failed = True
        for slot in app_slots:
            remaining = _run(
                ["docker", "image", "inspect", str(slot["compose_reference"])],
                timeout=30,
            )
            if remaining.returncode == 0:
                cleanup_failed = True
        if marker.is_file() and marker.read_text(encoding="ascii") == "owned\n":
            for child in work.iterdir():
                if child.is_file():
                    child.unlink()
                else:
                    cleanup_failed = True
            try:
                work.rmdir()
            except OSError:
                cleanup_failed = True
        else:
            cleanup_failed = True
        if cleanup_failed and primary_error is None:
            raise HandoffError("offline_probe_cleanup_failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--load-images", action="store_true")
    args = parser.parse_args()
    try:
        bundle = Path(args.bundle)
        manifest, lock = verify_bundle(bundle)
        if args.load_images:
            load_and_probe(bundle.resolve(strict=True), lock)
        print(
            json.dumps(
                {
                    "schema_version": "l3-verify-result-v1",
                    "status": "passed",
                    "generation_id": manifest["generation_id"],
                    "application_archives": 2,
                    "vendor_archives": 0,
                    "vendor_delivery": "digest_pull_cloud_gate",
                    "loaded_and_compose_created": bool(args.load_images),
                    "target_platform": "linux/amd64",
                    "uploaded": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
        reason = exc.args[0] if exc.args else "handoff_verification_failed"
        print(
            json.dumps(
                {
                    "schema_version": "l3-verify-result-v1",
                    "status": "failed",
                    "reason": str(reason),
                    "uploaded": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
