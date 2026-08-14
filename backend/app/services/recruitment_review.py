"""Internal-only recruitment review operations.

These functions are intentionally not mounted on a public API route.  The
operator CLI runs inside the backend container with database access and writes
an audit entry into the record governance JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.recruitment import Recruitment


class RecruitmentReviewError(ValueError):
    pass


def review_recruitment(
    db: Session,
    *,
    recruit_id: str,
    action: str,
    reviewer: str,
    reason: str,
) -> Recruitment:
    if action not in {"approve", "reject"}:
        raise RecruitmentReviewError("action must be approve or reject")
    if not reviewer.strip() or not reason.strip():
        raise RecruitmentReviewError("reviewer and reason are required")
    record = db.get(Recruitment, recruit_id)
    if record is None:
        raise RecruitmentReviewError("recruitment not found")

    now = datetime.now(timezone.utc)
    if action == "approve" and record.deadline and record.deadline < now.date():
        raise RecruitmentReviewError("expired recruitment cannot be approved")
    governance = dict(record.governance or {})
    history = list(governance.get("review_history") or [])
    history.append(
        {
            "action": action,
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "reviewed_at": now.isoformat(),
        }
    )
    governance.update(
        {
            "review_status": "verified" if action == "approve" else "rejected",
            "publication_status": "published" if action == "approve" else "restricted",
            "updated_at": now.isoformat(),
            "review_history": history,
        }
    )

    if action == "approve":
        record.review_status = "verified"
        record.publication_status = "published"
        record.verified_at = now
        record.authorization_basis = "publisher_submission_reviewed"
    else:
        record.review_status = "rejected"
        record.publication_status = "restricted"
    record.governance = governance
    record.updated_at = now
    db.commit()
    db.refresh(record)
    return record
