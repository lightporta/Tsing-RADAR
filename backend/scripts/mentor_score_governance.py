#!/usr/bin/env python3
"""Offline collect → review → publish → expire workflow for score evidence.

The CLI accepts structured claims only.  It has no argument for student text or
personal identifiers and writes atomically to a versioned JSON release file.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.schemas.mentor_scores import (
    ClaimReviewStatus,
    MentorScoreDataset,
    MentorScoreRelease,
    ScoreDimension,
    ScoreEvidenceClaim,
    ScoreReleaseStatus,
)


def aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone")
    return parsed


def load(path: Path) -> MentorScoreDataset:
    if not path.exists():
        return MentorScoreDataset(
            generated_at=datetime.now(timezone.utc),
            releases=[],
        )
    return MentorScoreDataset.model_validate_json(path.read_bytes())


def save(path: Path, dataset: MentorScoreDataset) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dataset.model_dump_json(exclude_none=True).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def draft_release(dataset: MentorScoreDataset, version: int) -> MentorScoreRelease:
    release = next((item for item in dataset.releases if item.version == version), None)
    if release is None:
        release = MentorScoreRelease(
            version=version,
            created_at=datetime.now(timezone.utc),
        )
        dataset.releases.append(release)
    if release.status != ScoreReleaseStatus.DRAFT:
        raise ValueError("claims can only be changed in a draft release")
    return release


def collect(args: argparse.Namespace, dataset: MentorScoreDataset) -> None:
    release = draft_release(dataset, args.version)
    claim = ScoreEvidenceClaim(
        advisor_id=args.advisor_id,
        dimension=args.dimension,
        value=json.loads(args.value_json),
        source_kind=args.source_kind,
        source_url=args.source_url,
        extracted_at=args.extracted_at,
        valid_until=args.valid_until,
        method=args.method,
        method_version=args.method_version,
        sample_size=args.sample_size,
        privacy_threshold=args.privacy_threshold,
    )
    if any(
        item.advisor_id == claim.advisor_id and item.dimension == claim.dimension
        for item in release.claims
    ):
        raise ValueError("advisor/dimension already exists in this release")
    release.claims.append(claim)
    print(json.dumps({"claim_id": str(claim.claim_id), "status": "pending"}))


def review(args: argparse.Namespace, dataset: MentorScoreDataset) -> None:
    claim_id = UUID(args.claim_id)
    for release in dataset.releases:
        if release.status != ScoreReleaseStatus.DRAFT:
            continue
        for claim in release.claims:
            if claim.claim_id == claim_id:
                claim.review_status = ClaimReviewStatus(args.decision)
                claim.reviewer_id = args.reviewer_id
                claim.reviewed_at = datetime.now(timezone.utc)
                claim.review_note = args.note
                ScoreEvidenceClaim.model_validate(claim.model_dump())
                print(json.dumps({"claim_id": args.claim_id, "status": args.decision}))
                return
    raise ValueError("claim not found in a draft release")


def publish(args: argparse.Namespace, dataset: MentorScoreDataset) -> None:
    release = draft_release(dataset, args.version)
    now = datetime.now(timezone.utc)
    if not release.claims:
        raise ValueError("empty release cannot be published")
    if any(claim.review_status != ClaimReviewStatus.APPROVED for claim in release.claims):
        raise ValueError("every dimension claim must be approved before publish")
    if any(claim.valid_until <= now for claim in release.claims):
        raise ValueError("expired claim cannot be published")
    previous = max(
        (
            item
            for item in dataset.releases
            if item.status == ScoreReleaseStatus.PUBLISHED
        ),
        key=lambda item: item.version,
        default=None,
    )
    if previous is not None:
        previous.status = ScoreReleaseStatus.SUPERSEDED
        release.supersedes_release_id = previous.release_id
    release.status = ScoreReleaseStatus.PUBLISHED
    release.published_at = now
    MentorScoreRelease.model_validate(release.model_dump())
    print(json.dumps({"version": release.version, "status": "published"}))


def expire(dataset: MentorScoreDataset) -> None:
    now = datetime.now(timezone.utc)
    expired = 0
    for release in dataset.releases:
        release_expired = False
        for claim in release.claims:
            if claim.valid_until <= now and claim.review_status == ClaimReviewStatus.APPROVED:
                claim.review_status = ClaimReviewStatus.EXPIRED
                expired += 1
                release_expired = True
        if release_expired and release.status == ScoreReleaseStatus.PUBLISHED:
            release.status = ScoreReleaseStatus.WITHDRAWN
    print(json.dumps({"expired_claims": expired}))


def show_status(dataset: MentorScoreDataset) -> None:
    print(
        json.dumps(
            {
                "schema_version": dataset.schema_version,
                "releases": [
                    {
                        "version": item.version,
                        "status": item.status.value,
                        "claims": len(item.claims),
                        "approved": sum(
                            claim.review_status == ClaimReviewStatus.APPROVED
                            for claim in item.claims
                        ),
                    }
                    for item in sorted(dataset.releases, key=lambda row: row.version)
                ],
            },
            ensure_ascii=False,
        )
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--file", type=Path, required=True)
    commands = root.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser("collect")
    collect_parser.add_argument("--version", type=int, required=True)
    collect_parser.add_argument("--advisor-id", required=True)
    collect_parser.add_argument("--dimension", type=ScoreDimension, required=True)
    collect_parser.add_argument("--value-json", required=True)
    collect_parser.add_argument(
        "--source-kind",
        choices=("official_public", "authorized_aggregate"),
        required=True,
    )
    collect_parser.add_argument("--source-url", required=True)
    collect_parser.add_argument("--extracted-at", type=aware_datetime, required=True)
    collect_parser.add_argument("--valid-until", type=aware_datetime, required=True)
    collect_parser.add_argument("--method", required=True)
    collect_parser.add_argument("--method-version", required=True)
    collect_parser.add_argument("--sample-size", type=int)
    collect_parser.add_argument("--privacy-threshold", type=int)
    review_parser = commands.add_parser("review")
    review_parser.add_argument("--claim-id", required=True)
    review_parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    review_parser.add_argument("--reviewer-id", required=True)
    review_parser.add_argument("--note")
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--version", type=int, required=True)
    commands.add_parser("expire")
    commands.add_parser("status")
    return root


def main() -> int:
    args = parser().parse_args()
    dataset = load(args.file)
    if args.command == "collect":
        collect(args, dataset)
    elif args.command == "review":
        review(args, dataset)
    elif args.command == "publish":
        publish(args, dataset)
    elif args.command == "expire":
        expire(dataset)
    else:
        show_status(dataset)
        return 0
    dataset.generated_at = datetime.now(timezone.utc)
    validated = MentorScoreDataset.model_validate(dataset.model_dump())
    save(args.file, validated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
