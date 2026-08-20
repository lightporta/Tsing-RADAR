"""清小搭 OpenAI-compatible 协议合同测试。"""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import threading
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import chat as qxd_chat
from app.main import app
from app.db.session import SessionLocal
from app.models.questionnaire_session import QuestionnaireSession
from app.models.identity import ExternalIdentity
from app.schemas.qxd import SodaAttachment
from app.services.artifact_delivery import issue_radar_chart_token
from app.services.match_application import MatchApplicationOutcome
from app.services import match_refine as match_refine_service
from app.services.qxd_media import FetchedMedia
from app.services.radar_chart import ADVISOR_TRAIT_COLOR, RadarSeries

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"
TRIAL_HEADERS = {
    **AUTH,
    "X-Tsing-Radar-QXD1-Trial": "qxd1-single-user-trial",
}


def _qxd_headers(claim: str) -> dict[str, str]:
    signature = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        claim.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        **AUTH,
        "X-QXD-End-User-Id": claim,
        "X-QXD-End-User-Signature": signature,
    }


def _qxd_session_id(claim: str, conversation: str) -> str:
    fingerprint = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        f"identity-map:{claim}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with SessionLocal() as db:
        mapping = (
            db.query(ExternalIdentity)
            .filter(ExternalIdentity.claim_fingerprint == fingerprint)
            .one()
        )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tsing-radar:qxd-interview:{mapping.subject_id}:{conversation}",
        )
    )


def test_models_requires_valid_bearer():
    missing = client.get("/v1/models")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    invalid = client.get(
        "/v1/models", headers={"Authorization": "Bearer wrong-key"}
    )
    assert invalid.status_code == 401

    valid = client.get("/v1/models", headers=AUTH)
    assert valid.status_code == 200
    assert valid.json() == {
        "object": "list",
        "data": [
            {
                "id": "tsing-radar",
                "object": "model",
                "owned_by": "tsing-radar",
            }
        ],
    }


def test_missing_server_credential_fails_closed(monkeypatch):
    monkeypatch.setattr(qxd_chat.settings, "QXD_API_KEY", None)
    response = client.get(
        "/v1/models", headers={"Authorization": "Bearer any-key"}
    )
    assert response.status_code == 503


def test_single_user_trial_mode_is_default_off():
    assert qxd_chat.settings.QXD_TRIAL_SINGLE_USER_MODE is False


def test_trial_mode_requires_debug_and_qxd1_gateway_marker(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)

    missing_marker = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"messages": [{"role": "user", "content": "你好"}]},
    )
    assert missing_marker.status_code == 503

    monkeypatch.setattr(qxd_chat.settings, "DEBUG", False)
    production = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "你好"}]},
    )
    assert production.status_code == 503
    qxd_chat._reset_trial_state_for_tests()


def test_trial_single_turn_requests_progress(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)

    first = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={
            "messages": [
                {"role": "user", "content": "自然语言处理、对话系统"}
            ]
        },
    )
    assert first.status_code == 200
    assert "工程与落地" in first.json()["choices"][0]["message"]["content"]

    second_payload = {
        "messages": [{"role": "user", "content": "工程落地"}]
    }
    second = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json=second_payload,
    )
    assert second.status_code == 200
    second_content = second.json()["choices"][0]["message"]["content"]
    assert "高频具体指导" in second_content

    third = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "高频具体指导"}]},
    )
    assert third.status_code == 200
    assert "未来三到五年" in third.json()["choices"][0]["message"]["content"]
    qxd_chat._reset_trial_state_for_tests()


def test_trial_identical_confirm_answers_advance_two_constraints(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)
    clock = {"now": 100.0}
    monkeypatch.setattr(qxd_chat.time, "monotonic", lambda: clock["now"])

    turns = [
        "自然语言处理",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
        "只能北京、每周至少3天",
    ]
    response = None
    for content in turns:
        response = client.post(
            "/v1/chat/completions",
            headers=TRIAL_HEADERS,
            json={"messages": [{"role": "user", "content": content}]},
        )
    assert response is not None
    assert "地点必须在“北京”" in response.json()["choices"][0]["message"]["content"]

    first_confirm = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "确认"}]},
    )
    assert "每周至少投入 3 天" in first_confirm.json()["choices"][0]["message"]["content"]
    # 模拟 5 秒内对下一条不同约束再次合法回答同样的“确认”。
    clock["now"] = 101.0
    second_confirm = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "确认"}]},
    )
    assert second_confirm.status_code == 200
    content = second_confirm.json()["choices"][0]["message"]["content"]
    assert "已确认硬性条件" in content
    assert "地点必须属于北京" in content
    assert "每周投入天数至少3" in content
    assert qxd_chat._trial_state.consumed_turns == 8
    qxd_chat._reset_trial_state_for_tests()


def test_trial_probe_empty_payload_and_explicit_reset_do_not_consume_answers(
    monkeypatch,
):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)

    invalid = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": []},
    )
    assert invalid.status_code == 422
    assert qxd_chat._trial_state is None

    probe = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={
            "messages": [{"role": "user", "content": "probe"}],
            "stream": True,
            "max_tokens": 1,
        },
    )
    assert probe.status_code == 200
    assert qxd_chat._trial_state is None

    initial = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "自然语言处理"}]},
    )
    assert initial.status_code == 200
    old_session_id = qxd_chat._trial_state.session_id

    reset = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "重新开始"}]},
    )
    assert reset.status_code == 200
    assert "研究主题" in reset.json()["choices"][0]["message"]["content"]
    assert qxd_chat._trial_state.session_id != old_session_id
    assert qxd_chat._trial_state.consumed_turns == 0
    qxd_chat._reset_trial_state_for_tests()


def test_trial_idle_and_absolute_ttl_rotate_random_scope(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_IDLE_TTL_SECONDS", 100)
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_ABSOLUTE_TTL_SECONDS", 250)
    clock = {"now": 0.0}
    monkeypatch.setattr(qxd_chat.time, "monotonic", lambda: clock["now"])

    def send(content: str):
        return client.post(
            "/v1/chat/completions",
            headers=TRIAL_HEADERS,
            json={"messages": [{"role": "user", "content": content}]},
        )

    assert send("自然语言处理").status_code == 200
    first_id = qxd_chat._trial_state.session_id
    clock["now"] = 80
    assert send("工程落地").status_code == 200
    assert qxd_chat._trial_state.session_id == first_id
    clock["now"] = 260
    assert send("新的研究问题").status_code == 200
    absolute_rotated_id = qxd_chat._trial_state.session_id
    assert absolute_rotated_id != first_id
    clock["now"] = 361
    assert send("另一个问题").status_code == 200
    assert qxd_chat._trial_state.session_id != absolute_rotated_id
    qxd_chat._reset_trial_state_for_tests()


def test_trial_concurrent_requests_fail_closed(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)
    entered = threading.Event()
    release = threading.Event()
    original_sync = qxd_chat.sync_user_transcript

    def blocked_sync(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_sync(*args, **kwargs)

    monkeypatch.setattr(qxd_chat, "sync_user_transcript", blocked_sync)
    first_result: dict[str, object] = {}

    def first_request() -> None:
        first_result["response"] = client.post(
            "/v1/chat/completions",
            headers=TRIAL_HEADERS,
            json={"messages": [{"role": "user", "content": "自然语言处理"}]},
        )

    worker = threading.Thread(target=first_request)
    worker.start()
    assert entered.wait(timeout=5)
    conflict = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "高频具体指导"}]},
    )
    assert conflict.status_code == 409
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert first_result["response"].status_code == 200
    assert qxd_chat._trial_state.consumed_turns == 1
    qxd_chat._reset_trial_state_for_tests()


