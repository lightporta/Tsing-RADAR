"""Recruitment listing and application use the same current publication window."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1.recruitment import list_recruitments
from app.db.session import SessionLocal
from app.models.application import Application
from app.models.private_document import PrivateDocument
from app.models.recruitment import Recruitment
from app.services import applications
from app.services.applications import _published_recruitment_ids, create_in_app_application
from app.services.document_locking import lock_private_document
from app.services.recruitment_policy import recruitment_lock_statement, recruitment_window_open


def _published(**overrides):
    values = {
        "recruit_id": str(uuid4()),
        "publisher_id": "policy-test",
        "review_status": "verified",
        "publication_status": "published",
        "title": "合成招募",
        "deadline": None,
        "expires_at": None,
    }
    values.update(overrides)
    return Recruitment(**values)


def _ready_document():
    identifier = str(uuid4())
    return PrivateDocument(
        document_id=identifier,
        owner_subject_id="policy-test",
        original_name="synthetic.pdf",
        stored_name=f"synthetic-{identifier}",
        extension=".pdf",
        media_type="application/pdf",
        size_bytes=1,
        sha256="0" * 64,
        status="ready",
        scan_status="clean",
    )


def test_deadline_includes_shanghai_calendar_day_and_timestamp_is_exclusive():
    deadline = date(2026, 10, 30)
    before_end = datetime(2026, 10, 30, 15, 59, 59, tzinfo=timezone.utc)
    after_end = datetime(2026, 10, 30, 16, 0, 0, tzinfo=timezone.utc)
    assert recruitment_window_open(deadline, as_of=before_end)
    assert not recruitment_window_open(deadline, as_of=after_end)
    assert not recruitment_window_open(None, before_end, as_of=before_end)
    # SQLite's naive UTC timestamp has the same expiry semantics.
    assert not recruitment_window_open(None, before_end.replace(tzinfo=None), as_of=before_end)
    assert recruitment_window_open(None, None, as_of=after_end)
    assert not recruitment_window_open("not-a-date", as_of=after_end)


def test_expired_recruitments_are_absent_from_list_and_application_selection():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        expired_date = _published(deadline=date(2020, 1, 1))
        expired_timestamp = _published(expires_at=now - timedelta(seconds=1))
        active = _published(deadline=date(2099, 1, 1), expires_at=now + timedelta(days=1))
        indefinite = _published()
        withdrawn = _published(takedown_at=now)
        restricted = _published(publication_status="restricted")
        records = [expired_date, expired_timestamp, active, indefinite, withdrawn, restricted]
        db.add_all(records)
        document = _ready_document()
        db.add(document)
        db.commit()
        ids = {item.recruit_id for item in records}

        public_ids = {item["recruit_id"] for item in list_recruitments(db=db)["data"]}
        allowed_ids = _published_recruitment_ids(db)
        expected = {active.recruit_id, indefinite.recruit_id}
        assert public_ids & ids == expected
        assert allowed_ids & ids == expected

        with pytest.raises(HTTPException) as error:
            create_in_app_application(
                db,
                subject_id="policy-test",
                recruit_id=expired_date.recruit_id,
                document_id=document.document_id,
                confirmed=True,
                idempotency_key=f"expired-{uuid4()}",
            )
        assert error.value.status_code == 409
        assert "过期" in error.value.detail


@pytest.mark.parametrize("change", ["expiry", "takedown"])
def test_application_rechecks_recruitment_after_waiting_for_document_lock(monkeypatch, change):
    with SessionLocal() as db:
        recruitment = _published(expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        document = _ready_document()
        db.add_all([recruitment, document])
        db.commit()
        recruit_id, document_id = recruitment.recruit_id, document.document_id

    def changed_while_waiting(db, target_id):
        # A controlled concurrent change at the same boundary as a real lock
        # wait. SQLite's document helper then restarts and locks the transaction.
        with SessionLocal() as other:
            record = other.get(Recruitment, recruit_id)
            if change == "expiry":
                record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            else:
                record.takedown_at = datetime.now(timezone.utc)
            other.commit()
        return lock_private_document(db, target_id)

    monkeypatch.setattr(applications, "lock_private_document", changed_while_waiting)
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            create_in_app_application(
                db,
                subject_id="policy-test",
                recruit_id=recruit_id,
                document_id=document_id,
                confirmed=True,
                idempotency_key=f"wait-{uuid4()}",
            )
        assert error.value.status_code == 409
        assert db.query(Application).filter(Application.recruit_id == recruit_id).count() == 0


def test_target_recruitment_lock_uses_postgres_row_lock_and_primary_key():
    statement = recruitment_lock_statement("target-id")
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "WHERE recruitments.recruit_id =" in str(compiled)
    assert "FOR UPDATE" in str(compiled)
    assert list(compiled.params.values()) == ["target-id"]


def test_file_backed_current_recruitment_can_still_accept_an_application(monkeypatch):
    recruit_id = f"static-{uuid4()}"
    monkeypatch.setattr(
        applications,
        "load_mentors",
        lambda: [{"recruitments": [{"recruit_id": recruit_id, "deadline": "2099-01-01"}]}],
    )
    with SessionLocal() as db:
        document = _ready_document()
        db.add(document)
        db.commit()
        result = create_in_app_application(
            db,
            subject_id="policy-test",
            recruit_id=recruit_id,
            document_id=document.document_id,
            confirmed=True,
            idempotency_key=f"static-{uuid4()}",
        )
        assert result.status == "submitted_in_app"
