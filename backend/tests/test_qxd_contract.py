"""清小搭 OpenAI-compatible 协议合同测试。"""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import chat as qxd_chat
from app.main import app
from app.db.session import SessionLocal
from app.models.questionnaire_session import QuestionnaireSession
from app.models.identity import ExternalIdentity
from app.schemas.qxd import SodaAttachment
from app.services.qxd_media import FetchedMedia

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
