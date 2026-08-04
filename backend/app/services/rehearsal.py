"""Synthetic, local-only competition rehearsal for A7."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.services.evaluation import run_synthetic_contract_evaluation
from app.services.observability import metrics_snapshot


def _step(
    steps: list[dict[str, Any]],
    step_id: str,
    passed: bool,
    *,
    evidence: dict[str, Any] | None = None,
) -> None:
    steps.append(
        {
            "id": step_id,
            "status": "passed" if passed else "failed",
            "evidence": evidence or {},
        }
    )


def _qxd_headers(
    *,
    platform_key: str,
    claim: str,
    claim_secret: str,
) -> dict[str, str]:
    signature = hmac.new(
        claim_secret.encode("utf-8"),
        claim.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Authorization": f"Bearer {platform_key}",
        "X-QXD-End-User-Id": claim,
        "X-QXD-End-User-Signature": signature,
    }


def run_local_competition_rehearsal(
    client,
    *,
    qxd_platform_key: str,
    qxd_claim_secret: str,
) -> dict[str, Any]:
    """Exercise the two product surfaces with synthetic values only.

    The caller must provide an isolated local database/object root. This
    function never calls an external service and never submits an application.
    """
    steps: list[dict[str, Any]] = []

    live = client.get("/health/live")
    ready = client.get("/health/ready")
    _step(
        steps,
        "local_health",
        live.status_code == 200
        and live.json().get("external_dependencies_probed") is False
        and ready.status_code == 200
        and ready.json().get("scope") == "local_dependencies_only",
        evidence={
            "liveness": live.json().get("status"),
            "readiness": ready.json().get("status"),
            "external_dependencies_probed": False,
        },
    )

    synthetic_claim = "a7-synthetic-qxd-user"
    qxd_headers = _qxd_headers(
        platform_key=qxd_platform_key,
        claim=synthetic_claim,
        claim_secret=qxd_claim_secret,
    )
    qxd_turns = [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "愿意探索高风险新方向",
        "无",
        "确认画像",
    ]
    invalid_claim_headers = dict(qxd_headers)
    invalid_claim_headers["X-QXD-End-User-Signature"] = "0" * 64
    invalid_claim = client.post(
        "/v1/chat/completions",
        headers=invalid_claim_headers,
        json={
            "model": "tsing-radar",
            "user": "a7-synthetic-conversation",
            "messages": [{"role": "user", "content": qxd_turns[0]}],
            "stream": False,
        },
    )

    transcript: list[dict[str, str]] = []
    qxd_statuses: list[int] = []
    qxd_replies: list[str] = []
    final_sse_contract = False
    for round_index, user_turn in enumerate(qxd_turns):
        transcript.append({"role": "user", "content": user_turn})
        use_stream = round_index == len(qxd_turns) - 1
        qxd_round = client.post(
            "/v1/chat/completions",
            headers=qxd_headers,
            json={
                "model": "tsing-radar",
                "user": "a7-synthetic-conversation",
                "messages": transcript,
                "stream": use_stream,
            },
        )
        qxd_statuses.append(qxd_round.status_code)
        if use_stream and qxd_round.status_code == 200:
            data_lines = [
                line.removeprefix("data:").strip()
                for line in qxd_round.text.splitlines()
                if line.startswith("data:")
            ]
            frames = [
                json.loads(line)
                for line in data_lines[:-1]
                if line != "[DONE]"
            ]
            assistant_reply = "".join(
                frame["choices"][0]["delta"].get("content", "")
                for frame in frames
            )
            final_sse_contract = (
                bool(data_lines)
                and data_lines[-1] == "[DONE]"
                and bool(frames)
                and frames[-1]["choices"][0]["finish_reason"] == "stop"
                and frames[-1].get("usage")
                == {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
            )
        else:
            assistant_reply = (
                qxd_round.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                if qxd_round.status_code == 200
                else ""
            )
        qxd_replies.append(assistant_reply)
        transcript.append({"role": "assistant", "content": assistant_reply})

    preconfirmation_replies = qxd_replies[:-1]
    preconfirmation_safe = all(
        "暂无通过审核的数据" not in reply and "推荐你" not in reply
        for reply in preconfirmation_replies
    )
    state_progressed = len(set(preconfirmation_replies)) >= 5
    _step(
        steps,
        "qxd_preconfirmation_state",
        invalid_claim.status_code in {401, 403}
        and all(status == 200 for status in qxd_statuses[:-1])
        and preconfirmation_safe
        and state_progressed,
        evidence={
            "invalid_claim_rejected": invalid_claim.status_code in {401, 403},
            "completed_rounds_before_confirmation": len(
                preconfirmation_replies
            ),
            "distinct_assistant_states": len(set(preconfirmation_replies)),
            "recommendation_before_confirmation": not preconfirmation_safe,
        },
    )
    qxd_content = qxd_replies[-1] if qxd_replies else ""
    _step(
        steps,
        "qxd_interview_confirm_match",
        len(qxd_statuses) == len(qxd_turns)
        and all(status == 200 for status in qxd_statuses)
        and final_sse_contract
        and "暂无通过审核的数据" in qxd_content
        and "推荐你" not in qxd_content,
        evidence={
            "sequential_http_rounds": len(qxd_statuses),
            "all_rounds_authenticated": all(
                status == 200 for status in qxd_statuses
            ),
            "assistant_messages_carried_forward": (
                sum(
                    1
                    for message in transcript
                    if message["role"] == "assistant"
                )
                == len(qxd_turns)
            ),
            "final_sse_contract": final_sse_contract,
            "honest_empty_result": "暂无通过审核的数据" in qxd_content,
            "sse_used": True,
            "attachments_created": False,
        },
    )

    web_session = client.get("/api/session")
    csrf = client.cookies.get("tsing_radar_csrf")
    web_headers = {"X-CSRF-Token": csrf or ""}
    interview = client.post(
        "/api/interviews",
        headers=web_headers,
        json={"initial_answer": "自然语言处理、对话系统"},
    )
    state = interview.json() if interview.status_code == 200 else {}
    answers = {
        "research_mode": "工程落地",
        "mentorship_style": "高频具体指导",
        "career_orientation": "产业就业",
        "innovation_risk": "愿意探索高风险新方向",
        "hard_constraints": "无",
    }
    for _ in range(8):
        if state.get("status") != "in_progress":
            break
        question = state.get("current_question") or {}
        answer = answers.get(question.get("dimension"))
        if answer is None:
            break
        interview = client.post(
            f"/api/interviews/{state['session_id']}/answers",
            headers=web_headers,
            json={"answer": answer},
        )
        state = interview.json() if interview.status_code == 200 else {}

    confirm = client.post(
        f"/api/interviews/{state.get('session_id', '')}/confirm",
        headers=web_headers,
        json={"expected_version": state.get("profile_version", 0)},
    )
    confirmed = confirm.json() if confirm.status_code == 200 else {}
    matched = client.post(
        "/api/match",
        headers=web_headers,
        json={"session_id": confirmed.get("session_id")},
    )
    match_payload = matched.json() if matched.status_code == 200 else {}
    _step(
        steps,
        "web_interview_confirm_match",
        web_session.status_code == 200
        and confirm.status_code == 200
        and confirmed.get("status") == "confirmed"
        and matched.status_code == 200
        and match_payload.get("status") == "no_published_data"
        and match_payload.get("data") == [],
        evidence={
            "session_status": web_session.status_code,
            "profile_status": confirmed.get("status"),
            "match_status": match_payload.get("status"),
            "result_count": len(match_payload.get("data") or []),
        },
    )

    resume = client.post(
        "/api/resume/generate",
        headers={
            **web_headers,
            "Idempotency-Key": "a7-rehearsal-resume-0001",
        },
        json={
            "student_name": "合成参赛者",
            "dept": "合成院系",
            "email": "",
            "phone": "",
            "education": "合成教育经历，仅用于本地合同彩排",
            "research_interests": ["自然语言处理"],
            "projects": [
                {
                    "name": "合成项目",
                    "detail": "无真实个人信息、无外部投递",
                }
            ],
            "awards": [],
            "positions": [],
            "target_advisor": None,
            "format": "pdf",
            "confirm_generation": True,
        },
    )
    resume_payload = resume.json() if resume.status_code == 200 else {}
    grant = client.post(
        f"/api/artifacts/{resume_payload.get('document_id', '')}/download-grant",
        headers={
            **web_headers,
            "Idempotency-Key": "a7-rehearsal-grant-0001",
        },
        json={"confirm_private_download": True},
    )
    grant_payload = grant.json() if grant.status_code == 200 else {}
    download_url = grant_payload.get("download_url", "")
    downloaded = (
        client.post(download_url, headers=web_headers)
        if isinstance(download_url, str) and download_url.startswith("/")
        else None
    )
    downloaded_sha = (
        hashlib.sha256(downloaded.content).hexdigest()
        if downloaded is not None and downloaded.status_code == 200
        else None
    )
    _step(
        steps,
        "web_private_artifact_download",
        resume.status_code == 200
        and grant.status_code == 200
        and downloaded is not None
        and downloaded.status_code == 200
        and downloaded.content.startswith(b"%PDF")
        and downloaded_sha == resume_payload.get("sha256"),
        evidence={
            "generation_status": resume.status_code,
            "grant_status": grant.status_code,
            "download_status": (
                downloaded.status_code if downloaded is not None else None
            ),
            "magic": "PDF"
            if downloaded is not None
            and downloaded.content.startswith(b"%PDF")
            else "invalid",
            "hash_verified": downloaded_sha == resume_payload.get("sha256"),
            "public_url_created": False,
            "application_submitted": False,
        },
    )

    evaluation = run_synthetic_contract_evaluation()
    _step(
        steps,
        "synthetic_contract_evaluation",
        evaluation["summary"]["status"] == "passed",
        evidence=evaluation["summary"],
    )

    passed = sum(1 for item in steps if item["status"] == "passed")
    return {
        "schema_version": "a7-local-rehearsal-v1",
        "classification": "synthetic_local_only",
        "status": "passed" if passed == len(steps) else "failed",
        "summary": {
            "total": len(steps),
            "passed": passed,
            "failed": len(steps) - passed,
        },
        "steps": steps,
        "safety": {
            "network_requests_performed": False,
            "real_credentials_used": False,
            "public_urls_created": False,
            "external_applications_submitted": False,
            "real_user_data_used": False,
        },
        "observability": metrics_snapshot(),
        "claim_limit": (
            "This rehearsal validates local contracts and failure states only; "
            "it is not production or recommendation-accuracy evidence."
        ),
    }


def compact_rehearsal_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
