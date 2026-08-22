"""v4.3.0 阶段五：LLM 自主工具调用（工具域转正）+ 收藏 + 敏感工具二次确认测试。

验收口径（任务书 §五）：
- ⑤-① 协议接入：tool_calls 解析正确；无 key 降级回服务端路由（行为逐字一致）；
- ⑤-② 收藏：新表 + 迁移 0015 + 幂等收藏；意图词与自主调用双路径均可用；
- ⑤-③ 敏感工具：send_contact_request 无确认词不执行；确认后走既有链路；
- ⑤-④ 红线：幻觉工具名/参数注入/未注册能力调用全部拒绝。
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.core.config import Settings
from app.models.mentor_favorite import MentorFavorite
from app.services import autonomous_tools as at
from app.services.llm import LLMToolCall, _parse_tool_calls
from app.services.tools_registry import (
    LLM_TOOL_SCHEMAS,
    PENDING_CONTACT_KEY,
    TOOL_SAVE_FAVORITE,
    TOOL_SEND_CONTACT_REQUEST,
    build_tool_runtime,
    dispatch_tool_call,
    format_favorite_listing,
    is_sensitive_tool,
    remove_favorite,
)

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"

ITEMS = [
    {"advisor_id": "adv-alpha", "name": "张三丰"},
    {"advisor_id": "adv-beta", "name": "李琦"},
    {"advisor_id": "adv-gamma", "name": "王重阳"},
]


# —— ⑤-① 协议：tool_calls 解析 ——


class TestParseToolCalls:
    def test_string_arguments_parsed(self):
        calls = _parse_tool_calls(
            [
                {
                    "id": "call-1",
                    "function": {
                        "name": "save_favorite",
                        "arguments": '{"advisor_id": "adv-alpha"}',
                    },
                }
            ]
        )
        assert calls == (
            LLMToolCall(
                name="save_favorite",
                arguments={"advisor_id": "adv-alpha"},
                call_id="call-1",
            ),
        )

    def test_dict_arguments_accepted(self):
        calls = _parse_tool_calls(
            [
                {
                    "id": "c",
                    "function": {
                        "name": "get_recruitments",
                        "arguments": {"limit": 2},
                    },
                }
            ]
        )
        assert calls[0].arguments == {"limit": 2}

    def test_malformed_arguments_become_none(self):
        calls = _parse_tool_calls(
            [
                {
                    "id": "c",
                    "function": {
                        "name": "save_favorite",
                        "arguments": "{not json",
                    },
                }
            ]
        )
        # 解析失败 → None（注册表校验 fail-closed 拒绝，不编造默认值）
        assert calls[0].arguments is None

    def test_truncated_to_three_and_skips_malformed(self):
        raw = [
            {"id": str(i), "function": {"name": "recall_memory"}}
            for i in range(5)
        ] + [{"id": "x"}, {"id": "y", "function": {"name": ""}}]
        calls = _parse_tool_calls(raw)
        assert len(calls) == 3
        assert all(call.name == "recall_memory" for call in calls)

    def test_non_list_returns_empty(self):
        assert _parse_tool_calls(None) == ()
        assert _parse_tool_calls("nope") == ()


# —— ⑤-④ 红线：注册表白名单制 ——


class TestRegistryWhitelist:
    def test_llm_schemas_only_marked_tools(self):
        names = {schema["function"]["name"] for schema in LLM_TOOL_SCHEMAS}
        assert names == {
            "query_mentor_knowledge",
            "get_recruitments",
            "recall_memory",
            "save_favorite",
            "send_contact_request",
        }

    def test_forbidden_capabilities_never_registered(self):
        """画像确认/匹配触发/记忆写入/招募发布永不注册为 LLM 可调工具。"""
        import app.services.tools_registry as registry

        source = open(registry.__file__, encoding="utf-8").read()
        registered = set(registry._TOOL_DEFINITIONS)
        forbidden = {
            "confirm_profile",
            "trigger_match",
            "remember_communication_stage",
            "remember_confirmed_portrait",
            "write_memory",
            "publish_recruitment",
            "clear_memories",
        }
        assert not (registered & forbidden)
        # 写路径仅经 memory_service 枚举门禁；注册表不 import 记忆写函数
        assert "remember_confirmed_portrait" not in source
        assert "remember_communication_stage" not in source

    def test_sensitive_flag(self):
        assert is_sensitive_tool(TOOL_SEND_CONTACT_REQUEST) is True
        assert is_sensitive_tool(TOOL_SAVE_FAVORITE) is False


# —— ⑤-② 收藏：执行体 ——


def _runtime(db, student, items=ITEMS, session_id="s-fav"):
    return build_tool_runtime(
        db=db,
        student_id=student,
        session_id=session_id,
        match_items=items,
    )


class TestSaveFavoriteExecutor:
    def test_favorite_saved_idempotently(self):
        student = f"fav-{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            runtime = _runtime(db, student)
            first = dispatch_tool_call(
                runtime,
                name=TOOL_SAVE_FAVORITE,
                arguments={"advisor_id": "adv-alpha"},
            )
            assert first == "已收藏导师 张三丰。回复「我的收藏」可随时查看。"
            rows = (
                db.query(MentorFavorite)
                .filter(MentorFavorite.student_id == student)
                .all()
            )
            assert len(rows) == 1
            assert rows[0].advisor_name == "张三丰"
            second = dispatch_tool_call(
                runtime,
                name=TOOL_SAVE_FAVORITE,
                arguments={"advisor_id": "adv-alpha"},
            )
            assert second == "张三丰 已在收藏列表，无需重复收藏。"
            assert (
                db.query(MentorFavorite)
                .filter(MentorFavorite.student_id == student)
                .count()
                == 1
            )

    def test_hallucinated_advisor_id_rejected(self):
        """LLM 编造的 advisor_id（不在匹配上下文）→ 拒绝，不写库。"""
        student = f"fav-{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            runtime = _runtime(db, student)
            reply = dispatch_tool_call(
                runtime,
                name=TOOL_SAVE_FAVORITE,
                arguments={"advisor_id": "adv-does-not-exist"},
            )
            assert "不在当前匹配候选" in reply
            assert (
                db.query(MentorFavorite)
                .filter(MentorFavorite.student_id == student)
                .count()
                == 0
            )

    def test_listing_and_remove(self):
        student = f"fav-{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            runtime = _runtime(db, student)
            dispatch_tool_call(
                runtime, name=TOOL_SAVE_FAVORITE, arguments={"advisor_id": "adv-alpha"}
            )
            dispatch_tool_call(
                runtime, name=TOOL_SAVE_FAVORITE, arguments={"advisor_id": "adv-beta"}
            )
            listing = format_favorite_listing(db, student)
            assert "当前收藏了 2 位导师" in listing
            assert "1. 张三丰" in listing and "2. 李琦" in listing
            removed = remove_favorite(db, student_id=student, ordinal=1)
            assert removed == "已取消收藏 张三丰。"
            out_of_range = remove_favorite(db, student_id=student, ordinal=5)
            assert "共有 1 位导师" in out_of_range
        assert format_favorite_listing(db, student).startswith("当前收藏了 1 位导师")

    def test_empty_listing_honest(self):
        student = f"fav-{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            assert "收藏列表为空" in format_favorite_listing(db, student)


# —— ⑤-③ 敏感工具：执行体只登记待确认，绝不直接执行 ——


class TestContactRequestExecutor:
    def test_registers_pending_and_asks_confirmation(self):
        student = f"contact-{uuid.uuid4().hex[:8]}"
        session_id = f"s-contact-{uuid.uuid4().hex[:6]}"
        with SessionLocal() as db:
            runtime = _runtime(db, student, session_id=session_id)
            reply = dispatch_tool_call(
                runtime,
                name=TOOL_SEND_CONTACT_REQUEST,
                arguments={
                    "advisor_id": "adv-beta",
                    "message": "想聊聊NLP方向",
                },
            )
            assert "确认请回复「确认联系李琦」" in reply
            assert "未确认前不会执行任何联系操作" in reply
            pending = at.load_pending_contact(
                db, session_id=session_id, student_id=student
            )
        assert pending == {
            "advisor_id": "adv-beta",
            "advisor_name": "李琦",
            "message": "想聊聊NLP方向",
        }

    def test_no_session_graceful(self):
        student = f"contact-{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            runtime = build_tool_runtime(
                db=db, student_id=student, match_items=ITEMS
            )
            reply = dispatch_tool_call(
                runtime,
                name=TOOL_SEND_CONTACT_REQUEST,
                arguments={"advisor_id": "adv-alpha"},
            )
        assert "未执行任何联系操作" in reply

    def test_confirmation_word_helpers(self):
        assert at.is_contact_confirmation("确认联系李琦", "李琦") is True
        assert at.is_contact_confirmation("确认联系李琦老师", "李琦") is False
        assert at.is_contact_confirmation("确认", "李琦") is False
        assert at.is_contact_confirmation("确认联系王重阳", "李琦") is False
        assert at.is_contact_cancellation("取消") is True
        assert at.is_contact_cancellation("算了") is True
        assert at.is_contact_cancellation("那算了") is False


# —— ⑤-① 自主调用层（monkeypatch 模拟有 key 环境）——


def _keyed_settings() -> Settings:
    return Settings(_env_file=None, LLM_PROVIDER="glm", GLM_API_KEY="test-key")


class TestAutonomousLayer:
    @pytest.mark.asyncio
    async def test_ready_requires_key_and_flag(self, monkeypatch):
        monkeypatch.setattr(at, "settings", _keyed_settings())
        assert at.autonomous_tools_ready() is True
        monkeypatch.setattr(
            at,
            "settings",
            Settings(_env_file=None, QXD_AUTONOMOUS_TOOLS_ENABLED=False),
        )
        assert at.autonomous_tools_ready() is False

    @pytest.mark.asyncio
    async def test_no_key_returns_none(self, monkeypatch):
        # 测试环境默认无 key：降级为 None（行为与基线一致）
        monkeypatch.setattr(at, "settings", Settings(_env_file=None))
        result = await at.try_autonomous_tool_call(
            SimpleNamespace(),
            latest_user="帮我收藏张三丰",
            session_id="s-x",
            student_id="stu-x",
            match_items=ITEMS,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_tool_calls_dispatched_deterministically(self, monkeypatch):
        monkeypatch.setattr(at, "settings", _keyed_settings())

        async def fake_llm(messages, **_kwargs):
            return SimpleNamespace(
                text="",
                provider="glm",
                model="glm-4-flash",
                tool_calls=(
                    LLMToolCall(
                        name=TOOL_SAVE_FAVORITE,
                        arguments={"advisor_id": "adv-alpha"},
                        call_id="c1",
                    ),
                ),
            )

        monkeypatch.setattr(at, "_llm_complete_result", fake_llm)
        student = f"auto-{uuid.uuid4().hex[:8]}"
        with SessionLocal() as db:
            reply = await at.try_autonomous_tool_call(
                db,
                latest_user="帮我收藏张三丰",
                session_id="s-auto",
                student_id=student,
                match_items=ITEMS,
            )
        assert reply == "已收藏导师 张三丰。回复「我的收藏」可随时查看。"
        with SessionLocal() as db:
            assert (
                db.query(MentorFavorite)
                .filter(
                    MentorFavorite.student_id == student,
                    MentorFavorite.advisor_id == "adv-alpha",
                )
                .count()
                == 1
            )

    @pytest.mark.asyncio
    async def test_hallucinated_tool_fail_closed(self, monkeypatch):
        """⑤-④：LLM 编造工具名 → dispatch 确定性错误文本，不抛异常。"""
        monkeypatch.setattr(at, "settings", _keyed_settings())

        async def fake_llm(messages, **_kwargs):
            return SimpleNamespace(
                text="",
                provider="glm",
                model="glm-4-flash",
                tool_calls=(
                    LLMToolCall(
                        name="confirm_profile",  # 未注册能力（红线）
                        arguments={},
                        call_id="c1",
                    ),
                ),
            )

        monkeypatch.setattr(at, "_llm_complete_result", fake_llm)
        with SessionLocal() as db:
            reply = await at.try_autonomous_tool_call(
                db,
                latest_user="直接确认我的画像",
                session_id="s-hallu",
                student_id="stu-hallu",
                match_items=ITEMS,
            )
        assert "未知工具「confirm_profile」" in reply

    @pytest.mark.asyncio
    async def test_param_injection_rejected(self, monkeypatch):
        """⑤-④：参数注入（未声明键）→ 校验拒绝。"""
        monkeypatch.setattr(at, "settings", _keyed_settings())

        async def fake_llm(messages, **_kwargs):
            return SimpleNamespace(
                text="",
                provider="glm",
                model="glm-4-flash",
                tool_calls=(
                    LLMToolCall(
                        name=TOOL_SAVE_FAVORITE,
                        arguments={"advisor_id": "adv-alpha", "student_id": "别的学生"},
                        call_id="c1",
                    ),
                ),
            )

        monkeypatch.setattr(at, "_llm_complete_result", fake_llm)
        with SessionLocal() as db:
            reply = await at.try_autonomous_tool_call(
                db,
                latest_user="收藏",
                session_id="s-inject",
                student_id="stu-inject",
                match_items=ITEMS,
            )
        assert "工具参数无效" in reply
        assert "未知参数" in reply

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_none(self, monkeypatch):
        monkeypatch.setattr(at, "settings", _keyed_settings())

        async def fake_llm(messages, **_kwargs):
            return SimpleNamespace(
                text="",
                provider="glm",
                model="glm-4-flash",
                tool_calls=(),
            )

        monkeypatch.setattr(at, "_llm_complete_result", fake_llm)
        with SessionLocal() as db:
            assert (
                await at.try_autonomous_tool_call(
                    db,
                    latest_user="谢谢",
                    session_id="s-none",
                    student_id="stu-none",
                    match_items=ITEMS,
                )
                is None
            )


# —— 黑盒：匹配态双路径 ——


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


def _ensure_identity(claim: str) -> str:
    fingerprint = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        f"identity-map:{claim}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with SessionLocal() as db:
        from app.models.identity import ExternalIdentity

        mapping = (
            db.query(ExternalIdentity)
            .filter(ExternalIdentity.claim_fingerprint == fingerprint)
            .one_or_none()
        )
        if mapping is None:
            mapping = ExternalIdentity(
                mapping_id=str(uuid.uuid4()),
                provider="qxd",
                claim_fingerprint=fingerprint,
                subject_id=f"usr_{uuid.uuid4().hex}",
            )
            db.add(mapping)
            db.commit()
        return mapping.subject_id


def _session_id(claim: str) -> str:
    subject = _ensure_identity(claim)
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tsing-radar:qxd-interview:{subject}:stage5",
        )
    )


def _post(claim: str, session_id: str, messages: list[str]):
    return client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "model": "tsing-radar",
            "user": claim,
            "messages": [
                {"role": "user", "content": c} for c in messages
            ],
            "stream": False,
        },
    )


def _matched_fixture(monkeypatch, claim: str) -> str:
    """走到已确认 + 匹配候选展示态，返回 session_id。"""
    from app.api.v1 import chat as qxd_chat

    def fake_run(db, *, session_id, student_id, **_kwargs):
        return SimpleNamespace(
            status="matched",
            items=[
                dict(item) for item in [
                    {"advisor_id": "adv-alpha", "name": "张三丰"},
                    {"advisor_id": "adv-beta", "name": "李琦"},
                ]
            ],
            meta={"match_candidate_records": 2},
            message="ok",
            questions=[],
        )

    def fake_format(outcome, *, profile, advisor_ratings=None, user_dimension_scores=None):
        return "测试匹配结果"

    monkeypatch.setattr(qxd_chat, "run_confirmed_match", fake_run)
    monkeypatch.setattr(qxd_chat, "format_match_outcome", fake_format)
    session_id = _session_id(claim)
    turns = [
        "自然语言处理、对话系统",
        "工程落地",
        "高频具体指导",
        "产业就业",
        "成熟稳妥路线",
        "无",
        "确认画像",
    ]
    response = _post(claim, session_id, turns)
    assert response.status_code == 200
    assert "测试匹配结果" in response.json()["choices"][0]["message"]["content"]
    return session_id


def test_favorite_intent_word_path_blackbox(monkeypatch):
    """⑤-② 黑盒：「收藏第 1 个」意图词路由 → 入库；「我的收藏」可查。"""
    claim = f"fav-bb-{uuid.uuid4().hex[:8]}"
    session_id = _matched_fixture(monkeypatch, claim)
    subject = _ensure_identity(claim)

    response = _post(claim, session_id, ["收藏第 1 个"])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "已收藏导师 张三丰" in content

    listing = _post(claim, session_id, ["我的收藏"])
    assert listing.status_code == 200
    listing_content = listing.json()["choices"][0]["message"]["content"]
    assert "当前收藏了 1 位导师" in listing_content
    assert "1. 张三丰" in listing_content

    remove = _post(claim, session_id, ["取消收藏第 1 个"])
    assert remove.status_code == 200
    assert "已取消收藏 张三丰" in remove.json()["choices"][0]["message"]["content"]
    with SessionLocal() as db:
        assert (
            db.query(MentorFavorite)
            .filter(MentorFavorite.student_id == subject)
            .count()
            == 0
        )


def test_favorite_by_name_and_out_of_range(monkeypatch):
    claim = f"fav-name-{uuid.uuid4().hex[:8]}"
    session_id = _matched_fixture(monkeypatch, claim)
    response = _post(claim, session_id, ["收藏李琦老师"])
    assert response.status_code == 200
    assert "已收藏导师 李琦" in response.json()["choices"][0]["message"]["content"]
    out = _post(claim, session_id, ["收藏王重阳"])
    assert out.status_code == 200
    assert "不在其中" in out.json()["choices"][0]["message"]["content"]


def test_autonomous_path_blackbox(monkeypatch):
    """⑤-② 黑盒：自主调用路径（模拟 LLM 返回 save_favorite tool_call）。"""
    claim = f"auto-bb-{uuid.uuid4().hex[:8]}"
    session_id = _matched_fixture(monkeypatch, claim)

    async def fake_llm(messages, **_kwargs):
        return SimpleNamespace(
            text="",
            provider="glm",
            model="glm-4-flash",
            tool_calls=(
                LLMToolCall(
                    name=TOOL_SAVE_FAVORITE,
                    arguments={"advisor_id": "adv-beta"},
                    call_id="c1",
                ),
            ),
        )

    from app.services import autonomous_tools as at_module

    monkeypatch.setattr(
        at_module, "settings", Settings(_env_file=None, LLM_PROVIDER="glm", GLM_API_KEY="k")
    )
    monkeypatch.setattr(at_module, "_llm_complete_result", fake_llm)
    response = _post(claim, session_id, ["帮我把第二位收藏一下"])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "已收藏导师 李琦" in content


def test_baseline_without_key_unchanged(monkeypatch):
    """⑤-① 黑盒：无 key（测试环境默认）→ 跑题兜底与基线一致。"""
    claim = f"base-bb-{uuid.uuid4().hex[:8]}"
    session_id = _matched_fixture(monkeypatch, claim)
    response = _post(claim, session_id, ["今天天气不错"])
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    # 跑题消息 → 能力引导（未因自主调用层存在而改变）
    assert "这个话题我暂时帮不上忙哦" in content


def test_contact_request_full_gate_blackbox(monkeypatch):
    """⑤-③ 黑盒：登记 → 精确确认执行 / 非确认消息失效。"""
    claim = f"contact-bb-{uuid.uuid4().hex[:8]}"
    session_id = _matched_fixture(monkeypatch, claim)

    async def fake_llm(messages, **_kwargs):
        return SimpleNamespace(
            text="",
            provider="glm",
            model="glm-4-flash",
            tool_calls=(
                LLMToolCall(
                    name=TOOL_SEND_CONTACT_REQUEST,
                    arguments={"advisor_id": "adv-alpha", "message": "想去组里"},
                    call_id="c1",
                ),
            ),
        )

    from app.services import autonomous_tools as at_module

    monkeypatch.setattr(
        at_module, "settings", Settings(_env_file=None, LLM_PROVIDER="glm", GLM_API_KEY="k")
    )
    monkeypatch.setattr(at_module, "_llm_complete_result", fake_llm)

    # 1) LLM 发起 → 只登记待确认，返回确认指令
    initiated = _post(claim, session_id, ["我想联系第一位导师"])
    assert initiated.status_code == 200
    initiated_content = initiated.json()["choices"][0]["message"]["content"]
    assert "确认请回复「确认联系张三丰」" in initiated_content
    assert "未确认前不会执行任何联系操作" in initiated_content

    # 2) 模糊确认词（非精确）→ 不执行，且待确认动作失效
    vague = _post(claim, session_id, ["好的确认"])
    assert vague.status_code == 200
    vague_content = vague.json()["choices"][0]["message"]["content"]
    assert "套磁信初稿" not in vague_content

    # 3) 再次发起 → 精确确认 → 走既有套磁链路（记录联系阶段）
    _post(claim, session_id, ["还是想联系第一位导师"])
    confirmed = _post(claim, session_id, ["确认联系张三丰"])
    assert confirmed.status_code == 200
    confirmed_content = confirmed.json()["choices"][0]["message"]["content"]
    assert "已确认联系 张三丰" in confirmed_content
    assert "套磁信初稿" in confirmed_content
    subject = _ensure_identity(claim)
    with SessionLocal() as db:
        from app.services.memory_service import recall_memories

        assert (
            recall_memories(db, subject).get("communication_stage") == "联系中"
        )
        # 待确认动作已清除（不会二次触发）
        from app.services.dialogue_state_store import get_session_value

        assert (
            get_session_value(
                db,
                session_id=session_id,
                student_id=subject,
                key=PENDING_CONTACT_KEY,
            )
            in (None, "")
        )

    # 4) 取消路径
    _post(claim, session_id, ["再帮我联系第二位导师"])
    cancelled = _post(claim, session_id, ["取消"])
    assert cancelled.status_code == 200
    assert "已取消联系" in cancelled.json()["choices"][0]["message"]["content"]
    assert "未执行任何联系操作" in cancelled.json()["choices"][0]["message"]["content"]
