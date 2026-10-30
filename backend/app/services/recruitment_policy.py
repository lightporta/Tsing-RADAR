"""Shared publication and time-window rules for recruitment reads and actions."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models.recruitment import Recruitment

PROJECT_TIMEZONE = ZoneInfo("Asia/Shanghai")


def recruitment_window_open(
    deadline: date | str | None,
    expires_at: datetime | str | None = None,
    *,
    as_of: datetime | None = None,
) -> bool:
    """Dates include their Shanghai calendar day; timestamps expire exactly.

    A published record without either bound remains open until withdrawn.
    Invalid bounds fail closed. SQLite drops timezone information, so application
    timestamps are stored in UTC and naive values are interpreted as UTC.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        if isinstance(deadline, str):
            deadline = date.fromisoformat(deadline)
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if deadline is not None and now.astimezone(PROJECT_TIMEZONE).date() > deadline:
            return False
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                return False
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def active_published_recruitments(
    db: Session,
    *,
    as_of: datetime | None = None,
) -> list[Recruitment]:
    """Only this shared selection can enter a public list or a new application."""
    now = as_of or datetime.now(timezone.utc)
    records = (
        db.query(Recruitment)
        .filter(
            Recruitment.review_status == "verified",
            Recruitment.publication_status == "published",
            Recruitment.takedown_at.is_(None),
        )
        .all()
    )
    return [
        record
        for record in records
        if recruitment_is_current(record, as_of=now)
    ]


def recruitment_lock_statement(recruit_id: str) -> Select:
    """Target one primary key and hold its publication state until commit."""
    return (
        select(Recruitment)
        .where(Recruitment.recruit_id == recruit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_recruitment(db: Session, recruit_id: str) -> Recruitment | None:
    """Call after the document lock; SQLite already holds BEGIN IMMEDIATE.

    PostgreSQL waits for and refreshes the target row. The caller must evaluate
    its time window after this wait, using the current time, in this transaction.
    """
    return db.execute(recruitment_lock_statement(recruit_id)).scalar_one_or_none()


def recruitment_is_current(
    record: Recruitment,
    *,
    as_of: datetime | None = None,
) -> bool:
    return (
        record.review_status == "verified"
        and record.publication_status == "published"
        and record.takedown_at is None
        and recruitment_window_open(record.deadline, record.expires_at, as_of=as_of)
    )