def test_signed_qxd_identity_bypasses_trial_singleton(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)
    claim = f"signed-trial-bypass-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "user": "signed-conversation",
            "messages": [
                {"role": "user", "content": "自然语言处理"},
                {"role": "user", "content": "工程落地"},
            ],
        },
    )
    assert response.status_code == 200
    assert "高频具体指导" in response.json()["choices"][0]["message"]["content"]
    assert qxd_chat._trial_state is None


def test_trial_internal_reset_requires_admin_and_exposes_no_state(monkeypatch):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)
    created = client.post(
        "/v1/chat/completions",
        headers=TRIAL_HEADERS,
        json={"messages": [{"role": "user", "content": "自然语言处理"}]},
    )
    assert created.status_code == 200
    assert qxd_chat._trial_state is not None

    denied = client.post(
        "/v1/internal/trial-reset",
        headers={"X-Admin-Token": "wrong"},
    )
    assert denied.status_code == 403
    assert qxd_chat._trial_state is not None

    reset = client.post(
        "/v1/internal/trial-reset",
        headers={"X-Admin-Token": "test-admin-token-not-for-production"},
    )
    assert reset.status_code == 200
    assert reset.json() == {"status": "reset"}
    assert qxd_chat._trial_state is None


def test_qxd_metadata_log_excludes_user_value_message_and_session(monkeypatch, caplog):
    qxd_chat._reset_trial_state_for_tests()
    monkeypatch.setattr(qxd_chat.settings, "QXD_TRIAL_SINGLE_USER_MODE", True)
    monkeypatch.setattr(qxd_chat.settings, "DEBUG", True)
    raw_user = "private-platform-user-value"
    raw_message = "private-message-body"
    with caplog.at_level(logging.INFO, logger="tsing_radar.qxd"):
        response = client.post(
            "/v1/chat/completions",
            headers=TRIAL_HEADERS,
            json={
                "user": raw_user,
                "messages": [{"role": "user", "content": raw_message}],
            },
        )
    assert response.status_code == 200
    serialized = "\n".join(record.getMessage() for record in caplog.records)
    assert raw_user not in serialized
    assert raw_message not in serialized
    # P-A：body user 字段映射为持久主体；日志同样不得出现主体与派生会话 ID
    fingerprint = hashlib.sha256(
        f"qxd-user:{raw_user}".encode("utf-8")
    ).hexdigest()
    with SessionLocal() as db:
        mapping = (
            db.query(ExternalIdentity)
            .filter(
                ExternalIdentity.provider == "qxd_user",
                ExternalIdentity.claim_fingerprint == fingerprint,
            )
            .one()
        )
    assert mapping.subject_id not in serialized
    derived_session = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tsing-radar:qxd-interview:{mapping.subject_id}:{raw_user}",
        )
    )
    assert derived_session not in serialized
    qxd_chat._reset_trial_state_for_tests()


def test_nonstreaming_completion_contract(monkeypatch):
    async def fake_reply(_request, _principal):
        return qxd_chat.AgentReply(content="完整回答")

    monkeypatch.setattr(qxd_chat, "generate_agent_reply", fake_reply)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [
                {"role": "system", "content": "系统提示"},
                {"role": "user", "content": "你好"},
            ],
            "stream": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("chatcmpl-")
    assert payload["object"] == "chat.completion"
    assert isinstance(payload["created"], int)
    assert payload["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "完整回答"},
            "finish_reason": "stop",
        }
    ]
    assert payload["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert "x_soda" not in payload


def test_stream_must_be_json_boolean():
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "stream": "false",
        },
    )
    assert response.status_code == 422


def test_probe_stream_sequence_usage_and_attachment(monkeypatch):
    attachment = SodaAttachment(
        fileUrl="https://files.example.edu/report.pdf",
        fileName="调研报告.pdf",
        fileType="pdf",
        mimeType="application/pdf",
        fileSize=42,
    )

    async def fake_reply(_request, _principal):
        return qxd_chat.AgentReply(
            content="测试流式回答",
            attachments=(attachment,),
        )

    monkeypatch.setattr(qxd_chat, "generate_agent_reply", fake_reply)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": None,
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
            "max_tokens": 1,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    data_lines = [
        line.removeprefix("data:").strip()
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]
    assert data_lines[-1] == "[DONE]"
    frames = [json.loads(line) for line in data_lines[:-1]]

    role_frames = [
        frame
        for frame in frames
        if frame["choices"][0]["delta"].get("role") == "assistant"
    ]
    stop_frames = [
        frame
        for frame in frames
        if frame["choices"][0]["finish_reason"] is not None
    ]
    assert len(role_frames) == 1
    assert frames[0] is role_frames[0]
    assert len(stop_frames) == 1
    assert frames[-1] is stop_frames[0]
    assert stop_frames[0]["choices"][0]["delta"] == {}
    assert stop_frames[0]["choices"][0]["finish_reason"] == "stop"
    assert stop_frames[0]["usage"]["total_tokens"] == 0
    assert stop_frames[0]["x_soda"]["attachments"][0]["fileType"] == "pdf"
    assert all("x_soda" not in frame for frame in frames[:-1])


def test_qxd_multiturn_confirmation_triggers_shared_a4_and_honest_empty_reason():
    user_id = f"qxd-e2e-{uuid.uuid4()}"
    headers = _qxd_headers(user_id)
    user_turns = [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "愿意探索高风险新方向",
        "只能北京、每周至少3天",
    ]
    first = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "tsing-radar",
            "user": user_id,
            "messages": [
                {"role": "user", "content": content}
                for content in user_turns
            ],
            "stream": False,
        },
    )
    assert "地点必须在“北京”" in first.json()["choices"][0]["message"]["content"]

    user_turns.append("确认")
    second = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": user_id,
            "messages": [
                {"role": "user", "content": content}
                for content in user_turns
            ],
            "stream": False,
        },
    )
    assert "每周至少投入 3 天" in second.json()["choices"][0]["message"]["content"]

    user_turns.append("确认")
    third = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": user_id,
            "messages": [
                {"role": "user", "content": content}
                for content in user_turns
            ],
            "stream": False,
        },
    )
    third_content = third.json()["choices"][0]["message"]["content"]
    assert "已确认硬性条件" in third_content
    assert "field|" not in third_content

    user_turns.append("确认画像")
    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "tsing-radar",
            "user": user_id,
            "messages": [
                {"role": "user", "content": content}
                for content in user_turns
            ],
            "stream": True,
        },
    )
    assert response.status_code == 200
    data_lines = [
        line.removeprefix("data:").strip()
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]
    assert data_lines[-1] == "[DONE]"
    frames = [json.loads(line) for line in data_lines[:-1]]
    content = "".join(
        frame["choices"][0]["delta"].get("content", "")
        for frame in frames
    )
    assert "暂无通过审核的数据" in content
    assert "推荐你" not in content
    assert frames[-1]["choices"][0]["finish_reason"] == "stop"
    assert frames[-1]["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    session_id = _qxd_session_id(user_id, user_id)
    with SessionLocal() as db:
        portrait = db.get(QuestionnaireSession, session_id).portrait
    constraints = portrait["hard_constraints"]
    assert [
        (item["field"], item["operator"], item["value"])
        for item in constraints
    ] == [
        ("location", "one_of", ["北京"]),
        ("weekly_commitment_days", "minimum", ["3"]),
    ]


@pytest.mark.parametrize(
    ("constraint_turns", "expected_locations"),
    [
        (["只能北京", "修改为上海", "确认"], ["上海"]),
        (["只能北京", "不作为硬约束"], []),
    ],
)
def test_qxd_constraint_modification_and_rejection_branches(
    constraint_turns,
    expected_locations,
):
    user_id = f"qxd-constraint-branch-{uuid.uuid4()}"
    headers = _qxd_headers(user_id)
    base_turns = [
        "自然语言处理",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
    ]
    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": user_id,
            "messages": [
                {"role": "user", "content": content}
                for content in [
                    *base_turns,
                    *constraint_turns,
                    "确认画像",
                ]
            ],
            "stream": False,
        },
    )
    assert response.status_code == 200
    assert "暂无通过审核的数据" in response.json()["choices"][0]["message"]["content"]
    session_id = _qxd_session_id(user_id, user_id)
    with SessionLocal() as db:
        portrait = db.get(QuestionnaireSession, session_id).portrait
    locations = [
        value
        for item in portrait["hard_constraints"]
        if item["field"] == "location"
        for value in item["value"]
    ]
    assert locations == expected_locations


