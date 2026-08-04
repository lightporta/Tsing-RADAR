#!/usr/bin/env python3
"""Build an offline, content-addressed linux/amd64 deployment handoff.

The handoff is a local artifact only. It never uploads, publishes, opens a port,
or reads deployment secrets. Vendor tags are consulted only while capturing an
immutable index -> manifest -> config/layer chain. Offline verification uses
the captured digests and archives, never the mutable tags.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = ROOT / "deploy" / "production"
HANDOFF_ROOT = ROOT / ".l3-handoff"
IMAGE_LOCK_OUTPUT = PRODUCTION / "image-lock.local.json"
L2_MANIFEST_OUTPUT = PRODUCTION / "release-manifest.local.json"
IMAGE_LOCK_SCHEMA = PRODUCTION / "image-lock.schema.json"
HANDOFF_SCHEMA = PRODUCTION / "handoff-manifest.schema.json"

TARGET_PLATFORM = {"os": "linux", "architecture": "amd64"}
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
GENERATION_RE = re.compile(r"l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z")
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 50_000
MAX_MEMBER_BYTES = 8 * 1024 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
COPY_BLOCK_BYTES = 1024 * 1024
MIN_BUILD_FREE_BYTES = 5 * 1024 * 1024 * 1024
MAX_APPLICATION_IMAGE_BYTES = 1536 * 1024 * 1024

INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
CONFIG_MEDIA_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
LAYER_MEDIA_PREFIXES = (
    "application/vnd.oci.image.layer.",
    "application/vnd.docker.image.rootfs.diff.tar",
)


SLOT_SPECS: tuple[dict[str, str], ...] = (
    {
        "slot": "POSTGRES_IMAGE",
        "role": "postgres",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "library/postgres",
        "source_tag": "16-alpine",
        "source_reference": "postgres:16-alpine",
        "pull_repository": "postgres",
        "import_repository": "tsing-radar-offline/postgres",
    },
    {
        "slot": "REDIS_IMAGE",
        "role": "redis",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "library/redis",
        "source_tag": "7-alpine",
        "source_reference": "redis:7-alpine",
        "pull_repository": "redis",
        "import_repository": "tsing-radar-offline/redis",
    },
    {
        "slot": "ETCD_IMAGE",
        "role": "etcd",
        "kind": "vendor",
        "registry": "quay.io",
        "repository": "coreos/etcd",
        "source_tag": "v3.5.18",
        "source_reference": "quay.io/coreos/etcd:v3.5.18",
        "pull_repository": "quay.io/coreos/etcd",
        "import_repository": "tsing-radar-offline/etcd",
    },
    {
        "slot": "MINIO_IMAGE",
        "role": "minio",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "minio/minio",
        "source_tag": "RELEASE.2024-12-18T13-15-44Z",
        "source_reference": "minio/minio:RELEASE.2024-12-18T13-15-44Z",
        "pull_repository": "minio/minio",
        "import_repository": "tsing-radar-offline/minio",
    },
    {
        "slot": "MILVUS_IMAGE",
        "role": "milvus",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "milvusdb/milvus",
        "source_tag": "v2.5.27",
        "source_reference": "milvusdb/milvus:v2.5.27",
        "pull_repository": "milvusdb/milvus",
        "import_repository": "tsing-radar-offline/milvus",
    },
    {
        "slot": "CLAMAV_IMAGE",
        "role": "clamav",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "clamav/clamav-debian",
        "source_tag": "1.4",
        "source_reference": "clamav/clamav-debian:1.4",
        "pull_repository": "clamav/clamav-debian",
        "import_repository": "tsing-radar-offline/clamav",
    },
    {
        "slot": "BACKEND_IMAGE",
        "role": "backend",
        "kind": "application",
        "registry": "local-engine",
        "repository": "tsing-radar-backend",
        "source_tag": "l2-local",
        "source_reference": "tsing-radar-backend:l2-local",
        "pull_repository": "",
        "import_repository": "tsing-radar-offline/backend",
    },
    {
        "slot": "FRONTEND_IMAGE",
        "role": "frontend",
        "kind": "application",
        "registry": "local-engine",
        "repository": "tsing-radar-frontend",
        "source_tag": "l2-local",
        "source_reference": "tsing-radar-frontend:l2-local",
        "pull_repository": "",
        "import_repository": "tsing-radar-offline/frontend",
    },
    {
        "slot": "CADDY_IMAGE",
        "role": "edge",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "library/caddy",
        "source_tag": "2.10.2-alpine",
        "source_reference": "caddy:2.10.2-alpine",
        "pull_repository": "caddy",
        "import_repository": "tsing-radar-offline/caddy",
    },
    {
        "slot": "NGINX_UNPRIVILEGED_IMAGE",
        "role": "protocol-media-gateway",
        "kind": "vendor",
        "registry": "docker.io",
        "repository": "nginxinc/nginx-unprivileged",
        "source_tag": "1.31.3-alpine3.24",
        "source_reference": "nginxinc/nginx-unprivileged:1.31.3-alpine3.24",
        "pull_repository": "nginxinc/nginx-unprivileged",
        "import_repository": "tsing-radar-offline/nginx-unprivileged",
    },
)

SLOT_FIELDS = {
    "slot",
    "role",
    "kind",
    "registry",
    "repository",
    "source_tag",
    "source_reference",
    "import_repository",
    "import_tag",
    "delivery_mode",
    "compose_reference",
    "index",
    "manifest",
    "config",
    "layers",
}
DESCRIPTOR_FIELDS = {"media_type", "digest", "size"}
ENGINE_OBSERVATION_FIELDS = {"image_id", "descriptor_digest", "semantic"}
ENGINE_OBSERVATION_SEMANTIC = "engine-specific-informational-not-config-authority"
CLOUD_GATES = (
    "target_docker_load_inspect_and_compose_create",
    "target_vendor_digest_pull_and_inspect",
    "final_candidate_secret_pii_authorization_scan",
    "real_secret_uid_mode",
    "real_cos_clamav_database_backup_restore",
    "dns_tls_icp_and_public_surface_authorization",
)


class HandoffError(RuntimeError):
    """Stable, non-secret L3 failure."""


@dataclass(frozen=True)
class TarMember:
    name: str
    data_offset: int
    size: int
    typeflag: bytes
    mode: int
    uid: int
    gid: int
    mtime: int
    uname: str
    gname: str


@dataclass(frozen=True)
class ImageChain:
    root: dict[str, object]
    manifest: dict[str, object]
    config: dict[str, object]
    layers: tuple[dict[str, object], ...]
    members: Mapping[str, TarMember]


class SliceReader(io.RawIOBase):
    def __init__(self, path: Path, offset: int, size: int) -> None:
        self._handle: BinaryIO = path.open("rb")
        self._handle.seek(offset)
        self._remaining = size

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        if self._remaining <= 0:
            return 0
        requested = min(len(buffer), self._remaining)
        data = self._handle.read(requested)
        if not data:
            raise HandoffError("archive_member_truncated")
        buffer[: len(data)] = data
        self._remaining -= len(data)
        return len(data)

    def close(self) -> None:
        self._handle.close()
        super().close()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(COPY_BLOCK_BYTES)
            if not block:
                break
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _parse_tar_number(raw: bytes) -> int:
    if raw and raw[0] & 0x80:
        raise HandoffError("archive_base256_number_forbidden")
    stripped = raw.rstrip(b"\0 ").lstrip(b" ")
    if not stripped:
        return 0
    if any(byte not in b"01234567" for byte in stripped):
        raise HandoffError("archive_number_invalid")
    return int(stripped, 8)


def _normalize_archive_name(raw_name: str, *, directory: bool) -> str:
    if "\\" in raw_name or "\0" in raw_name:
        raise HandoffError("archive_path_invalid")
    candidate = raw_name[:-1] if directory and raw_name.endswith("/") else raw_name
    if not candidate or candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise HandoffError("archive_path_not_relative")
    parsed = PurePosixPath(candidate)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise HandoffError("archive_path_not_normalized")
    normalized = parsed.as_posix()
    if normalized != candidate:
        raise HandoffError("archive_path_not_canonical")
    return normalized + ("/" if directory else "")


def _canonical_ustar_header(
    name: str,
    *,
    size: int,
    typeflag: bytes,
    mode: int,
    uid: int,
    gid: int,
    mtime: int,
    uname: str,
    gname: str,
) -> bytes:
    """Rebuild the only USTAR header representation accepted by this bundle."""
    info = tarfile.TarInfo(name)
    info.size = size
    info.type = tarfile.DIRTYPE if typeflag == b"5" else tarfile.REGTYPE
    info.mode = mode
    info.uid = uid
    info.gid = gid
    info.mtime = mtime
    info.uname = uname
    info.gname = gname
    info.linkname = ""
    try:
        header = info.tobuf(
            format=tarfile.USTAR_FORMAT,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeError, ValueError) as exc:
        raise HandoffError("archive_header_not_canonical") from exc
    if len(header) != 512:
        raise HandoffError("archive_header_not_canonical")
    return header


def scan_tar_headers(
    path: Path,
    *,
    allow_directories: bool,
    max_archive_bytes: int = MAX_ARCHIVE_BYTES,
    require_canonical_header: bool = True,
) -> dict[str, TarMember]:
    try:
        archive_size = path.stat().st_size
    except OSError as exc:
        raise HandoffError("archive_missing") from exc
    if archive_size <= 0 or archive_size > max_archive_bytes:
        raise HandoffError("archive_size_out_of_budget")
    members: dict[str, TarMember] = {}
    casefolded: dict[str, str] = {}
    declared_total = 0
    zero_blocks = 0
    with path.open("rb") as handle:
        while handle.tell() < archive_size:
            header_offset = handle.tell()
            header = handle.read(512)
            if len(header) != 512:
                raise HandoffError("archive_header_truncated")
            if header == b"\0" * 512:
                zero_blocks += 1
                if zero_blocks >= 2:
                    trailing = handle.read()
                    if any(trailing):
                        raise HandoffError("archive_nonzero_trailing_data")
                    break
                continue
            if zero_blocks:
                raise HandoffError("archive_single_zero_block")
            stored_checksum = _parse_tar_number(header[148:156])
            computed_checksum = sum(header[:148]) + (8 * 32) + sum(header[156:])
            if stored_checksum != computed_checksum:
                raise HandoffError("archive_header_checksum_invalid")
            if header[257:263] != b"ustar\0":
                raise HandoffError("archive_header_format_not_ustar")
            typeflag = header[156:157]
            is_regular = typeflag in {b"", b"\0", b"0"}
            is_directory = typeflag == b"5"
            if not is_regular and not (allow_directories and is_directory):
                raise HandoffError("archive_member_type_forbidden")
            name_bytes = header[0:100].split(b"\0", 1)[0]
            prefix_bytes = header[345:500].split(b"\0", 1)[0]
            try:
                name = name_bytes.decode("utf-8")
                prefix = prefix_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HandoffError("archive_path_encoding_invalid") from exc
            raw_name = f"{prefix}/{name}" if prefix else name
            normalized = _normalize_archive_name(raw_name, directory=is_directory)
            folded = normalized.casefold()
            if normalized in members:
                raise HandoffError("archive_duplicate_member")
            if folded in casefolded and casefolded[folded] != normalized:
                raise HandoffError("archive_case_collision")
            size = _parse_tar_number(header[124:136])
            mode = _parse_tar_number(header[100:108])
            uid = _parse_tar_number(header[108:116])
            gid = _parse_tar_number(header[116:124])
            mtime = _parse_tar_number(header[136:148])
            try:
                uname = header[265:297].split(b"\0", 1)[0].decode("utf-8")
                gname = header[297:329].split(b"\0", 1)[0].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HandoffError("archive_owner_encoding_invalid") from exc
            if require_canonical_header and header != _canonical_ustar_header(
                normalized,
                size=size,
                typeflag=typeflag,
                mode=mode,
                uid=uid,
                gid=gid,
                mtime=mtime,
                uname=uname,
                gname=gname,
            ):
                raise HandoffError("archive_header_not_canonical")
            if is_directory and size != 0:
                raise HandoffError("archive_directory_has_payload")
            if size > MAX_MEMBER_BYTES:
                raise HandoffError("archive_member_size_out_of_budget")
            declared_total += size
            if declared_total > max_archive_bytes:
                raise HandoffError("archive_declared_total_out_of_budget")
            data_offset = header_offset + 512
            padded = ((size + 511) // 512) * 512
            if data_offset + padded > archive_size:
                raise HandoffError("archive_member_truncated")
            members[normalized] = TarMember(
                normalized,
                data_offset,
                size,
                typeflag,
                mode,
                uid,
                gid,
                mtime,
                uname,
                gname,
            )
            casefolded[folded] = normalized
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise HandoffError("archive_member_count_out_of_budget")
            handle.seek(data_offset + size)
            padding = handle.read(padded - size)
            if any(padding):
                raise HandoffError("archive_nonzero_member_padding")
    if zero_blocks < 2:
        raise HandoffError("archive_end_marker_missing")
    return members


def read_member(path: Path, member: TarMember, *, max_bytes: int = MAX_JSON_BYTES) -> bytes:
    if member.size > max_bytes:
        raise HandoffError("archive_metadata_member_too_large")
    with path.open("rb") as handle:
        handle.seek(member.data_offset)
        data = handle.read(member.size)
    if len(data) != member.size:
        raise HandoffError("archive_member_truncated")
    return data


def hash_member(path: Path, member: TarMember) -> str:
    digest = hashlib.sha256()
    remaining = member.size
    with path.open("rb") as handle:
        handle.seek(member.data_offset)
        while remaining:
            block = handle.read(min(COPY_BLOCK_BYTES, remaining))
            if not block:
                raise HandoffError("archive_member_truncated")
            digest.update(block)
            remaining -= len(block)
    return "sha256:" + digest.hexdigest()


def validate_deterministic_member_metadata(member: TarMember, *, expected_mode: int) -> None:
    if (
        member.typeflag not in {b"", b"\0", b"0"}
        or member.mode != expected_mode
        or member.uid != 0
        or member.gid != 0
        or member.mtime != 0
        or member.uname != ""
        or member.gname != ""
    ):
        raise HandoffError("archive_member_metadata_not_deterministic")


def _descriptor(value: Mapping[str, object], *, allowed_media: set[str] | None = None) -> dict[str, object]:
    digest = value.get("digest")
    size = value.get("size")
    media_type = value.get("mediaType")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise HandoffError("oci_descriptor_digest_invalid")
    if not isinstance(size, int) or size < 0:
        raise HandoffError("oci_descriptor_size_invalid")
    if not isinstance(media_type, str) or not media_type:
        raise HandoffError("oci_descriptor_media_type_invalid")
    if allowed_media is not None and media_type not in allowed_media:
        raise HandoffError("oci_descriptor_media_type_unexpected")
    return {"media_type": media_type, "digest": digest, "size": size}


def _descriptor_blob_member(
    archive: Path,
    members: Mapping[str, TarMember],
    descriptor: Mapping[str, object],
) -> TarMember:
    digest = str(descriptor["digest"])
    name = "blobs/sha256/" + digest.removeprefix("sha256:")
    member = members.get(name)
    if member is None or member.name.endswith("/"):
        raise HandoffError("oci_descriptor_blob_missing")
    if member.size != descriptor["size"]:
        raise HandoffError("oci_descriptor_size_mismatch")
    if hash_member(archive, member) != digest:
        raise HandoffError("oci_descriptor_digest_mismatch")
    return member


def _json_member(archive: Path, member: TarMember) -> dict[str, object]:
    try:
        value = json.loads(read_member(archive, member))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("oci_json_invalid") from exc
    if not isinstance(value, dict):
        raise HandoffError("oci_json_not_object")
    return value


def parse_oci_archive(
    archive: Path,
    *,
    require_canonical_header: bool = True,
) -> ImageChain:
    members = scan_tar_headers(
        archive,
        allow_directories=True,
        require_canonical_header=require_canonical_header,
    )
    index_member = members.get("index.json")
    layout_member = members.get("oci-layout")
    if index_member is None or layout_member is None:
        raise HandoffError("oci_layout_missing")
    layout = _json_member(archive, layout_member)
    if layout != {"imageLayoutVersion": "1.0.0"}:
        raise HandoffError("oci_layout_version_invalid")
    index = _json_member(archive, index_member)
    top_descriptors = index.get("manifests")
    if not isinstance(top_descriptors, list) or len(top_descriptors) != 1:
        raise HandoffError("oci_top_descriptor_count_invalid")
    top_raw = top_descriptors[0]
    if not isinstance(top_raw, dict):
        raise HandoffError("oci_top_descriptor_invalid")
    top = _descriptor(top_raw, allowed_media=INDEX_MEDIA_TYPES | MANIFEST_MEDIA_TYPES)
    top_member = _descriptor_blob_member(archive, members, top)
    if top["media_type"] in INDEX_MEDIA_TYPES:
        nested = _json_member(archive, top_member)
        candidates = []
        for raw in nested.get("manifests", []):
            if not isinstance(raw, dict):
                continue
            platform = raw.get("platform")
            if platform == TARGET_PLATFORM:
                candidates.append(raw)
        if len(candidates) != 1:
            raise HandoffError("oci_linux_amd64_manifest_not_unique")
        manifest_descriptor = _descriptor(candidates[0], allowed_media=MANIFEST_MEDIA_TYPES)
    else:
        manifest_descriptor = top
    manifest_member = _descriptor_blob_member(archive, members, manifest_descriptor)
    manifest_json = _json_member(archive, manifest_member)
    if manifest_json.get("mediaType") not in MANIFEST_MEDIA_TYPES:
        raise HandoffError("oci_manifest_media_type_invalid")
    config_raw = manifest_json.get("config")
    layers_raw = manifest_json.get("layers")
    if not isinstance(config_raw, dict) or not isinstance(layers_raw, list) or not layers_raw:
        raise HandoffError("oci_manifest_descriptors_invalid")
    config_descriptor = _descriptor(config_raw, allowed_media=CONFIG_MEDIA_TYPES)
    config_member = _descriptor_blob_member(archive, members, config_descriptor)
    config_json = _json_member(archive, config_member)
    if config_json.get("os") != "linux" or config_json.get("architecture") != "amd64":
        raise HandoffError("oci_config_platform_invalid")
    layers: list[dict[str, object]] = []
    for raw in layers_raw:
        if not isinstance(raw, dict):
            raise HandoffError("oci_layer_descriptor_invalid")
        layer = _descriptor(raw)
        if not any(str(layer["media_type"]).startswith(prefix) for prefix in LAYER_MEDIA_PREFIXES):
            raise HandoffError("oci_layer_media_type_invalid")
        _descriptor_blob_member(archive, members, layer)
        layers.append(layer)
    return ImageChain(
        root=top,
        manifest=manifest_descriptor,
        config=config_descriptor,
        layers=tuple(layers),
        members=members,
    )


def _run(arguments: Sequence[str], *, timeout: int, capture_bytes: bool = False) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            list(arguments),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=not capture_bytes,
            encoding=None if capture_bytes else "utf-8",
            errors=None if capture_bytes else "replace",
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandoffError("subprocess_unavailable_or_timed_out") from exc


def _registry_raw(reference: str) -> bytes:
    completed = _run(
        ["docker", "buildx", "imagetools", "inspect", reference, "--raw"],
        timeout=180,
        capture_bytes=True,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise HandoffError("registry_metadata_fetch_failed")
    return bytes(completed.stdout)


def capture_vendor_metadata(spec: Mapping[str, str]) -> ImageChain:
    index_raw = _registry_raw(spec["source_reference"])
    try:
        index_json = json.loads(index_raw)
    except json.JSONDecodeError as exc:
        raise HandoffError("registry_index_invalid") from exc
    if not isinstance(index_json, dict) or index_json.get("mediaType") not in INDEX_MEDIA_TYPES:
        raise HandoffError("registry_index_required")
    candidates = []
    for raw in index_json.get("manifests", []):
        if isinstance(raw, dict) and raw.get("platform") == TARGET_PLATFORM:
            candidates.append(raw)
    if len(candidates) != 1:
        raise HandoffError("registry_linux_amd64_manifest_not_unique")
    manifest_descriptor = _descriptor(candidates[0], allowed_media=MANIFEST_MEDIA_TYPES)
    manifest_raw = _registry_raw(
        f"{spec['pull_repository']}@{manifest_descriptor['digest']}"
    )
    if len(manifest_raw) != manifest_descriptor["size"]:
        raise HandoffError("registry_manifest_size_mismatch")
    if _sha256_bytes(manifest_raw) != manifest_descriptor["digest"]:
        raise HandoffError("registry_manifest_digest_mismatch")
    try:
        manifest_json = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise HandoffError("registry_manifest_invalid") from exc
    config_raw = manifest_json.get("config")
    layers_raw = manifest_json.get("layers")
    if not isinstance(config_raw, dict) or not isinstance(layers_raw, list) or not layers_raw:
        raise HandoffError("registry_manifest_descriptors_invalid")
    config_descriptor = _descriptor(config_raw, allowed_media=CONFIG_MEDIA_TYPES)
    layers = tuple(_descriptor(raw) for raw in layers_raw if isinstance(raw, dict))
    if len(layers) != len(layers_raw):
        raise HandoffError("registry_layer_descriptor_invalid")
    for layer in layers:
        if not any(str(layer["media_type"]).startswith(prefix) for prefix in LAYER_MEDIA_PREFIXES):
            raise HandoffError("registry_layer_media_type_invalid")
    return ImageChain(
        root={
            "media_type": str(index_json["mediaType"]),
            "digest": _sha256_bytes(index_raw),
            "size": len(index_raw),
        },
        manifest=manifest_descriptor,
        config=config_descriptor,
        layers=layers,
        members={},
    )


def _docker_save(reference: str, output: Path) -> None:
    completed = _run(
        ["docker", "image", "save", "--output", str(output), reference],
        timeout=900,
    )
    if completed.returncode != 0:
        raise HandoffError("docker_image_save_failed")


def _compare_chains(expected: ImageChain, actual: ImageChain, *, compare_index: bool) -> None:
    if compare_index and expected.root != actual.root:
        raise HandoffError("oci_index_descriptor_mismatch")
    if expected.manifest != actual.manifest:
        raise HandoffError("oci_manifest_descriptor_mismatch")
    if expected.config != actual.config:
        raise HandoffError("oci_config_descriptor_mismatch")
    if expected.layers != actual.layers:
        raise HandoffError("oci_layer_descriptors_mismatch")


def _tar_info(name: str, size: int, *, mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.type = tarfile.REGTYPE
    return info


def _add_bytes(target: tarfile.TarFile, name: str, data: bytes, *, mode: int = 0o644) -> None:
    target.addfile(_tar_info(name, len(data), mode=mode), io.BytesIO(data))


def _add_slice(
    target: tarfile.TarFile,
    name: str,
    source_archive: Path,
    member: TarMember,
) -> None:
    reader = SliceReader(source_archive, member.data_offset, member.size)
    try:
        target.addfile(_tar_info(name, member.size), reader)
    finally:
        reader.close()


def write_single_platform_oci_archive(
    source_archive: Path,
    chain: ImageChain,
    output: Path,
    *,
    import_repository: str,
    import_tag: str = "l3-locked",
) -> None:
    manifest_digest = str(chain.manifest["digest"])
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [
            {
                "mediaType": chain.manifest["media_type"],
                "digest": manifest_digest,
                "size": chain.manifest["size"],
                "platform": TARGET_PLATFORM,
                "annotations": {
                    "io.containerd.image.name": f"docker.io/{import_repository}:{import_tag}",
                    "org.opencontainers.image.ref.name": import_tag,
                },
            }
        ],
    }
    layout = {"imageLayoutVersion": "1.0.0"}
    descriptors = [chain.manifest, chain.config, *chain.layers]
    if chain.root["media_type"] in INDEX_MEDIA_TYPES:
        descriptors.insert(0, chain.root)
    names_and_members: list[tuple[str, TarMember]] = []
    seen_blob_names: set[str] = set()
    for descriptor in descriptors:
        digest = str(descriptor["digest"])
        name = "blobs/sha256/" + digest.removeprefix("sha256:")
        member = chain.members.get(name)
        if member is None:
            raise HandoffError("oci_source_blob_missing")
        if name in seen_blob_names:
            raise HandoffError("oci_source_descriptor_duplicate")
        seen_blob_names.add(name)
        names_and_members.append((name, member))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as target:
        for name, member in sorted(names_and_members):
            _add_slice(target, name, source_archive, member)
        _add_bytes(target, "index.json", canonical_json_bytes(index))
        _add_bytes(target, "oci-layout", canonical_json_bytes(layout))


def _slot_from_chain(
    spec: Mapping[str, str],
    chain: ImageChain,
    *,
    engine_observation: Mapping[str, str] | None = None,
) -> dict[str, object]:
    manifest_digest = str(chain.manifest["digest"])
    delivery_mode = "digest_pull" if spec["kind"] == "vendor" else "oci_archive"
    compose_repository = (
        spec["pull_repository"]
        if delivery_mode == "digest_pull"
        else spec["import_repository"]
    )
    slot = {
        "slot": spec["slot"],
        "role": spec["role"],
        "kind": spec["kind"],
        "registry": spec["registry"],
        "repository": spec["repository"],
        "source_tag": spec["source_tag"],
        "source_reference": spec["source_reference"],
        "import_repository": spec["import_repository"],
        "import_tag": "l3-locked",
        "delivery_mode": delivery_mode,
        "compose_reference": f"{compose_repository}@{manifest_digest}",
        "index": dict(chain.root),
        "manifest": dict(chain.manifest),
        "config": dict(chain.config),
        "layers": [dict(layer) for layer in chain.layers],
    }
    if spec["kind"] == "application":
        observation = dict(
            engine_observation
            or {
                "image_id": str(chain.root["digest"]),
                "descriptor_digest": str(chain.root["digest"]),
                "semantic": ENGINE_OBSERVATION_SEMANTIC,
            }
        )
        slot["engine_observation"] = observation
    elif engine_observation is not None:
        raise HandoffError("vendor_engine_observation_forbidden")
    return slot


def validate_image_lock(lock: Mapping[str, object]) -> None:
    expected_fields = {
        "schema_version",
        "captured_at",
        "target_platform",
        "freshness_policy",
        "slots",
    }
    if set(lock) != expected_fields:
        raise HandoffError("image_lock_fields_invalid")
    if lock.get("schema_version") != "l3-image-lock-v1":
        raise HandoffError("image_lock_schema_invalid")
    if lock.get("target_platform") != TARGET_PLATFORM:
        raise HandoffError("image_lock_platform_invalid")
    if lock.get("freshness_policy") != "source-tag-drift-is-recorded-separately-from-content-integrity":
        raise HandoffError("image_lock_freshness_policy_invalid")
    if not isinstance(lock.get("captured_at"), str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
        str(lock.get("captured_at")),
    ):
        raise HandoffError("image_lock_capture_time_invalid")
    slots = lock.get("slots")
    if not isinstance(slots, list) or len(slots) != len(SLOT_SPECS):
        raise HandoffError("image_lock_slot_count_invalid")
    seen: set[str] = set()
    seen_folded: set[str] = set()
    for spec, item in zip(SLOT_SPECS, slots, strict=True):
        expected_slot_fields = (
            SLOT_FIELDS | {"engine_observation"}
            if spec["kind"] == "application"
            else SLOT_FIELDS
        )
        if not isinstance(item, dict) or set(item) != expected_slot_fields:
            raise HandoffError("image_lock_slot_fields_invalid")
        identity_fields = (
            "slot",
            "role",
            "kind",
            "registry",
            "repository",
            "source_tag",
            "source_reference",
            "import_repository",
        )
        if any(item.get(field) != spec[field] for field in identity_fields):
            raise HandoffError("image_lock_slot_identity_invalid")
        if item.get("import_tag") != "l3-locked":
            raise HandoffError("image_lock_import_tag_invalid")
        expected_delivery = "digest_pull" if spec["kind"] == "vendor" else "oci_archive"
        if item.get("delivery_mode") != expected_delivery:
            raise HandoffError("image_lock_delivery_mode_invalid")
        if spec["kind"] == "application":
            observation = item.get("engine_observation")
            observed_index = item.get("index")
            if not isinstance(observation, dict) or set(observation) != ENGINE_OBSERVATION_FIELDS:
                raise HandoffError("image_lock_engine_observation_fields_invalid")
            if (
                not isinstance(observation.get("image_id"), str)
                or not DIGEST_RE.fullmatch(str(observation.get("image_id")))
                or not isinstance(observation.get("descriptor_digest"), str)
                or not DIGEST_RE.fullmatch(str(observation.get("descriptor_digest")))
                or not isinstance(observed_index, dict)
                or observation.get("descriptor_digest") != observed_index.get("digest")
                or observation.get("semantic") != ENGINE_OBSERVATION_SEMANTIC
            ):
                raise HandoffError("image_lock_engine_observation_invalid")
        slot = str(item["slot"])
        if slot in seen or slot.casefold() in seen_folded:
            raise HandoffError("image_lock_slot_duplicate")
        seen.add(slot)
        seen_folded.add(slot.casefold())
        index_descriptor = item.get("index")
        if not isinstance(index_descriptor, dict) or set(index_descriptor) != DESCRIPTOR_FIELDS:
            raise HandoffError("image_lock_index_descriptor_fields_invalid")
        converted_index = {
            "mediaType": index_descriptor["media_type"],
            "digest": index_descriptor["digest"],
            "size": index_descriptor["size"],
        }
        _descriptor(converted_index, allowed_media=INDEX_MEDIA_TYPES)
        manifest = item.get("manifest")
        config = item.get("config")
        layers = item.get("layers")
        for descriptor, allowed in (
            (manifest, MANIFEST_MEDIA_TYPES),
            (config, CONFIG_MEDIA_TYPES),
        ):
            if not isinstance(descriptor, dict) or set(descriptor) != DESCRIPTOR_FIELDS:
                raise HandoffError("image_lock_descriptor_fields_invalid")
            converted = {
                "mediaType": descriptor["media_type"],
                "digest": descriptor["digest"],
                "size": descriptor["size"],
            }
            _descriptor(converted, allowed_media=allowed)
        if not isinstance(layers, list) or not layers:
            raise HandoffError("image_lock_layers_invalid")
        layer_digests: set[str] = set()
        for layer in layers:
            if not isinstance(layer, dict) or set(layer) != DESCRIPTOR_FIELDS:
                raise HandoffError("image_lock_layer_fields_invalid")
            converted = {
                "mediaType": layer["media_type"],
                "digest": layer["digest"],
                "size": layer["size"],
            }
            parsed = _descriptor(converted)
            if not any(str(parsed["media_type"]).startswith(prefix) for prefix in LAYER_MEDIA_PREFIXES):
                raise HandoffError("image_lock_layer_media_type_invalid")
            if str(parsed["digest"]) in layer_digests:
                raise HandoffError("image_lock_layer_duplicate")
            layer_digests.add(str(parsed["digest"]))
        compose_repository = (
            spec["pull_repository"]
            if expected_delivery == "digest_pull"
            else spec["import_repository"]
        )
        expected_compose = f"{compose_repository}@{manifest['digest']}"
        if item.get("compose_reference") != expected_compose:
            raise HandoffError("image_lock_compose_reference_invalid")


def _generation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"l3-{stamp}-{uuid.uuid4().hex[:8]}"


def _captured_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _owned_generation_root(generation_id: str) -> Path:
    if not GENERATION_RE.fullmatch(generation_id):
        raise HandoffError("generation_id_invalid")
    root = (HANDOFF_ROOT / generation_id).resolve()
    try:
        root.relative_to(HANDOFF_ROOT.resolve())
    except ValueError as exc:
        raise HandoffError("generation_path_escape") from exc
    return root


def _create_generation(generation_id: str) -> tuple[Path, Path, Path]:
    root = _owned_generation_root(generation_id)
    if root.exists():
        raise HandoffError("generation_already_exists")
    work = root / "work"
    bundle = root / "bundle"
    work.mkdir(parents=True)
    bundle.mkdir()
    marker = root / ".tsing-radar-l3-generation"
    marker.write_text(generation_id + "\n", encoding="ascii")
    return root, work, bundle


def preflight_local_capacity() -> None:
    if shutil.disk_usage(ROOT).free < MIN_BUILD_FREE_BYTES:
        raise HandoffError("l3_build_disk_headroom_insufficient")
    total = 0
    for spec in SLOT_SPECS:
        if spec["kind"] != "application":
            continue
        inspected = _run(
            [
                "docker",
                "image",
                "inspect",
                spec["source_reference"],
                "--format",
                "{{.Size}}|{{.Os}}|{{.Architecture}}",
            ],
            timeout=30,
        )
        if inspected.returncode != 0:
            raise HandoffError("application_image_capacity_inspect_failed")
        parts = str(inspected.stdout).strip().split("|")
        if len(parts) != 3 or parts[1:] != ["linux", "amd64"]:
            raise HandoffError("application_image_capacity_platform_invalid")
        try:
            total += int(parts[0])
        except ValueError as exc:
            raise HandoffError("application_image_capacity_size_invalid") from exc
    if total <= 0 or total > MAX_APPLICATION_IMAGE_BYTES:
        raise HandoffError("application_image_bundle_budget_exceeded")


def _verify_owned_work_file(path: Path, generation_root: Path, generation_id: str) -> None:
    marker = generation_root / ".tsing-radar-l3-generation"
    try:
        path.resolve().relative_to((generation_root / "work").resolve())
    except ValueError as exc:
        raise HandoffError("work_cleanup_path_escape") from exc
    if marker.read_text(encoding="ascii").strip() != generation_id:
        raise HandoffError("generation_marker_invalid")


def capture_slot(
    spec: Mapping[str, str],
    *,
    source_archive: Path,
) -> tuple[ImageChain, dict[str, str]]:
    if spec["kind"] == "vendor":
        raise HandoffError("vendor_archive_capture_forbidden")
    before = _inspect_application_engine_observation(spec["source_reference"])
    _docker_save(spec["source_reference"], source_archive)
    actual = parse_oci_archive(source_archive, require_canonical_header=False)
    after = _inspect_application_engine_observation(spec["source_reference"])
    if after != before:
        raise HandoffError("application_image_changed_during_capture")
    if before["descriptor_digest"] != actual.root["digest"]:
        raise HandoffError("application_image_index_mismatch")
    return actual, before


def _inspect_application_engine_observation(reference: str) -> dict[str, str]:
    inspected = _run(
        ["docker", "image", "inspect", reference, "--format", "{{json .}}"],
        timeout=30,
    )
    if inspected.returncode != 0:
        raise HandoffError("application_image_inspect_failed")
    try:
        value = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise HandoffError("application_image_descriptor_invalid") from exc
    descriptor = value.get("Descriptor")
    image_id = value.get("Id")
    descriptor_digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    if value.get("Os") != "linux" or value.get("Architecture") != "amd64":
        raise HandoffError("application_image_platform_invalid")
    if (
        not isinstance(image_id, str)
        or not DIGEST_RE.fullmatch(image_id)
        or not isinstance(descriptor_digest, str)
        or not DIGEST_RE.fullmatch(descriptor_digest)
    ):
        raise HandoffError("application_image_descriptor_invalid")
    return {
        "image_id": image_id,
        "descriptor_digest": descriptor_digest,
        "semantic": ENGINE_OBSERVATION_SEMANTIC,
    }


def _load_l2_module():
    path = ROOT / "scripts" / "build_l2_release_manifest.py"
    spec = importlib.util.spec_from_file_location("tsing_radar_l2_manifest", path)
    if spec is None or spec.loader is None:
        raise HandoffError("l2_manifest_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_l2_manifest(
    captured_application_images: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    module = _load_l2_module()
    expected_pairs = [("backend", "tsing-radar-backend:l2-local"), ("frontend", "tsing-radar-frontend:l2-local")]
    if [
        (item.get("role"), item.get("local_reference"))
        for item in captured_application_images
    ] != expected_pairs:
        raise HandoffError("captured_application_identity_invalid")
    application_images = [dict(item) for item in captured_application_images]
    manifest = module.build_manifest(application_images=application_images)
    module.validate_manifest(manifest)
    L2_MANIFEST_OUTPUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _source_mode(relative: str) -> int:
    return 0o755 if relative.endswith(".sh") else 0o644


def write_source_archive(
    l2_manifest: Mapping[str, object],
    output: Path,
    *,
    root: Path = ROOT,
) -> None:
    entries = l2_manifest.get("source_files")
    if not isinstance(entries, list) or not entries:
        raise HandoffError("l2_source_entries_invalid")
    paths = [str(item.get("path", "")) for item in entries if isinstance(item, dict)]
    if len(paths) != len(entries) or paths != sorted(paths):
        raise HandoffError("l2_source_order_invalid")
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as target:
        for item in entries:
            relative = str(item["path"])
            path = root / Path(*PurePosixPath(relative).parts)
            if path.is_symlink() or not path.is_file():
                raise HandoffError("l2_source_file_invalid")
            size = path.stat().st_size
            if size != item["size"] or sha256_file(path) != item["sha256"]:
                raise HandoffError("l2_source_changed_during_archive")
            with path.open("rb") as handle:
                target.addfile(_tar_info(relative, size, mode=_source_mode(relative)), handle)


def _file_descriptor(path: Path, relative: str) -> dict[str, object]:
    size = path.stat().st_size
    if size <= 0:
        raise HandoffError("bundle_file_empty")
    return {"path": relative, "size": size, "sha256": sha256_file(path)}


def _write_compose_environment(lock: Mapping[str, object], output: Path) -> None:
    lines = [
        "# Generated L3 offline image references; contains no credentials.",
        "# Loading and using these images on a server remains a separately approved cloud gate.",
    ]
    for item in lock["slots"]:
        lines.append(f"{item['slot']}={item['compose_reference']}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def build_handoff(generation_id: str) -> Path:
    preflight_local_capacity()
    generation_root, work, bundle = _create_generation(generation_id)
    captured_at = _captured_at()
    image_slots: list[dict[str, object]] = []
    image_descriptors: list[dict[str, object]] = []
    captured_application_images: list[dict[str, str]] = []
    images_dir = bundle / "images"
    images_dir.mkdir()
    for spec in SLOT_SPECS:
        if spec["kind"] == "vendor":
            chain = capture_vendor_metadata(spec)
            image_slots.append(_slot_from_chain(spec, chain))
            continue
        safe_role = re.sub(r"[^a-z0-9-]", "-", spec["role"].lower())
        source_archive = work / f"{safe_role}.source.oci.tar"
        final_archive = images_dir / f"{safe_role}.oci.tar"
        chain, engine_observation = capture_slot(spec, source_archive=source_archive)
        write_single_platform_oci_archive(
            source_archive,
            chain,
            final_archive,
            import_repository=spec["import_repository"],
        )
        final_chain = parse_oci_archive(final_archive)
        if final_chain.root["digest"] != str(chain.manifest["digest"]):
            raise HandoffError("single_platform_archive_not_manifest_rooted")
        _compare_chains(chain, final_chain, compare_index=False)
        slot = _slot_from_chain(
            spec,
            chain,
            engine_observation=engine_observation,
        )
        image_slots.append(slot)
        captured_application_images.append(
            {
                "role": spec["role"],
                "local_reference": spec["source_reference"],
                "image_id": engine_observation["image_id"],
                "os": "linux",
                "architecture": "amd64",
            }
        )
        image_descriptors.append(
            {
                "slot": spec["slot"],
                **_file_descriptor(final_archive, f"images/{safe_role}.oci.tar"),
            }
        )
        _verify_owned_work_file(source_archive, generation_root, generation_id)
        source_archive.unlink()

    lock = {
        "schema_version": "l3-image-lock-v1",
        "captured_at": captured_at,
        "target_platform": TARGET_PLATFORM,
        "freshness_policy": "source-tag-drift-is-recorded-separately-from-content-integrity",
        "slots": image_slots,
    }
    validate_image_lock(lock)
    IMAGE_LOCK_OUTPUT.write_bytes(canonical_json_bytes(lock))
    lock_copy = bundle / "image-lock.json"
    lock_copy.write_bytes(canonical_json_bytes(lock))

    l2_manifest = build_l2_manifest(captured_application_images)
    l2_copy = bundle / "l2-release-manifest.json"
    l2_copy.write_bytes(canonical_json_bytes(l2_manifest))

    source_archive = bundle / "source.tar"
    source_repeat = work / "source.repeat.tar"
    write_source_archive(l2_manifest, source_archive)
    write_source_archive(l2_manifest, source_repeat)
    if sha256_file(source_archive) != sha256_file(source_repeat):
        raise HandoffError("source_archive_not_deterministic")
    _verify_owned_work_file(source_repeat, generation_root, generation_id)
    source_repeat.unlink()

    compose_environment = bundle / "compose-images.env"
    _write_compose_environment(lock, compose_environment)

    manifest = {
        "schema_version": "l3-handoff-manifest-v1",
        "generation_id": generation_id,
        "captured_at": captured_at,
        "target_platform": TARGET_PLATFORM,
        "image_lock": _file_descriptor(lock_copy, "image-lock.json"),
        "l2_release_manifest": _file_descriptor(l2_copy, "l2-release-manifest.json"),
        "compose_environment": _file_descriptor(compose_environment, "compose-images.env"),
        "source_archive": _file_descriptor(source_archive, "source.tar"),
        "image_archives": image_descriptors,
        "bundle_policy": {
            "fixed_regular_file_count": 8,
            "application_archive_count": 2,
            "vendor_archive_count": 0,
            "max_bundle_bytes": 2147483648,
        },
        "integrity_policy": {
            "manifest_hash": "detached-sha256-of-exact-bundle-manifest-bytes",
            "archive_validation": "validate-all-headers-and-descriptors-before-extract-or-load",
            "tag_freshness": "separate-non-integrity-gate",
        },
        "cloud_gates": list(CLOUD_GATES),
    }
    manifest_path = bundle / "bundle-manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    regular_files = [path for path in bundle.rglob("*") if path.is_file()]
    bundle_bytes = sum(path.stat().st_size for path in regular_files)
    if len(regular_files) != 7 or bundle_bytes > 2147483648:
        raise HandoffError("bundle_pre_manifest_budget_invalid")
    detached = bundle / "bundle-manifest.sha256"
    detached.write_text(
        f"{sha256_file(manifest_path).removeprefix('sha256:')}  bundle-manifest.json\n",
        encoding="ascii",
        newline="\n",
    )
    regular_files = [path for path in bundle.rglob("*") if path.is_file()]
    bundle_bytes = sum(path.stat().st_size for path in regular_files)
    if len(regular_files) != 8 or bundle_bytes > 2147483648:
        raise HandoffError("bundle_final_budget_invalid")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation-id", default=None)
    args = parser.parse_args()
    generation_id = args.generation_id or _generation_id()
    try:
        if not IMAGE_LOCK_SCHEMA.is_file() or not HANDOFF_SCHEMA.is_file():
            raise HandoffError("l3_schema_missing")
        bundle = build_handoff(generation_id)
        print(
            json.dumps(
                {
                    "schema_version": "l3-build-result-v1",
                    "status": "passed",
                    "generation_id": generation_id,
                    "bundle_relative_path": bundle.relative_to(ROOT).as_posix(),
                    "image_slot_count": len(SLOT_SPECS),
                    "target_platform": "linux/amd64",
                    "uploaded": False,
                    "ports_or_volumes_created": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
        reason = exc.args[0] if exc.args else "handoff_build_failed"
        print(
            json.dumps(
                {
                    "schema_version": "l3-build-result-v1",
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
