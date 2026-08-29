"""导师意向中心：匹配聚合、投递列表与反馈汇总（学生侧匿名化断言）。"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.models.advisor import Advisor
from app.models.application import Application
from app.models.feedback import Feedback
from app.models.match_record import MatchRecord
from app.models.recruitment import Recruitment
from app.models.student import Student
from tests.mentor_helpers import (
    auto_claim,
    mentor_dataset,
    mentor_login,
    mentor_web_client,
)

EMAIL = "mentor01@tsinghua.edu.cn"


def _seed_advisor(advisor_id: str = "A001") -> None:
    with SessionLocal() as db:
        if db.get(Advisor, advisor_id) is None:
            db.add(
                Advisor(
                    advisor_id=advisor_id,
                    name="张伟",
                    department="计算机科学与技术系",
                )
            )
            db.commit()


def test_matches_aggregate_without_student_identity(mentor_dataset, caplog):
    _seed_advisor()
    with SessionLocal() as db:
        db.add(
            Student(
                student_id="st-anon-1",
                email="student@example.com",
                department="计算机科学与技术系",
            )
        )
        db.commit()
        db.add_all(
            [
                MatchRecord(
                    student_id="st-anon-1",
                    advisor_id="A001",
                    synergy_score=0.91,
                    match_reason="研究方向匹配",
                ),
                MatchRecord(
                    student_id="st-anon-1",
                    advisor_id="A001",
                    synergy_score=0.73,
                    match_reason="项目经历吻合",
                ),
            ]
        )
        db.commit()

    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)
    try:
        response = client.get("/api/mentor/inbound/matches", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["recent"]) == 2
        serialized = str(body)
        assert "st-anon-1" not in serialized
        assert "student@example.com" not in serialized
        assert all("student_id" not in item for item in body["recent"])
    finally:
        with SessionLocal() as db:
            db.query(MatchRecord).delete(synchronize_session=False)
            db.query(Student).delete(synchronize_session=False)
            db.commit()


def test_feedback_summary_counts_without_comment_leak(mentor_dataset, caplog):
    _seed_advisor()
    with SessionLocal() as db:
        db.add_all(
            [
                Feedback(
                    student_id="st-anon-1",
                    advisor_id="A001",
                    rating=1,
                    comment="私密评论不应下发",
                ),
                Feedback(
                    student_id="st-anon-2",
                    advisor_id="A001",
                    rating=1,
                    comment="另一位学生评价",
                ),
                Feedback(
                    student_id="st-anon-3",
                    advisor_id="A001",
                    rating=-1,
                    comment="负面评价原文",
                ),
            ]
        )
        db.commit()
        try:
            client, headers = mentor_web_client()
            mentor_login(client, headers, caplog, email=EMAIL)
            auto_claim(client, headers)
            response = client.get("/api/mentor/inbound/feedback", headers=headers)
            assert response.status_code == 200
            body = response.json()
            assert body["positive"] == 2
            assert body["negative"] == 1
            assert body["total"] == 3
            serialized = str(body)
            assert "私密评论不应下发" not in serialized
            assert "st-anon-1" not in serialized
        finally:
            with SessionLocal() as db:
                db.query(Feedback).delete(synchronize_session=False)
                db.commit()


def test_applications_are_anonymized(mentor_dataset, caplog):
    client, headers = mentor_web_client()
    mentor_login(client, headers, caplog, email=EMAIL)
    auto_claim(client, headers)

    with SessionLocal() as db:
        from app.models.mentor_account import MentorAccount
        from app.models.private_document import PrivateDocument

        account = (
            db.query(MentorAccount).filter(MentorAccount.email == EMAIL).one()
        )
        subject_id = account.subject_id
        db.add(
            Recruitment(
                publisher_id=subject_id,
                publisher_type="advisor",
                type="科研助理",
                title="NLP 方向科研助理",
                req="熟悉深度学习",
                major="计算机",
                review_status="verified",
                publication_status="published",
            )
        )
        db.commit()
        recruitment = (
            db.query(Recruitment)
            .filter(Recruitment.publisher_id == subject_id)
            .one()
        )
        db.add(
            PrivateDocument(
                document_id="doc-anon-9",
                owner_subject_id="st-anon-9",
                original_name="resume.docx",
                stored_name="objects/resume.docx",
                extension=".docx",
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                size_bytes=1024,
                sha256="a" * 64,
                status="ready",
                document_kind="upload",
                object_backend="local",
                scan_status="clean",
            )
        )
        db.commit()
        db.add(
            Application(
                recruit_id=recruitment.recruit_id,
                student_id="st-anon-9",
                resume_id="doc-anon-9",
                status="submitted_in_app",
            )
        )
        db.commit()

    response = client.get("/api/mentor/inbound/applications", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["data"][0]
    assert item["status"] == "submitted_in_app"
    assert item["resume"]["present"] is True
    assert item["resume"]["extension"] == ".docx"
    serialized = str(body)
    assert "st-anon-9" not in serialized
    assert "doc-anon-9" not in serialized
    assert "student@example.com" not in serialized
    assert "resume.docx" not in serialized