def test_output_attachment_contract_rejects_relative_or_private_urls():
    with pytest.raises(ValidationError):
        SodaAttachment(
            fileUrl="/files/report.pdf",
            fileName="report.pdf",
            fileType="pdf",
            mimeType="application/pdf",
        )
    with pytest.raises(ValidationError):
        SodaAttachment(
            fileUrl="http://127.0.0.1/report.pdf",
            fileName="report.pdf",
            fileType="pdf",
            mimeType="application/pdf",
        )
    with pytest.raises(ValidationError):
        SodaAttachment(
            fileUrl="https://files.example.edu/report.txt",
            fileName="report.txt",
            fileType="txt",
            mimeType="text/plain",
        )
    with pytest.raises(ValidationError):
        SodaAttachment(
            fileUrl="https://files.example.edu/not-a-pdf.txt",
            fileName="report.pdf",
            fileType="pdf",
            mimeType="text/plain",
        )


def test_input_audio_base64_is_rejected():
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "转写"},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": "ZmFrZQ==",
                                "format": "mp3",
                            },
                        },
                    ],
                }
            ]
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "content_part",
    [
        {
            "type": "image_url",
            "image_url": {"url": "https://oss.example.edu/image.png"},
        },
        {
            "type": "input_audio",
            "input_audio": {
                "url": "https://oss.example.edu/audio.mp3",
                "format": "mp3",
            },
        },
        {
            "type": "file",
            "file": {
                "url": "https://oss.example.edu/document.pdf",
                "filename": "document.pdf",
            },
        },
        {
            "type": "file",
            "file": {"file_id": "file-123", "filename": "document.pdf"},
        },
    ],
)
def test_remote_media_disabled_rejects_before_fetch(
    monkeypatch,
    content_part,
):
    class FailIfCalledFetcher:
        resolver_calls = 0
        transport_calls = 0

        async def fetch(self, *_args, **_kwargs):
            self.resolver_calls += 1
            self.transport_calls += 1
            raise AssertionError("disabled media input must not fetch")

    fetcher = FailIfCalledFetcher()
    monkeypatch.setattr(qxd_chat.settings, "QXD_REMOTE_MEDIA_FETCH_ENABLED", False)
    monkeypatch.setattr(qxd_chat, "media_fetcher", fetcher)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [content_part],
                }
            ]
        },
    )
    assert response.status_code == 422
    assert fetcher.resolver_calls == 0
    assert fetcher.transport_calls == 0


def test_multimodal_url_is_fetched_during_request(monkeypatch):
    fetched_urls: list[tuple[str, str]] = []

    class FakeFetcher:
        async def fetch(self, url, kind, *, filename=None, max_bytes=None):
            fetched_urls.append((url, kind))
            return FetchedMedia(
                kind=kind,
                source_url=url,
                final_url=url,
                filename=filename,
                content_type="image/png",
                size=4,
                sha256="0" * 64,
            )

    monkeypatch.setattr(qxd_chat.settings, "QXD_REMOTE_MEDIA_FETCH_ENABLED", True)
    monkeypatch.setattr(qxd_chat, "media_fetcher", FakeFetcher())
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "识别图片"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "https://oss.example.edu/image.png"
                            },
                        },
                    ],
                }
            ]
        },
    )
    assert response.status_code == 200
    assert fetched_urls == [("https://oss.example.edu/image.png", "image")]


def test_file_id_is_accepted_without_url_fetch(monkeypatch):
    class FailFetcher:
        async def fetch(self, *_args, **_kwargs):
            raise AssertionError("file_id 不应触发 URL 下载")

    monkeypatch.setattr(qxd_chat.settings, "QXD_REMOTE_MEDIA_FETCH_ENABLED", True)
    monkeypatch.setattr(qxd_chat, "media_fetcher", FailFetcher())
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "file",
                            "file": {
                                "file_id": "file-123",
                                "filename": "材料.pdf",
                            },
                        }
                    ],
                }
            ]
        },
    )
    assert response.status_code == 200


def _qxd_session_id_from_session_id(claim: str, gateway_session_id: str) -> str:
    """按网关 sessionId 派生持久访谈会话键（与 chat.py 的 uuid5 规则一致）。"""
    fingerprint = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        f"identity-map:{claim}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with SessionLocal() as db:
        mapping = (
            db.query(ExternalIdentity)
            .filter(ExternalIdentity.claim_fingerprint == fingerprint)
            .one()
        )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            (
                "tsing-radar:qxd-session:"
                f"{mapping.subject_id}:{gateway_session_id}"
            ),
        )
    )


def _user_turn_count(session_id: str) -> int:
    with SessionLocal() as db:
        session = db.get(QuestionnaireSession, session_id)
        assert session is not None
        return sum(
            1 for item in (session.messages or []) if item.get("role") == "user"
        )


def test_qxd_session_id_continues_same_conversation_across_requests():
    claim = f"qxd-sid-continue-{uuid.uuid4()}"
    headers = _qxd_headers(claim)
    gateway_session = f"gw-{uuid.uuid4().hex[:16]}"

    first = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "sessionId": gateway_session,
            "messages": [{"role": "user", "content": "自然语言处理"}],
        },
    )
    assert first.status_code == 200
    assert "工程与落地" in first.json()["choices"][0]["message"]["content"]

    # 平台每轮回传全量历史；相同 sessionId 必须命中同一会话并推进。
    second = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "sessionId": gateway_session,
            "messages": [
                {"role": "user", "content": "自然语言处理"},
                {"role": "user", "content": "工程落地"},
            ],
        },
    )
    assert second.status_code == 200
    second_content = second.json()["choices"][0]["message"]["content"]
    assert "高频具体指导" in second_content

    session_id = _qxd_session_id_from_session_id(claim, gateway_session)
    assert _user_turn_count(session_id) == 2


def test_qxd_session_id_isolates_conversations_between_ids_and_subjects():
    claim_a = f"qxd-sid-iso-a-{uuid.uuid4()}"
    claim_b = f"qxd-sid-iso-b-{uuid.uuid4()}"
    session_one = f"gw-one-{uuid.uuid4().hex[:12]}"
    session_two = f"gw-two-{uuid.uuid4().hex[:12]}"

    advanced = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim_a),
        json={
            "sessionId": session_one,
            "messages": [
                {"role": "user", "content": "自然语言处理"},
                {"role": "user", "content": "工程落地"},
            ],
        },
    )
    assert advanced.status_code == 200
    assert "高频具体指导" in advanced.json()["choices"][0]["message"]["content"]

    # 同用户、不同 sessionId：新会话从头开始，不透出旧会话进度。
    fresh_same_user = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim_a),
        json={
            "sessionId": session_two,
            "messages": [{"role": "user", "content": "自然语言处理"}],
        },
    )
    assert fresh_same_user.status_code == 200
    fresh_same_user_content = fresh_same_user.json()["choices"][0]["message"][
        "content"
    ]
    assert "工程与落地" in fresh_same_user_content
    assert "高频具体指导" not in fresh_same_user_content

    # 不同用户、相同 sessionId：会话键与主体绑定，互不串扰。
    fresh_other_user = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim_b),
        json={
            "sessionId": session_one,
            "messages": [{"role": "user", "content": "自然语言处理"}],
        },
    )
    assert fresh_other_user.status_code == 200
    fresh_other_user_content = fresh_other_user.json()["choices"][0]["message"][
        "content"
    ]
    assert "工程与落地" in fresh_other_user_content
    assert "高频具体指导" not in fresh_other_user_content

    key_a1 = _qxd_session_id_from_session_id(claim_a, session_one)
    key_a2 = _qxd_session_id_from_session_id(claim_a, session_two)
    key_b1 = _qxd_session_id_from_session_id(claim_b, session_one)
    assert len({key_a1, key_a2, key_b1}) == 3
    assert _user_turn_count(key_a1) == 2
    assert _user_turn_count(key_a2) == 1
    assert _user_turn_count(key_b1) == 1


