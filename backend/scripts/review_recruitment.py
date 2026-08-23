"""Review user-submitted recruitments from inside the backend container."""

from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.models.recruitment import Recruitment
from app.services.recruitment_review import (
    RecruitmentReviewError,
    review_recruitment,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Internal recruitment review")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List restricted/pending submissions")
    for action in ("approve", "reject"):
        command = subparsers.add_parser(action)
        command.add_argument("recruit_id")
        command.add_argument("--reviewer", required=True)
        command.add_argument("--reason", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    with SessionLocal() as db:
        if args.command == "list":
            records = (
                db.query(Recruitment)
                .filter(Recruitment.publication_status != "published")
                .order_by(Recruitment.created_at.asc())
                .all()
            )
            print(
                json.dumps(
                    [
                        {
                            "recruit_id": item.recruit_id,
                            "title": item.title,
                            "review_status": item.review_status,
                            "publication_status": item.publication_status,
                            "created_at": item.created_at.isoformat()
                            if item.created_at else None,
                        }
                        for item in records
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        try:
            record = review_recruitment(
                db,
                recruit_id=args.recruit_id,
                action=args.command,
                reviewer=args.reviewer,
                reason=args.reason,
            )
        except RecruitmentReviewError as exc:
            print(json.dumps({"status": "error", "detail": str(exc)}))
            return 2
        print(
            json.dumps(
                {
                    "status": "ok",
                    "recruit_id": record.recruit_id,
                    "review_status": record.review_status,
                    "publication_status": record.publication_status,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
