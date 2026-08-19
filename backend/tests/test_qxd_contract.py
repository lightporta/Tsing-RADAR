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
    assert qxd_chat._trial_state.session_id not in serialized
    assert qxd_chat._trial_state.subject_id not in serialized
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
    assert "暂无候选导师的已审核六维评分" in content
    assert "x_soda" not in payload


def test_qxd_radar_intent_issues_signed_svg_attachment(monkeypatch):
    _patch_recommend_ready(monkeypatch, _matched_outcome())
    bundle = {
        "values": {f"trait_{key}": 80 for key in qxd_chat.TRAIT_KEYS}
    }
    monkeypatch.setattr(
        qxd_chat,
        "public_score_bundles",
        lambda: ({"T00001": bundle}, {"release_version": "v-test"}),
    )
    series = RadarSeries(
        name="导师特质（已审核评分）",
        values=[80.0] * 6,
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
    assert "已生成 测试导师 的导师特质雷达图" in payload["choices"][0]["message"][
        "content"
    ]


def test_radar_chart_endpoint_serves_deterministic_svg_and_rejects_tampering(
    monkeypatch,
):
    series = RadarSeries(
        name="导师特质（已审核评分）",
        values=[80.0, 60.0, 90.0, 70.0, 50.0, 85.0],
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