@pytest.mark.parametrize(
    "bad_session_id",
    ["含 空格的会话", "中文会话编号", "   ", "id with spaces"],
)
def test_qxd_malformed_session_id_is_treated_as_missing(bad_session_id):
    claim = f"qxd-sid-bad-{uuid.uuid4()}"
    conversation = f"conv-{uuid.uuid4().hex[:12]}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "user": conversation,
            "sessionId": bad_session_id,
            "messages": [{"role": "user", "content": "自然语言处理"}],
        },
    )
    assert response.status_code == 200
    assert "工程与落地" in response.json()["choices"][0]["message"]["content"]
    # 非法 sessionId 按缺失处理：回退到 user 字段派生的访谈会话键。
    fallback_session_id = _qxd_session_id(claim, conversation)
    assert _user_turn_count(fallback_session_id) == 1


def test_stream_reasoning_frames_precede_content_and_nonstream_omits_reasoning(
    monkeypatch,
):
    async def fake_reply(_request, _principal):
        return qxd_chat.AgentReply(
            content="带思考过程的回答",
            reasoning=("正在检索匹配导师…", "正在核实证据与置信度…"),
        )

    monkeypatch.setattr(qxd_chat, "generate_agent_reply", fake_reply)
    streamed = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
        },
    )
    assert streamed.status_code == 200
    data_lines = [
        line.removeprefix("data:").strip()
        for line in streamed.text.splitlines()
        if line.startswith("data:")
    ]
    assert data_lines[-1] == "[DONE]"
    frames = [json.loads(line) for line in data_lines[:-1]]

    kinds = []
    for frame in frames:
        if frame["choices"][0]["finish_reason"] is not None:
            kinds.append("stop")
            continue
        delta = frame["choices"][0]["delta"]
        if delta.get("role") == "assistant":
            kinds.append("role")
        elif "reasoning" in delta:
            kinds.append("reasoning")
        elif "content" in delta:
            kinds.append("content")
    assert kinds[0] == "role"
    reasoning_at = [index for index, kind in enumerate(kinds) if kind == "reasoning"]
    assert len(reasoning_at) == 2
    content_at = [index for index, kind in enumerate(kinds) if kind == "content"]
    assert content_at and min(content_at) > max(reasoning_at)
    assert kinds[-1] == "stop"
    assert frames[-1]["choices"][0]["delta"] == {}
    assert frames[-1]["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    non_stream = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "stream": False,
        },
    )
    assert non_stream.status_code == 200
    assert "reasoning" not in non_stream.text


def _matched_outcome() -> MatchApplicationOutcome:
    return MatchApplicationOutcome(
        status="matched",
        items=[
            {
                "advisor_id": "T00001",
                "name": "测试导师",
                "dept": "自动化系",
                "score": 87.25,
                "fit_score": 91.5,
                "evidence_coverage": 0.75,
                "evidence_confidence": 0.8,
                "score_breakdown": [
                    {
                        "objective": "topic_fit",
                        "requested_weight": 0.4,
                        "score": 0.95,  # 95 分 > 91.5 → 拉高
                        "method": "exact-category-v1",
                        "evidence_coverage": 1.0,
                        "evidence_confidence": 0.8,
                        "conservative_contribution": 0.304,
                    },
                    {
                        "objective": "mentorship_fit",
                        "requested_weight": 0.2,
                        "score": 0.8,  # 80 分 < 91.5 → 拉低
                        "method": "exact-category-v1",
                        "evidence_coverage": 1.0,
                        "evidence_confidence": 0.9,
                        "conservative_contribution": 0.144,
                    },
                    {
                        "objective": "career_fit",
                        "requested_weight": 0.2,
                        "score": 0.9,  # 90 分 ≈ 91.5 → 中位
                        "method": "exact-category-v1",
                        "evidence_coverage": 1.0,
                        "evidence_confidence": 0.7,
                        "conservative_contribution": 0.126,
                    },
                    {
                        "objective": "innovation_fit",
                        "requested_weight": 0.1,
                        "score": None,  # 无画像证据 → 未计入
                        "method": "not-scored",
                        "evidence_coverage": 0.0,
                        "evidence_confidence": 0.0,
                        "conservative_contribution": 0.0,
                    },
                ],
                "explanation": {
                    "supporting_evidence": [
                        {
                            "statement": "近三年在 NLP 顶会发表论文 12 篇",
                            "citations": [{"citation": "导师主页·2025"}],
                        },
                    ],
                    "counter_evidence": [],
                    "uncertainties": [],
                    "questions_to_verify": [],
                },
            }
        ],
        meta={},
        message="基于已确认画像找到 1 个证据化候选。",
        questions=[],
    )


def _matched_outcome_two() -> MatchApplicationOutcome:
    """v3.1.6 双候选 fixture：第二位用于「第 N 个」追问黑盒断言。"""
    first = _matched_outcome().items[0]
    second = {
        "advisor_id": "T00002",
        "name": "测试导师二",
        "dept": "计算机系",
        "score": 82.4,
        "fit_score": 88.0,
        "evidence_coverage": 0.8,
        "evidence_confidence": 0.75,
        "explanation": {
            "supporting_evidence": [
                {
                    "statement": "在系统方向有多年工程沉淀",
                    "citations": [{"citation": "实验室主页·2024"}],
                },
            ],
            "counter_evidence": [],
            "uncertainties": [],
            "questions_to_verify": [],
        },
    }
    return MatchApplicationOutcome(
        status="matched",
        items=[first, second],
        meta={"match_candidate_records": 2, "interview_status": "confirmed"},
        message="基于已确认画像找到 2 个证据化候选。",
        questions=[],
    )


