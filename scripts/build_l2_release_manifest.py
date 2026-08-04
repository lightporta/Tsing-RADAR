"""Build and verify a secret-free local L2 release-candidate manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deploy" / "production" / "release-manifest.local.json"
MAX_SOURCE_BYTES = 10 * 1024 * 1024
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")

BASE_IMAGES = (
    {
        "role": "backend",
        "tag": "python:3.11-slim",
        "index_digest": "sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93",
        "linux_amd64_manifest_digest": "sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045",
        "linux_amd64_config_digest": "sha256:1c03896dbf0ef4a2b86f1462395249e810c589e25d8c0b002faabc38aa144686",
    },
    {
        "role": "frontend_builder",
        "tag": "node:20-alpine",
        "index_digest": "sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293",
        "linux_amd64_manifest_digest": "sha256:afdf98210b07b586eb71fa22ba2e432e058e4cd1304d31ed60888755b8c865fb",
        "linux_amd64_config_digest": "sha256:11cedc39e663e7c5d5cb9cc77a461a0d2adc25537b94e6831a6108f09cb2001b",
    },
    {
        "role": "frontend_runtime",
        "tag": "nginx:alpine",
        "index_digest": "sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752",
        "linux_amd64_manifest_digest": "sha256:1d40e3eb3bf4f138de1d67193f2aa5309fcaf343eb5ffadbf5e9439de1eb1ebb",
        "linux_amd64_config_digest": "sha256:f0ba77f796e57c6fa89ae7f4fdad1665d6fcbd8e3f211535120542b337f9959e",
    },
)

APPLICATION_IMAGES = {
    "backend": "tsing-radar-backend:l2-local",
    "frontend": "tsing-radar-frontend:l2-local",
}

ALLOWED_ROOTS = (
    "backend/app",
    "backend/alembic",
    "backend/scripts",
    "backend/tests",
    "frontend/src",
    "frontend/public",
    "frontend/tests",
    "deploy/production",
)

ALLOWED_FILES = (
    ".gitignore",
    "backend/.dockerignore",
    "backend/Dockerfile",
    "backend/alembic.ini",
    "backend/requirements.txt",
    "frontend/.dockerignore",
    "frontend/Dockerfile",
    "frontend/eslint.config.js",
    "frontend/index.html",
    "frontend/nginx.conf",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/pnpm-lock.yaml",
    "frontend/pnpm-workspace.yaml",
    "frontend/tsconfig.json",
    "frontend/tsconfig.node.json",
    "frontend/vite.config.ts",
    "scripts/check_l1_production.py",
    "scripts/check_l1_containers.py",
    "scripts/check_l2_release.py",
    "scripts/build_l2_release_manifest.py",
    "scripts/check_l3_handoff.py",
)

SKIP_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".vite",
    "__pycache__",
    "backups",
    "dist",
    "htmlcov",
    "node_modules",
    "private_uploads",
    "secrets",
}

SKIP_EXACT_FILES = {
    "deploy/production/release-manifest.local.json",
    "deploy/production/image-lock.local.json",
}

PROHIBITED_EXACT = {
    "backend/data/mentors.evidence.json",
}

PROHIBITED_PREFIXES = (
    ".pytest-",
    "backend/data/private_local/",
    "backend/private_uploads/",
    "legacy/",
)

PROHIBITED_SUFFIXES = (
    ".key",
    ".p12",
    ".pem",
    ".pfx",
)

COMPOSE_IMAGE_SLOTS = (
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
)

CLOUD_GATES = (
    "cloud_pull_and_inspect_linux_amd64",
    "compose_vendor_and_application_image_digests",
    "real_secret_bind_uid_mode",
    "real_cos_clamav_database_dns_tls",
)

MANIFEST_FIELDS = {
    "schema_version",
    "target_platform",
    "base_images",
    "application_images",
    "source_files",
    "compose_image_slots",
    "cloud_gates",
}
APPLICATION_IMAGE_FIELDS = {
    "role",
    "local_reference",
    "image_id",
    "os",
    "architecture",
}
SOURCE_FILE_FIELDS = {"path", "size", "sha256"}


class ReleaseManifestError(RuntimeError):
    pass


def normalize_relative_path(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ReleaseManifestError("path_not_relative")
    parsed = PurePosixPath(raw)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ReleaseManifestError("path_not_normalized")
    normalized = parsed.as_posix()
    if normalized != raw.rstrip("/"):
        raise ReleaseManifestError("path_not_canonical")
    return normalized


def _is_prohibited(path: str) -> bool:
    lowered = path.casefold()
    if lowered in {item.casefold() for item in PROHIBITED_EXACT}:
        return True
    if any(lowered.startswith(prefix.casefold()) for prefix in PROHIBITED_PREFIXES):
        return True
    if any(lowered.endswith(suffix) for suffix in PROHIBITED_SUFFIXES):
        return True
    parts = PurePosixPath(lowered).parts
    if "secrets" in parts or "private_uploads" in parts:
        return True
    name = parts[-1]
    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        return True
    return False


def _validate_candidate(root: Path, relative: str) -> Path:
    normalized = normalize_relative_path(relative)
    if _is_prohibited(normalized):
        raise ReleaseManifestError("prohibited_release_candidate")
    path = root / Path(*PurePosixPath(normalized).parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseManifestError("candidate_missing") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ReleaseManifestError("candidate_symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ReleaseManifestError("candidate_not_regular_file")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ReleaseManifestError("candidate_escapes_root") from exc
    if metadata.st_size > MAX_SOURCE_BYTES:
        raise ReleaseManifestError("candidate_too_large")
    return path


def _walk_allowed_root(root: Path, relative_root: str) -> Iterable[str]:
    normalized_root = normalize_relative_path(relative_root)
    start = root / Path(*PurePosixPath(normalized_root).parts)
    if not start.exists():
        return
    if start.is_symlink():
        raise ReleaseManifestError("allowed_root_symlink")
    for current, directory_names, file_names in os.walk(start, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in directory_names:
            child = current_path / name
            relative = child.relative_to(root).as_posix()
            if name in SKIP_DIRECTORY_NAMES or name.startswith(".pytest-"):
                continue
            if child.is_symlink():
                raise ReleaseManifestError("candidate_directory_symlink")
            if _is_prohibited(relative.rstrip("/") + "/"):
                continue
            retained.append(name)
        directory_names[:] = retained
        for name in file_names:
            relative = (current_path / name).relative_to(root).as_posix()
            if relative in SKIP_EXACT_FILES:
                continue
            yield relative


def collect_source_paths(
    root: Path = ROOT,
    *,
    extra_candidates: Iterable[str] = (),
) -> list[str]:
    candidates: list[str] = []
    for relative_root in ALLOWED_ROOTS:
        candidates.extend(_walk_allowed_root(root, relative_root))
    for relative in ALLOWED_FILES:
        path = root / Path(*PurePosixPath(relative).parts)
        if path.exists():
            candidates.append(relative)
    candidates.extend(extra_candidates)

    normalized: list[str] = []
    for candidate in candidates:
        relative = normalize_relative_path(candidate)
        _validate_candidate(root, relative)
        normalized.append(relative)
    ensure_unique_normalized_paths(normalized)
    return sorted(normalized)


def ensure_unique_normalized_paths(paths: Iterable[str]) -> None:
    seen: set[str] = set()
    seen_casefold: dict[str, str] = {}
    for value in paths:
        relative = normalize_relative_path(value)
        folded = relative.casefold()
        if relative in seen:
            raise ReleaseManifestError("duplicate_candidate")
        if folded in seen_casefold and seen_casefold[folded] != relative:
            raise ReleaseManifestError("candidate_case_collision")
        seen.add(relative)
        seen_casefold[folded] = relative


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def source_entries(root: Path, paths: Iterable[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for relative in paths:
        path = _validate_candidate(root, relative)
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return entries


def _dockerfile_from_references(path: Path) -> list[str]:
    references: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = re.match(r"^FROM\s+([^\s]+)", line.strip(), re.IGNORECASE)
        if matched:
            references.append(matched.group(1))
    return references


def validate_dockerfile_pins(root: Path = ROOT) -> None:
    expected_backend = [
        f"{BASE_IMAGES[0]['tag']}@{BASE_IMAGES[0]['linux_amd64_manifest_digest']}"
    ]
    expected_frontend = [
        f"{BASE_IMAGES[1]['tag']}@{BASE_IMAGES[1]['linux_amd64_manifest_digest']}",
        f"{BASE_IMAGES[2]['tag']}@{BASE_IMAGES[2]['linux_amd64_manifest_digest']}",
    ]
    if _dockerfile_from_references(root / "backend" / "Dockerfile") != expected_backend:
        raise ReleaseManifestError("backend_base_image_not_linux_amd64_pinned")
    if _dockerfile_from_references(root / "frontend" / "Dockerfile") != expected_frontend:
        raise ReleaseManifestError("frontend_base_images_not_linux_amd64_pinned")


def _inspect_application_images(
    runner: callable = subprocess.run,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for role, reference in APPLICATION_IMAGES.items():
        completed = runner(
            [
                "docker",
                "image",
                "inspect",
                reference,
                "--format",
                "{{json .}}",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            shell=False,
        )
        if completed.returncode != 0:
            raise ReleaseManifestError("application_image_missing")
        try:
            inspected = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ReleaseManifestError("application_image_inspect_invalid") from exc
        image_id = inspected.get("Id")
        os_name = inspected.get("Os")
        architecture = inspected.get("Architecture")
        if not isinstance(image_id, str) or not DIGEST_PATTERN.fullmatch(image_id):
            raise ReleaseManifestError("application_image_id_invalid")
        if os_name != "linux" or architecture != "amd64":
            raise ReleaseManifestError("application_image_platform_invalid")
        entries.append(
            {
                "role": role,
                "local_reference": reference,
                "image_id": image_id,
                "os": os_name,
                "architecture": architecture,
            }
        )
    return entries


def build_manifest(
    root: Path = ROOT,
    *,
    application_images: list[dict[str, str]] | None = None,
    extra_candidates: Iterable[str] = (),
) -> dict[str, object]:
    validate_dockerfile_pins(root)
    paths = collect_source_paths(root, extra_candidates=extra_candidates)
    return {
        "schema_version": "l2-release-manifest-v1",
        "target_platform": {"os": "linux", "architecture": "amd64"},
        "base_images": [dict(item) for item in BASE_IMAGES],
        "application_images": (
            application_images if application_images is not None else _inspect_application_images()
        ),
        "source_files": source_entries(root, paths),
        "compose_image_slots": [
            {"name": name, "cloud_resolution_required": True}
            for name in COMPOSE_IMAGE_SLOTS
        ],
        "cloud_gates": [
            *CLOUD_GATES,
        ],
    }


def _validate_schema_contract(root: Path = ROOT) -> None:
    schema_path = root / "deploy" / "production" / "release-manifest.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError("manifest_schema_file_invalid") from exc
    properties = schema.get("properties")
    if (
        schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or set(schema.get("required", [])) != MANIFEST_FIELDS
        or not isinstance(properties, dict)
        or set(properties) != MANIFEST_FIELDS
    ):
        raise ReleaseManifestError("manifest_schema_contract_invalid")
    application_schema = schema.get("$defs", {}).get("applicationImage", {})
    application_properties = application_schema.get("properties", {})
    if (
        application_schema.get("additionalProperties") is not False
        or set(application_schema.get("required", [])) != APPLICATION_IMAGE_FIELDS
        or set(application_properties) != APPLICATION_IMAGE_FIELDS
        or set(application_properties.get("role", {}).get("enum", []))
        != set(APPLICATION_IMAGES)
        or set(application_properties.get("local_reference", {}).get("enum", []))
        != set(APPLICATION_IMAGES.values())
    ):
        raise ReleaseManifestError("manifest_schema_application_images_invalid")
    slot_schema = properties.get("compose_image_slots", {})
    slot_names = (
        slot_schema.get("items", {})
        .get("properties", {})
        .get("name", {})
        .get("enum", [])
    )
    if (
        slot_schema.get("minItems") != len(COMPOSE_IMAGE_SLOTS)
        or slot_schema.get("maxItems") != len(COMPOSE_IMAGE_SLOTS)
        or set(slot_names) != set(COMPOSE_IMAGE_SLOTS)
    ):
        raise ReleaseManifestError("manifest_schema_compose_slots_invalid")
    gate_schema = properties.get("cloud_gates", {})
    if (
        gate_schema.get("minItems") != len(CLOUD_GATES)
        or gate_schema.get("maxItems") != len(CLOUD_GATES)
        or gate_schema.get("uniqueItems") is not True
        or set(gate_schema.get("items", {}).get("enum", [])) != set(CLOUD_GATES)
    ):
        raise ReleaseManifestError("manifest_schema_cloud_gates_invalid")


def validate_manifest_contract(
    manifest: Mapping[str, object],
    root: Path = ROOT,
) -> None:
    """Validate the portable L2 contract without Docker or source extraction.

    The source bytes and local engine observations are deliberately verified by
    the caller that owns those resources.  This layer still rejects any
    structural downgrade, unknown field, unsafe path, or non-canonical source
    entry before an archive is extracted.
    """
    _validate_schema_contract(root)
    if set(manifest) != MANIFEST_FIELDS:
        raise ReleaseManifestError("manifest_fields_invalid")
    if manifest.get("schema_version") != "l2-release-manifest-v1":
        raise ReleaseManifestError("manifest_schema_version_invalid")
    if manifest.get("target_platform") != {"os": "linux", "architecture": "amd64"}:
        raise ReleaseManifestError("manifest_platform_invalid")
    if manifest.get("base_images") != [dict(item) for item in BASE_IMAGES]:
        raise ReleaseManifestError("manifest_base_image_relation_invalid")
    application_images = manifest.get("application_images")
    if not isinstance(application_images, list) or len(application_images) != 2:
        raise ReleaseManifestError("manifest_application_images_invalid")
    expected_application_pairs = list(APPLICATION_IMAGES.items())
    for index, item in enumerate(application_images):
        if not isinstance(item, dict) or set(item) != APPLICATION_IMAGE_FIELDS:
            raise ReleaseManifestError("manifest_application_image_invalid")
        expected_role, expected_reference = expected_application_pairs[index]
        if (
            item.get("role") != expected_role
            or item.get("local_reference") != expected_reference
        ):
            raise ReleaseManifestError("manifest_application_image_identity_invalid")
        if item.get("os") != "linux" or item.get("architecture") != "amd64":
            raise ReleaseManifestError("manifest_application_image_platform_invalid")
        if not isinstance(item.get("image_id"), str) or not DIGEST_PATTERN.fullmatch(
            str(item.get("image_id"))
        ):
            raise ReleaseManifestError("manifest_application_image_digest_invalid")
    expected_slots = [
        {"name": name, "cloud_resolution_required": True}
        for name in COMPOSE_IMAGE_SLOTS
    ]
    if manifest.get("compose_image_slots") != expected_slots:
        raise ReleaseManifestError("manifest_compose_image_slots_invalid")
    if manifest.get("cloud_gates") != list(CLOUD_GATES):
        raise ReleaseManifestError("manifest_cloud_gates_invalid")

    source_files = manifest.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise ReleaseManifestError("manifest_source_files_invalid")
    paths: list[str] = []
    folded_paths: set[str] = set()
    for item in source_files:
        if not isinstance(item, dict) or set(item) != SOURCE_FILE_FIELDS:
            raise ReleaseManifestError("manifest_source_entry_invalid")
        relative = normalize_relative_path(str(item.get("path", "")))
        if _is_prohibited(relative):
            raise ReleaseManifestError("manifest_contains_prohibited_path")
        folded = relative.casefold()
        if relative in paths or folded in folded_paths:
            raise ReleaseManifestError("manifest_source_path_duplicate")
        size = item.get("size")
        digest = item.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_SOURCE_BYTES:
            raise ReleaseManifestError("manifest_source_size_invalid")
        if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
            raise ReleaseManifestError("manifest_source_digest_invalid")
        paths.append(relative)
        folded_paths.add(folded)
    if paths != sorted(paths):
        raise ReleaseManifestError("manifest_source_order_invalid")


def validate_manifest(
    manifest: Mapping[str, object],
    root: Path = ROOT,
    *,
    verify_local_images: bool = True,
) -> None:
    validate_manifest_contract(manifest, root)
    application_images = manifest["application_images"]
    if verify_local_images and application_images != _inspect_application_images():
        raise ReleaseManifestError("manifest_application_image_inspect_mismatch")
    paths = [str(item["path"]) for item in manifest["source_files"]]
    if paths != collect_source_paths(root):
        raise ReleaseManifestError("manifest_source_set_mismatch")
    if manifest["source_files"] != source_entries(root, paths):
        raise ReleaseManifestError("manifest_source_integrity_failed")


def _write_manifest(manifest: Mapping[str, object], output: Path = OUTPUT) -> None:
    if output != OUTPUT:
        raise ReleaseManifestError("manifest_output_not_fixed")
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_only:
            manifest = json.loads(OUTPUT.read_text(encoding="utf-8"))
        else:
            manifest = build_manifest()
            _write_manifest(manifest)
        validate_manifest(manifest)
        print(
            json.dumps(
                {
                    "schema_version": "l2-release-manifest-result-v1",
                    "status": "passed",
                    "target_platform": "linux/amd64",
                    "source_file_count": len(manifest["source_files"]),
                    "values_or_host_metadata_emitted": False,
                    "output_tracked": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ReleaseManifestError, json.JSONDecodeError) as exc:
        reason = exc.args[0] if exc.args else "manifest_failed"
        print(
            json.dumps(
                {
                    "schema_version": "l2-release-manifest-result-v1",
                    "status": "failed",
                    "reason": str(reason),
                    "values_or_host_metadata_emitted": False,
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