def _patch_recommend_ready(monkeypatch, outcome: MatchApplicationOutcome) -> None:
    """把对话主链路桩到 recommend_ready 状态，专注断言意图分支行为。"""
    monkeypatch.setattr(
        qxd_chat, "sync_user_transcript", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(
        qxd_chat,
        "state_response",
        lambda _session: SimpleNamespace(
            recommend_ready=True,
            assistant_message="画像已确认。",
        ),
    )
    monkeypatch.setattr(
        qxd_chat, "run_confirmed_match", lambda *_args, **_kwargs: outcome
    )
    monkeypatch.setattr(
        qxd_chat, "confirmed_portrait", lambda *_args, **_kwargs: None
    )
    # v3.1.6：匹配结果上下文下的「第 N 个」追问短路（隔离 DB 会话依赖）
    monkeypatch.setattr(
        qxd_chat,
        "_ordinal_follows_match_results",
        lambda *_args, **_kwargs: True,
    )


def test_qxd_recruitment_intent_honest_empty_state(monkeypatch):
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    claim = f"qxd-recruit-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "有招募信息吗"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert "暂无通过审核" in content
    assert "https://www.tsingradar.com.cn/recruitment" in content
    assert "x_soda" not in payload


def test_qxd_radar_intent_without_approved_scores_is_honest_and_attachmentless(
    monkeypatch,
):
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    monkeypatch.setattr(qxd_chat, "public_score_bundles", lambda: ({}, {}))
    claim = f"qxd-radar-empty-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "雷达图"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert "暂无候选导师的已审核客观评分" in content
    assert "x_soda" not in payload


def test_qxd_radar_intent_issues_signed_svg_attachment(monkeypatch):
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    bundle = {
        "values": {key: 80 for key in qxd_chat.OBJECTIVE_DIMENSION_KEYS}
    }
    monkeypatch.setattr(
        qxd_chat,
        "public_score_bundles",
        lambda: ({"T00001": bundle}, {"release_version": "v-test"}),
    )
    series = RadarSeries(
        name="客观证据（已审核）",
        values=[80.0] * 4,
        color=ADVISOR_TRAIT_COLOR,
    )
    monkeypatch.setattr(
        qxd_chat,
        "build_radar_series_for_advisor",
        lambda _advisor_id, _bundles=None: series,
    )
    claim = f"qxd-radar-attach-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "雷达图"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    attachment = payload["x_soda"]["attachments"][0]
    assert attachment["fileType"] == "image"
    assert attachment["mimeType"] == "image/svg+xml"
    assert "/v1/radar/" in attachment["fileUrl"]
    assert attachment["fileUrl"].startswith(
        "https://agent.example.edu/v1/radar/"
    )
    assert attachment["fileName"].endswith(".svg")
    content = payload["choices"][0]["message"]["content"]
    assert "已生成 测试导师 的客观证据雷达图" in content
    # 客观与主观分离声明
    assert "客观指标与匿名主观评价严格分离" in content


def test_qxd_radar_intent_text_chart_when_attachments_disabled(monkeypatch):
    """清小搭仅对话端口（无附件能力）：雷达图指令应直出文本字符版雷达图。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    values = [88.0, 96.0, 60.0, 78.0]
    bundle = {
        "values": {
            key: value
            for key, value in zip(qxd_chat.OBJECTIVE_DIMENSION_KEYS, values)
        }
    }
    monkeypatch.setattr(
        qxd_chat,
        "public_score_bundles",
        lambda: ({"T00001": bundle}, {"release_version": "v-test"}),
    )
    series = RadarSeries(
        name="客观证据（已审核）",
        values=values,
        color=ADVISOR_TRAIT_COLOR,
    )
    monkeypatch.setattr(
        qxd_chat,
        "build_radar_series_for_advisor",
        lambda _advisor_id, _bundles=None: series,
    )
    # 仅对话端口：无附件交付能力 → 文本版降级
    monkeypatch.setattr(qxd_chat.settings, "QXD_ATTACHMENTS_ENABLED", False)
    claim = f"qxd-radar-text-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "雷达图"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    # 文本版雷达图：字符条形 + 标题 + 四维标签 + 数值
    assert "雷达图附件当前未启用" in content
    assert "仅对话端口直出" in content
    assert "█" in content
    assert "测试导师 客观证据雷达图" in content
    for label in ("项目广度", "研究主题广度", "联系信息完整度", "研究资料完整度"):
        assert label in content
    for value in ("88", "96", "60", "78"):
        assert value in content
    # 诚实性：客观与主观严格分离声明 + 样本来源（v + release_version 拼接）
    assert "客观指标与匿名主观评价严格分离" in content
    assert "样本来源：已审核评分发布" in content
    assert "v-test" in content
    # 无附件输出
    assert "x_soda" not in payload


def test_radar_chart_endpoint_serves_deterministic_svg_and_rejects_tampering(
    monkeypatch,
):
    series = RadarSeries(
        name="客观证据（已审核）",
        values=[80.0, 60.0, 90.0, 70.0],
        color=ADVISOR_TRAIT_COLOR,
    )
    monkeypatch.setattr(
        qxd_chat,
        "build_radar_series_for_advisor",
        lambda _advisor_id, _bundles=None: series,
    )
    token, _expires_at = issue_radar_chart_token("T00001")

    first = client.get(f"/v1/radar/{token}")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in first.text

    second = client.get(f"/v1/radar/{token}")
    assert second.status_code == 200
    assert second.content == first.content

    flipped = "0" if not token.endswith("0") else "1"
    tampered = f"{token[:-1]}{flipped}"
    assert client.get(f"/v1/radar/{tampered}").status_code == 404


def test_expression_layer_rewrites_interviewee_reply_when_available(monkeypatch):
    async def fake_render(_fact_pack):
        return SimpleNamespace(
            text="那我们继续聊聊：你更偏好算法理论研究，还是实际应用？",
            provider="glm",
            status="available",
        )

    monkeypatch.setattr(qxd_chat, "render_interview_reply", fake_render)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"messages": [{"role": "user", "content": "我对强化学习感兴趣"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == "那我们继续聊聊：你更偏好算法理论研究，还是实际应用？"


def test_expression_layer_falls_back_to_fixed_reply_when_disabled(monkeypatch):
    async def fake_render(_fact_pack):
        return SimpleNamespace(text=None, provider=None, status="disabled")

    monkeypatch.setattr(qxd_chat, "render_interview_reply", fake_render)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={"messages": [{"role": "user", "content": "我对强化学习感兴趣"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    # 降级：固定模板（首轮访谈题）非空，且绝不含表达层文本
    assert content
    assert "那我们继续聊聊" not in content


def test_expression_layer_skipped_for_platform_probe(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("连接探测请求不应触发表达层")

    monkeypatch.setattr(qxd_chat, "render_interview_reply", boom)
    response = client.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "stream": True,
            "max_tokens": 1,
        },
    )
    assert response.status_code == 200


def test_expression_layer_skipped_on_confirmation_gate_and_match(monkeypatch):
    """诚实性红线：画像确认门与匹配结果保持确定性原文，不进入表达层。"""

    async def fake_render(_fact_pack):
        return SimpleNamespace(
            text="[GLM-增强] 自然重写内容",
            provider="glm",
            status="available",
        )

    render_calls = []
    monkeypatch.setattr(
        qxd_chat,
        "render_interview_reply",
        lambda fp: render_calls.append(fp) or fake_render(fp),
    )

    user_id = f"qxd-gate-{uuid.uuid4()}"
    headers = _qxd_headers(user_id)
    user_turns = [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "愿意探索高风险新方向",
        "只能北京",
    ]
    # 提问轮（IN_PROGRESS）：表达层生效
    for n in range(1, len(user_turns) + 1):
        resp = client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "user": user_id,
                "messages": [
                    {"role": "user", "content": turn} for turn in user_turns[:n]
                ],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        assert (
            resp.json()["choices"][0]["message"]["content"]
            == "[GLM-增强] 自然重写内容"
        )
    assert len(render_calls) == 6

    # 确认硬性条件草案 → 画像总结轮（AWAITING_CONFIRMATION）：不增强
    user_turns.append("确认")
    resp = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": user_id,
            "messages": [
                {"role": "user", "content": turn} for turn in user_turns
            ],
            "stream": False,
        },
    )
    summary = resp.json()["choices"][0]["message"]["content"]
    assert "确认画像" in summary  # 确定性确认引导保留
    assert "[GLM-增强]" not in summary
    assert len(render_calls) == 6  # 总结轮未调用表达层

    # 确认画像 → 匹配结果（recommend_ready）：不增强
    user_turns.append("确认画像")
    resp = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "user": user_id,
            "messages": [
                {"role": "user", "content": turn} for turn in user_turns
            ],
            "stream": False,
        },
    )
    outcome = resp.json()["choices"][0]["message"]["content"]
    assert "[GLM-增强]" not in outcome
    assert len(render_calls) == 6  # 匹配轮未调用表达层


# ---------------------------------------------------------------- v2.5 对话模式


def _dialogue_headers(claim: str) -> dict[str, str]:
    return _qxd_headers(claim)


def _post_dialogue(
    claim: str,
    content: str,
    *,
    session_id: str,
    stream: bool = False,
    max_tokens: int | None = None,
):
    body: dict = {
        "messages": [{"role": "user", "content": content}],
        "sessionId": session_id,
        "stream": stream,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return client.post(
        "/v1/chat/completions",
        headers=_dialogue_headers(claim),
        json=body,
    )


def _ensure_qxd_identity(claim: str) -> None:
    """预热：首次带 claim 的请求创建 ExternalIdentity 映射（get_qxd_principal
    依赖注入内完成），_qxd_session_id 依赖该行存在。探测请求（max_tokens=1）
    不进入对话模式也不推进访谈，不会污染任何会话状态。"""
    warm = _post_dialogue(
        claim,
        "你好",
        session_id=f"warm-{uuid.uuid4()}",
        max_tokens=1,
    )
    assert warm.status_code == 200


def test_qxd_resume_build_multiturn_dialogue_blackbox():
    from app.db.session import SessionLocal
    from app.models.questionnaire_session import QuestionnaireSession

    claim = f"qxd-resume-{uuid.uuid4()}"
    conversation = f"resume-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)

    first = _post_dialogue(claim, "帮我从零写一份简历", session_id=session_id)
    assert first.status_code == 200
    first_text = first.json()["choices"][0]["message"]["content"]
    assert "第一步" in first_text
    assert "姓名" in first_text

    answers = [
        "张三",
        "计算机科学与技术系 · 软件工程",
        "大三 · 3.8/4.0 · 数据结构、机器学习",
        "NLP 项目：负责模型训练，完成情感分类",
        "挑战杯二等奖\n担任班级学习委员",
        "英语六级 · test@example.com",
    ]
    final_text = ""
    for answer in answers:
        resp = _post_dialogue(claim, answer, session_id=session_id)
        assert resp.status_code == 200
        final_text = resp.json()["choices"][0]["message"]["content"]

    assert "简历初稿已生成" in final_text
    assert "张三" in final_text
    # 对话模式不触碰访谈状态机：本会话不应产生问卷访谈记录
    with SessionLocal() as db:
        interview_rows = (
            db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.session_id == session_id)
            .count()
        )
        assert interview_rows == 0


def test_qxd_probe_never_enters_dialogue_mode():
    claim = f"qxd-probe-{uuid.uuid4()}"
    conversation = f"probe-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)
    resp = _post_dialogue(
        claim,
        "帮我从零写一份简历",
        session_id=session_id,
        max_tokens=1,
    )
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    # 探测请求绝不进入对话模式（不应出现简历第一步引导语）
    assert "第一步" not in content


def test_qxd_recruitment_dialogue_before_interview_and_reasoning_stage():
    claim = f"qxd-recruit2-{uuid.uuid4()}"
    conversation = f"recruit-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)
    resp = _post_dialogue(
        claim, "有招募信息吗", session_id=session_id, stream=True
    )
    assert resp.status_code == 200
    data_lines = [
        line.removeprefix("data:").strip()
        for line in resp.text.splitlines()
        if line.startswith("data:")
    ]
    assert data_lines[-1] == "[DONE]"
    frames = [json.loads(line) for line in data_lines[:-1]]

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for frame in frames:
        delta = frame["choices"][0].get("delta") or {}
        if "reasoning" in delta:
            reasoning_parts.append(delta["reasoning"])
        if "content" in delta:
            content_parts.append(delta["content"])
    content = "".join(content_parts)
    assert "暂无通过审核且仍在招期内的招募信息" in content
    assert "https://www.tsingradar.com.cn/recruitment" in content
    # 分派走对话模式：reasoning 应为检索档位，而非访谈档位
    assert any("正在为你检索并整理信息…" in part for part in reasoning_parts)
    # 诚实空态不附带任何交付物
    assert not any("x_soda" in frame for frame in frames)


def test_qxd_scatter_query_honest_gate_closed_blackbox():
    claim = f"qxd-scatter-{uuid.uuid4()}"
    conversation = f"scatter-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)
    resp = _post_dialogue(claim, "四象限导师分布怎么样", session_id=session_id)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "暂不能诚实地进行四象限分类" in content


def test_qxd_consult_faq_honest_not_collected_blackbox():
    claim = f"qxd-faq-{uuid.uuid4()}"
    conversation = f"faq-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)
    resp = _post_dialogue(claim, "组会频率一般怎么样", session_id=session_id)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "暂未收录" in content
    assert "官方邮箱" in content


def test_qxd_consult_email_blackbox():
    claim = f"qxd-mail-{uuid.uuid4()}"
    conversation = f"mail-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)
    resp = _post_dialogue(claim, "给王老师写一封套磁邮件", session_id=session_id)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "套磁信初稿" in content
    assert "王老师" in content


def test_qxd_research_style_multiturn_blackbox():
    """v3.1.4 科研风格速测：清小搭仅对话端口多轮直出，不触碰访谈状态机。"""
    from app.db.session import SessionLocal
    from app.models.questionnaire_session import QuestionnaireSession

    claim = f"qxd-style-{uuid.uuid4()}"
    conversation = f"style-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)

    first = _post_dialogue(claim, "测测我的科研风格", session_id=session_id)
    assert first.status_code == 200
    first_text = first.json()["choices"][0]["message"]["content"]
    assert "第一题" in first_text
    assert "不判断你是否适合科研" in first_text

    # 依次作答：1(范围-broad) / 从方法创新出发(method) / 2(工程) / 论文(paper)
    final_text = ""
    for answer in ("1", "从方法创新出发", "2", "论文"):
        resp = _post_dialogue(claim, answer, session_id=session_id)
        assert resp.status_code == 200
        final_text = resp.json()["choices"][0]["message"]["content"]

    assert "【你的科研风格速测结果】" in final_text
    assert "多线·方法工程型" in final_text
    # 诚实性：结果不评价能力高低、不写入六维评分
    assert "不评价能力高低" in final_text
    assert "「确认」后生效" in final_text
    # 对话模式不触碰访谈状态机：本会话不应产生问卷访谈记录
    with SessionLocal() as db:
        interview_rows = (
            db.query(QuestionnaireSession)
            .filter(QuestionnaireSession.session_id == session_id)
            .count()
        )
        assert interview_rows == 0


def test_qxd_direction_map_single_turn_blackbox():
    """v3.1.4 方向地图：单轮输出公开方向清单，不输出参考教师名单。"""
    claim = f"qxd-dir-{uuid.uuid4()}"
    conversation = f"dir-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)

    resp = _post_dialogue(claim, "有哪些方向", session_id=session_id)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "【研究方向地图】" in content
    assert "自然语言处理" in content
    assert "大模型 / 大语言模型" in content
    assert "不涉及具体导师" in content
    # 治理边界：方向地图只输出学科方向本身，不输出参考教师名单
    assert "参考教师" not in content
    assert "回复其中一个方向名" in content


def test_qxd_research_style_cancel_blackbox():
    """v3.1.4 科研风格速测：中途取消退出并清除模式状态。"""
    claim = f"qxd-style-cancel-{uuid.uuid4()}"
    conversation = f"style-cancel-conv-{uuid.uuid4()}"
    _ensure_qxd_identity(claim)
    session_id = _qxd_session_id(claim, conversation)

    first = _post_dialogue(claim, "测测我的科研风格", session_id=session_id)
    assert first.status_code == 200
    assert "第一题" in first.json()["choices"][0]["message"]["content"]

    cancel = _post_dialogue(claim, "不测了", session_id=session_id)
    assert cancel.status_code == 200
    content = cancel.json()["choices"][0]["message"]["content"]
    assert "已退出科研风格速测" in content

    # 退出后可正常触发其它对话模式（不被残留状态拦截）
    again = _post_dialogue(claim, "有哪些方向", session_id=session_id)
    assert again.status_code == 200
    assert "【研究方向地图】" in again.json()["choices"][0]["message"]["content"]


def test_qxd_match_outcome_includes_fit_breakdown_blackbox(monkeypatch):
    """v3.1.5 特色：匹配输出含「契合度构成」分解（拉高/拉低/中位/未计入）。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    claim = f"qxd-breakdown-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "查看匹配结果"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "契合度 92 分" in content  # 91.5 四舍五入
    assert "契合度构成" in content
    assert "非新增评分" in content  # 诚实声明：构成分解只解释不新增评分
    assert "▲ 拉高：方向匹配（权重 40%）—— 95 分" in content
    assert "▼ 拉低：指导方式（权重 20%）—— 80 分" in content
    assert "· 中位：生涯去向（权重 20%）—— 90 分" in content
    assert "创新偏好：未计入（画像无该维度证据，确认后生效）" in content


def test_qxd_match_outcome_omits_breakdown_when_absent(monkeypatch):
    """无 score_breakdown 的旧数据/桩：诚实省略构成块，其余输出不受影响。"""
    outcome = _matched_outcome()
    for item in outcome.items:
        item.pop("score_breakdown", None)
    _patch_recommend_ready(monkeypatch, outcome)
    claim = f"qxd-no-breakdown-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "查看匹配结果"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "契合度 92 分" in content
    assert "契合度构成" not in content


# —— v3.1.6 匹配后「第 N 个」候选追问（详情 / 雷达 / 套磁 / 越界诚实） ——


def test_qxd_match_ordinal_shows_single_candidate_detail(monkeypatch):
    _patch_recommend_ready(monkeypatch, _matched_outcome_two())
    claim = f"qxd-ordinal-detail-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "第2个"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    # 单候选详情头 + 第二位候选事实（不重新输出整份匹配列表）
    assert "第 2 位候选详情" in content
    assert "测试导师二" in content
    assert "计算机系" in content
    assert "契合度 88 分" in content
    assert "x_soda" not in payload


def test_qxd_match_ordinal_radar_selects_candidate(monkeypatch):
    """「雷达图 第2个」应按序号选择第二位候选并签发其 SVG。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome_two())
    bundle = {
        "values": {key: 90 for key in qxd_chat.OBJECTIVE_DIMENSION_KEYS}
    }
    monkeypatch.setattr(
        qxd_chat,
        "public_score_bundles",
        lambda: ({"T00001": bundle, "T00002": bundle}, {"release_version": "v-test"}),
    )
    monkeypatch.setattr(
        qxd_chat,
        "build_radar_series_for_advisor",
        lambda _advisor_id, _bundles=None: RadarSeries(
            name="客观证据（已审核）",
            values=[90.0] * 4,
            color=ADVISOR_TRAIT_COLOR,
        ),
    )
    claim = f"qxd-ordinal-radar-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "雷达图 第2个"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    attachment = payload["x_soda"]["attachments"][0]
    assert attachment["fileType"] == "image"
    assert attachment["mimeType"] == "image/svg+xml"
    content = payload["choices"][0]["message"]["content"]
    assert "已生成 测试导师二 的客观证据雷达图" in content


def test_qxd_match_ordinal_email_targets_candidate(monkeypatch):
    """「第2个的套磁邮件」应按序号把候选名注入套磁邮件生成。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome_two())
    seen: list[str] = []

    async def fake_consult_email(*, latest_user: str, portrait=None):
        seen.append(latest_user)
        return "【套磁信初稿】\n尊敬的测试导师二老师：……（确定性模板）", None

    monkeypatch.setattr(qxd_chat, "handle_consult_email", fake_consult_email)
    claim = f"qxd-ordinal-email-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "第2个的套磁邮件"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert seen == ["给测试导师二写一封套磁邮件"]
    assert "为第 2 位候选 测试导师二 生成套磁邮件" in content
    assert "【套磁信初稿】" in content
    assert "x_soda" not in payload


def test_qxd_match_ordinal_out_of_range_is_honest(monkeypatch):
    _patch_recommend_ready(monkeypatch, _matched_outcome_two())
    claim = f"qxd-ordinal-oob-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "第9个"}]},
    )
    assert response.status_code == 200
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    assert "当前匹配结果只有 2 位候选" in content
    assert "第 1 到第 2" in content
    assert "x_soda" not in payload


# —— v3.1.7 匹配结果二次筛选（换一批 / 缩小范围 / 恢复完整结果） ——


def _refined_batch_outcome() -> MatchApplicationOutcome:
    """换一批 fixture：排除已展示候选后的新批次（T00003，含主页与方向）。"""
    return MatchApplicationOutcome(
        status="matched",
        items=[
            {
                "advisor_id": "T00003",
                "name": "新批次导师",
                "dept": "软件学院",
                "score": 79.2,
                "fit_score": 84.0,
                "evidence_coverage": 0.7,
                "evidence_confidence": 0.85,
                "research_keywords": ["大模型"],
                "official_homepage": "https://example.com/new-prof",
                "explanation": {
                    "supporting_evidence": [
                        {
                            "statement": "在大模型对齐方向有公开成果",
                            "citations": [
                                {"citation": "论文·2024", "source": "public"}
                            ],
                        },
                    ],
                    "counter_evidence": [],
                    "uncertainties": [],
                    "questions_to_verify": [],
                },
            }
        ],
        meta={},
        message="基于已确认画像找到 1 个证据化候选。",
        questions=[],
    )


def _narrowed_outcome() -> MatchApplicationOutcome:
    """缩小范围 fixture：按方向过滤后的候选（T00004）。"""
    return MatchApplicationOutcome(
        status="matched",
        items=[
            {
                "advisor_id": "T00004",
                "name": "筛选后导师",
                "dept": "计算机系",
                "score": 81.0,
                "fit_score": 87.0,
                "evidence_coverage": 0.75,
                "evidence_confidence": 0.8,
                "research_keywords": ["自然语言处理"],
                "explanation": {
                    "supporting_evidence": [
                        {
                            "statement": "在自然语言处理方向有公开积累",
                            "citations": [
                                {"citation": "主页·2025", "source": "public"}
                            ],
                        },
                    ],
                    "counter_evidence": [],
                    "uncertainties": [],
                    "questions_to_verify": [],
                },
            }
        ],
        meta={},
        message="基于已确认画像找到 1 个证据化候选。",
        questions=[],
    )


def _refine_outcome_for(extra_constraints) -> MatchApplicationOutcome:
    """按附加硬约束返回对应批次（模拟 match_mentors 硬过滤行为）。

    无约束 → 基础双候选；有 ADVISOR_ID EXCLUDES → 换一批新批次；
    有 RESEARCH_TOPIC CONTAINS → 缩小范围后的过滤结果。
    """
    include: list[str] = []
    excluded: list[str] = []
    for constraint in extra_constraints or []:
        if constraint.get("field") == "research_topic":
            if constraint.get("operator") == "contains":
                include = list(constraint.get("value") or [])
        elif constraint.get("field") == "advisor_id":
            excluded = list(constraint.get("value") or [])
    if include:
        return _narrowed_outcome()
    if excluded:
        return _refined_batch_outcome()
    return _matched_outcome_two()


def _patch_refine_ready(monkeypatch) -> None:
    """桩到 recommend_ready 且基础重跑/二次筛选共用同一约束驱动的假匹配。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome_two())
    monkeypatch.setattr(
        qxd_chat,
        "run_confirmed_match",
        lambda _db, *, extra_constraints=None, **_kwargs: _refine_outcome_for(
            extra_constraints
        ),
    )
    monkeypatch.setattr(
        match_refine_service,
        "run_confirmed_match",
        lambda _db, *, extra_constraints=None, **_kwargs: _refine_outcome_for(
            extra_constraints
        ),
    )


def _qxd_refine_claim(tag: str) -> str:
    return f"qxd-refine-{tag}-{uuid.uuid4()}"


def test_qxd_refine_change_batch_excludes_shown(monkeypatch):
    """换一批：排除已展示候选后重新匹配，输出含主页链接与能力差距分析。"""
    _patch_refine_ready(monkeypatch)
    claim = _qxd_refine_claim("change")
    headers = _qxd_headers(claim)

    first = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "查看匹配结果"}]},
    )
    assert first.status_code == 200
    base_content = first.json()["choices"][0]["message"]["content"]
    assert "测试导师" in base_content and "测试导师二" in base_content
    assert "换一批" in base_content  # 引导文案含二次筛选入口

    second = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "换一批"}]},
    )
    assert second.status_code == 200
    content = second.json()["choices"][0]["message"]["content"]
    assert "已排除已展示的 2 位候选" in content
    assert "新批次导师" in content
    assert "测试导师" not in content  # 已展示候选不再出现
    assert "官方主页：https://example.com/new-prof" in content
    assert "能力差距：暂无画像证据" in content
    assert "Transformer 架构与注意力机制" in content


def test_qxd_refine_narrow_scope_two_questions(monkeypatch):
    """缩小范围：两问状态机 → 按方向过滤重跑，输出过滤后候选。"""
    _patch_refine_ready(monkeypatch)
    claim = _qxd_refine_claim("narrow")
    headers = _qxd_headers(claim)

    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "查看匹配结果"}]},
    )
    q1 = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "缩小范围"}]},
    )
    assert q1.status_code == 200
    q1_content = q1.json()["choices"][0]["message"]["content"]
    assert "集中在哪些方向或技术上" in q1_content

    q2 = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "大模型、多模态"}]},
    )
    assert q2.status_code == 200
    q2_content = q2.json()["choices"][0]["message"]["content"]
    assert "排除的方向或技术" in q2_content

    done = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "无"}]},
    )
    assert done.status_code == 200
    content = done.json()["choices"][0]["message"]["content"]
    assert "已按你的筛选条件重新匹配" in content
    assert "筛选后导师" in content
    assert "能力差距" in content
    assert "自然语言处理" in content


def test_qxd_refine_ordinal_consistent_after_change(monkeypatch):
    """换一批后「第 N 个」追问与二次筛选批次一致（不回到旧批次）。"""
    _patch_refine_ready(monkeypatch)
    claim = _qxd_refine_claim("ordinal")
    headers = _qxd_headers(claim)

    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "查看匹配结果"}]},
    )
    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "换一批"}]},
    )
    third = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "第1个"}]},
    )
    assert third.status_code == 200
    content = third.json()["choices"][0]["message"]["content"]
    assert "第 1 位候选详情" in content
    assert "新批次导师" in content
    assert "测试导师" not in content


def test_qxd_refine_reset_restores_full(monkeypatch):
    """恢复完整结果：清空二次筛选条件后回到全量结果。"""
    _patch_refine_ready(monkeypatch)
    claim = _qxd_refine_claim("reset")
    headers = _qxd_headers(claim)

    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "查看匹配结果"}]},
    )
    client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "换一批"}]},
    )
    restored = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"messages": [{"role": "user", "content": "恢复完整结果"}]},
    )
    assert restored.status_code == 200
    content = restored.json()["choices"][0]["message"]["content"]
    assert "已恢复完整结果" in content
    assert "测试导师" in content  # 全量候选回归


def test_qxd_refine_first_change_is_honest(monkeypatch):
    """首次直接「换一批」（无已展示批次）→ 诚实说明无法排除。"""
    _patch_refine_ready(monkeypatch)
    claim = _qxd_refine_claim("first")
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "换一批"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "还没有已展示的候选可排除" in content


def test_qxd_matched_state_off_topic_gives_capability_guidance(monkeypatch):
    """v4.0.0：已匹配态收到跑题消息 → 能力引导，不再静默复读匹配结果。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    claim = f"qxd-offtopic-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "讲个笑话"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "这个话题我暂时帮不上忙" in content
    assert "可以继续追问" not in content  # 不再复读匹配引导
    assert "x_soda" not in response.json()


def test_qxd_matched_state_weather_is_guided_not_absorbed(monkeypatch):
    """v4.0.0：天气类消息在匹配态给引导，不静默重跑。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    claim = f"qxd-weather-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "今天天气怎么样"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "暂时帮不上忙" in content


def test_qxd_matched_state_acknowledgment_keeps_follow_ups(monkeypatch):
    """v4.0.0：致谢消息 → 简短回应 + 保留候选追问引导。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    claim = f"qxd-thanks-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "谢谢"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "不客气" in content
    assert "可以继续追问" in content


def test_qxd_matched_state_relevant_question_still_reruns(monkeypatch):
    """v4.0.0：匹配相关提问不受跑题兜底影响，仍正常复跑+引导。"""
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    claim = f"qxd-relevant-{uuid.uuid4()}"
    response = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={"messages": [{"role": "user", "content": "哪个导师更适合我"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "可以继续追问" in content
    assert "测试导师" in content


def _complete_qxd_interview_turns() -> list[str]:
    """走到画像确认门前的完整访谈轮次（与既有多轮确认测试同一口径）。

    两个“确认”分别确认地点与每周投入的约束草案，随后状态机进入
    awaiting_confirmation（回复里会出现“确认无误请回复‘确认画像’”）。
    """
    return [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "愿意探索高风险新方向",
        "只能北京、每周至少3天",
        "确认",
        "确认",
    ]


def test_qxd_confirmation_touches_relevant_recruitment_once(monkeypatch):
    """v4.0.0：确认画像 → 匹配结果附带一次招募提示；后续消息不再触发。"""
    user_id = f"qxd-proactive-{uuid.uuid4()}"
    headers = _qxd_headers(user_id)
    turns = _complete_qxd_interview_turns()
    monkeypatch.setattr(
        qxd_chat,
        "proactive_recruitment_hint",
        lambda *_a, **_k: (
            "顺带一提：自然语言处理课题组（科研助理，截止 2027-01-01）"
            "正在开放。回复「招募信息」可查看。"
        ),
    )

    def _post(messages):
        return client.post(
            "/v1/chat/completions",
            headers=headers,
            json={
                "model": "tsing-radar",
                "user": user_id,
                "messages": [{"role": "user", "content": c} for c in messages],
                "stream": False,
            },
        )

    # 第一段：走到画像确认门（awaiting_confirmation）
    first = _post(turns)
    assert "确认无误请回复" in first.json()["choices"][0]["message"]["content"]

    # 第二段：确认画像 → 匹配结果 + 一次性招募提示
    confirmed_turns = [*turns, "确认画像"]
    second = _post(confirmed_turns)
    second_content = second.json()["choices"][0]["message"]["content"]
    assert "顺带一提" in second_content
    assert "回复「招募信息」" in second_content

    # 后续非确认消息：匹配结果正常复跑，但不再附带招募提示（仅一次）
    follow = _post([*confirmed_turns, "哪个导师更适合我"])
    follow_content = follow.json()["choices"][0]["message"]["content"]
    assert "顺带一提" not in follow_content
    assert "暂无通过审核的数据" in follow_content


def test_qxd_confirmation_silent_without_relevant_recruitment(monkeypatch):
    """v4.0.0：无画像相关开放招募时，确认回复保持诚实，不提示招募。"""
    user_id = f"qxd-proactive-empty-{uuid.uuid4()}"
    headers = _qxd_headers(user_id)
    turns = [*_complete_qxd_interview_turns(), "确认画像"]
    monkeypatch.setattr(
        qxd_chat, "proactive_recruitment_hint", lambda *_a, **_k: None
    )
    response = client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "tsing-radar",
            "user": user_id,
            "messages": [{"role": "user", "content": c} for c in turns],
            "stream": False,
        },
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "顺带一提" not in content
