"""v2.5 简历对话模块测试：分步采集状态机、优化降级、定向解析、交付诚实性。"""

from __future__ import annotations

import asyncio
import types
import uuid

import pytest

from app.db.session import SessionLocal
from app.models.dialogue_state import DialogueSession
from app.services.dialogue_state_store import (
    clear_dialogue_state,
    get_dialogue_mode,
    get_dialogue_state,
)
from app.services.identity import Principal
from app.services.resume_dialogue import (
    FIELD_SEQUENCE,
    MODE_RESUME_BUILD,
    RESUME_DELIVERY_CONFIRMATION,
    build_resume_request,
    handle_resume_build,
    handle_resume_polish,
    handle_resume_targeted,
    parse_target_from_message,
    render_resume_markdown,
)


@pytest.fixture(autouse=True)
def isolate_dialogue_sessions():
    """清理跨测试的对话模式状态（简历采集等）。"""
    yield
    with SessionLocal() as db:
        db.query(DialogueSession).delete(synchronize_session=False)
        db.commit()


@pytest.mark.asyncio
async def test_resume_build_collects_all_fields_and_finalizes():
    with SessionLocal() as db:
        session_id = "resume-build-test-session"
        student_id = "student-test-1"

        # 第一步：触发从零生成
        reply, attachment = await handle_resume_build(
            db,
            latest_user="帮我从零写一份简历",
            session_id=session_id,
            student_id=student_id,
        )
        assert "第一步" in reply
        assert attachment is None
        assert (
            get_dialogue_mode(db, session_id=session_id, student_id=student_id)
            == MODE_RESUME_BUILD
        )

        answers = {
            "student_name": "张三",
            "dept": "计算机科学与技术系 · 软件工程",
            "education": "大三 · 3.8/4.0 · 数据结构、机器学习",
            "projects": "NLP 项目：担任核心开发，使用 PyTorch，完成情感分类模型",
            "awards_positions": "挑战杯二等奖\n担任班级学习委员",
            "extras": "英语六级 · 邮箱 test@example.com",
        }
        collected: list[str] = []
        for key, _ in FIELD_SEQUENCE:
            reply, _attachment = await handle_resume_build(
                db,
                latest_user=answers[key],
                session_id=session_id,
                student_id=student_id,
            )
            collected.append(reply)
        # 采集完成后的收尾回复应包含简历与后续选项
        final = collected[-1]
        assert "简历初稿已生成" in final
        assert "张三" in final
        assert "计算机科学与技术系" in final
        assert "挑战杯二等奖" in final
        # 平台仅支持匹配报告公开转存：PDF 引导到 Web 端简历中心（诚实说明）
        assert "Web 端简历中心" in final
        assert RESUME_DELIVERY_CONFIRMATION not in final

        # 状态进入交付等待阶段
        state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
        assert state["phase"] == "awaiting_delivery"
        assert set(state["fields"]) == set(answers)


@pytest.mark.asyncio
async def test_resume_build_cancel_exits_and_clears_state():
    with SessionLocal() as db:
        session_id = "resume-cancel-test"
        student_id = "student-test-2"
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        assert (
            get_dialogue_mode(db, session_id=session_id, student_id=student_id)
            == MODE_RESUME_BUILD
        )
        reply, _ = await handle_resume_build(
            db,
            latest_user="取消",
            session_id=session_id,
            student_id=student_id,
        )
        assert "已退出简历模式" in reply
        assert (
            get_dialogue_mode(db, session_id=session_id, student_id=student_id)
            is None
        )


@pytest.mark.asyncio
async def test_resume_build_done_terms_close_flow():
    with SessionLocal() as db:
        session_id = "resume-done-test"
        student_id = "student-test-3"
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        reply, _ = await handle_resume_build(
            db,
            latest_user="完成",
            session_id=session_id,
            student_id=student_id,
        )
        assert "简历流程已完成" in reply


def test_render_resume_markdown_deterministic_and_honest():
    fields = {
        "student_name": "李四",
        "dept": "自动化系",
        "education": "大二 · 3.6 · 控制理论",
        "projects": "ROS 机器人项目；负责感知模块",
        "awards_positions": "国家奖学金",
        "extras": "",
    }
    markdown = render_resume_markdown(fields)
    assert markdown.startswith("# 李四 个人简历")
    assert "## 教育背景" in markdown
    assert "国家奖学金" in markdown
    # 诚实性：明确标注"未经真实性核验"
    assert "未经真实性核验" in markdown
    # 空字段不渲染为章节
    assert "## 技能与补充" not in markdown


def test_build_resume_request_maps_fields_and_keeps_integrity():
    fields = {
        "student_name": "王五",
        "dept": "电子工程系",
        "education": "研一 · 3.9 · 信号处理",
        "projects": "项目A：负责算法实现",
        "awards_positions": "优秀学生干部\n担任课题组助教",
        "extras": "CET-6",
    }
    request = build_resume_request(fields)
    assert request["student_name"] == "王五"
    assert request["dept"] == "电子工程系"
    assert request["education"] == "研一 · 3.9 · 信号处理"
    # 任职语义归入 positions，奖项归入 awards
    assert "优秀学生干部" in request["awards"]
    assert any("助教" in position for position in request["positions"])
    assert request["format"] == "pdf"


@pytest.mark.asyncio
async def test_resume_polish_degrades_to_deterministic_without_llm(monkeypatch):
    # 测试环境无 LLM 凭据 → 必须降级确定性整理，绝不报错
    with SessionLocal() as db:
        reply, _ = await handle_resume_polish(
            db,
            latest_user="做过一些机器学习项目，主要是图像分类，参加了几个比赛",
            session_id="polish-test",
            student_id="student-test-4",
        )
    assert "整理后的简历" in reply
    assert "未使用生成式润色" in reply or "确定性整理" in reply
    # 降级文本不虚构内容：原文仍在
    assert "图像分类" in reply


@pytest.mark.asyncio
async def test_resume_polish_waits_for_paste_then_processes():
    with SessionLocal() as db:
        session_id = "polish-wait-test"
        student_id = "student-test-5"
        first, _ = await handle_resume_polish(
            db,
            latest_user="优化简历",
            session_id=session_id,
            student_id=student_id,
        )
        assert "请把你的简历原文粘贴给我" in first
        # 第二轮：粘贴内容 → 直接进入处理
        second, _ = await handle_resume_polish(
            db,
            latest_user="我的简历：做过网络安全的项目",
            session_id=session_id,
            student_id=student_id,
        )
        assert "整理后的简历" in second
        assert "网络安全的项目" in second


def test_parse_target_from_message_extracts_advisor():
    assert parse_target_from_message("针对张三老师的课题组优化简历") == "张三"
    assert parse_target_from_message("针对李四老师优化简历") == "李四"
    assert parse_target_from_message("针对这个科研助理岗位优化简历") == "这个科研助理岗位"
    assert parse_target_from_message("帮我改改简历") is None


@pytest.mark.asyncio
async def test_resume_targeted_without_target_asks_for_it():
    with SessionLocal() as db:
        reply, _ = await handle_resume_targeted(
            db,
            latest_user="定向优化",
            session_id="target-test",
            student_id="student-test-6",
        )
    assert "请告诉我要针对哪位导师" in reply


@pytest.mark.asyncio
async def test_resume_delivery_non_persistent_principal_is_honest():
    with SessionLocal() as db:
        session_id = "delivery-test"
        student_id = "student-test-7"
        principal = Principal(
            subject_id=student_id,
            channel="qxd",
            auth_session_id=None,
            persistent=False,
        )
        # 先走完采集，进入交付等待
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        fields = {
            "student_name": "赵六",
            "dept": "机械工程系",
            "education": "大三",
            "projects": "无",
            "awards_positions": "无",
            "extras": "邮箱 test@example.com",
        }
        for key, _ in FIELD_SEQUENCE:
            answer = fields.get(key) or "无"
            await handle_resume_build(
                db,
                latest_user=answer,
                session_id=session_id,
                student_id=student_id,
            )
        # 非持久主体请求 PDF 交付 → 诚实拒绝 + 保留文本
        reply, attachment = await handle_resume_build(
            db,
            latest_user=RESUME_DELIVERY_CONFIRMATION,
            session_id=session_id,
            student_id=student_id,
            principal=principal,
        )
        assert "不能生成可下载简历文件" in reply
        assert attachment is None
        # 交付完成后流程退出
        assert (
            get_dialogue_mode(db, session_id=session_id, student_id=student_id)
            is None
        )


@pytest.mark.asyncio
async def test_resume_delivery_persistent_principal_is_honest_about_platform_policy():
    """持久主体确认交付：平台短时公开转存仅支持匹配报告，简历 PDF 不走
    聊天附件——诚实说明并终局清状态，绝不尝试越权签发。"""
    from app.services.identity import Principal

    session_id = "resume-delivery-persistent"
    student_id = f"usr_{uuid.uuid4().hex}"
    principal = Principal(
        subject_id=student_id,
        channel="qxd",
        auth_session_id=None,
        persistent=True,
    )
    fields = {
        "student_name": "钱七",
        "dept": "自动化系",
        "education": "大三",
        "projects": "无人车项目；负责感知模块",
        "awards_positions": "无",
        "extras": "邮箱 test@example.com",
    }
    with SessionLocal() as db:
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        for key, _ in FIELD_SEQUENCE:
            answer = fields.get(key) or "无"
            await handle_resume_build(
                db,
                latest_user=answer,
                session_id=session_id,
                student_id=student_id,
            )
        reply, attachment = await handle_resume_build(
            db,
            latest_user=RESUME_DELIVERY_CONFIRMATION,
            session_id=session_id,
            student_id=student_id,
            principal=principal,
        )
        assert "仅支持匹配报告" in reply
        assert attachment is None
        # 投递确认是终局动作：诚实说明后同样清空状态
        assert (
            get_dialogue_mode(db, session_id=session_id, student_id=student_id)
            is None
        )


def test_clear_dialogue_state_is_idempotent():
    with SessionLocal() as db:
        clear_dialogue_state(
            db, session_id="absent-session", student_id="absent-student"
        )
        # 不抛异常即通过


@pytest.mark.asyncio
async def test_resume_build_prefills_from_dense_trigger_message():
    """触发消息一次给出大部分信息 → 智能预填，只问缺失字段（extras）。"""
    with SessionLocal() as db:
        session_id = "resume-prefill-trigger"
        student_id = "student-test-11"
        reply, _ = await handle_resume_build(
            db,
            latest_user=(
                "我叫张三，计算机科学与技术系，大三，GPA 3.8，"
                "做过一个 NLP 情感分类项目，拿了挑战杯二等奖"
            ),
            session_id=session_id,
            student_id=student_id,
        )
        assert "最后一步" in reply
        assert "第一步" not in reply  # 不重复问姓名
        state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
        assert state["fields"]["student_name"] == "张三"
        assert state["fields"]["dept"] == "计算机科学与技术系"
        assert state["fields"]["education"]
        assert "项目" in state["fields"]["projects"]
        assert "奖" in state["fields"]["awards_positions"]
        assert "extras" not in state["fields"]
        # 补上最后一项后直接生成简历
        final, _ = await handle_resume_build(
            db,
            latest_user="邮箱 test@example.com",
            session_id=session_id,
            student_id=student_id,
        )
        assert "简历初稿已生成" in final
        assert "张三" in final


@pytest.mark.asyncio
async def test_resume_build_collection_round_prefills_missing_fields():
    """采集轮回答姓名时顺带告知院系 → 院系被预填，跳过院系提问。"""
    with SessionLocal() as db:
        session_id = "resume-prefill-round"
        student_id = "student-test-12"
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        reply, _ = await handle_resume_build(
            db,
            latest_user="我叫李四，在自动化系",
            session_id=session_id,
            student_id=student_id,
        )
        assert "教育背景" in reply  # 直接问教育背景而非院系
        state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
        assert state["fields"]["student_name"] == "我叫李四，在自动化系"
        assert state["fields"]["dept"] == "自动化系"


@pytest.mark.asyncio
async def test_resume_build_vague_answer_skips_field():
    """宽泛回答（随便/都行）→ 该字段留空跳过，不追问。"""
    with SessionLocal() as db:
        session_id = "resume-vague-test"
        student_id = "student-test-13"
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        await handle_resume_build(
            db,
            latest_user="张三",
            session_id=session_id,
            student_id=student_id,
        )
        reply, _ = await handle_resume_build(
            db,
            latest_user="随便",
            session_id=session_id,
            student_id=student_id,
        )
        assert "教育背景" in reply
        state = get_dialogue_state(db, session_id=session_id, student_id=student_id)
        assert state["fields"]["dept"] == ""


def test_start_or_resume_build_promotes_one_shot_input():
    """引导文案明确支持一次性说完所有信息（减少来回轮次）。"""
    import asyncio

    with SessionLocal() as db:
        reply, _ = asyncio.run(
            handle_resume_build(
                db,
                latest_user="帮我从零写一份简历",
                session_id="resume-oneshot-prompt",
                student_id="student-test-14",
            )
        )
    assert "一次说完" in reply
    assert "一起发给我" in reply


@pytest.mark.asyncio
async def test_resume_finalize_shows_completeness_tips_when_key_fields_missing():
    """简历完整性体检：关键字段缺失时诚实提示，不虚构补写。"""
    with SessionLocal() as db:
        session_id = "resume-tips-test"
        student_id = "student-test-15"
        await handle_resume_build(
            db,
            latest_user="写简历",
            session_id=session_id,
            student_id=student_id,
        )
        answers = {
            "student_name": "孙八",
            "dept": "计算机科学与技术系",
            "education": "大三",
            "projects": "无",  # 关键缺失：科研经历
            "awards_positions": "无",
            "extras": "无",  # 关键缺失：联系方式
        }
        final = ""
        for key, _ in FIELD_SEQUENCE:
            reply, _ = await handle_resume_build(
                db,
                latest_user=answers[key],
                session_id=session_id,
                student_id=student_id,
            )
            final = reply
        assert "简历体检" in final
        assert "暂无科研/项目经历" in final
        assert "暂无联系方式" in final
        # 体检只是提示，不虚构内容
        assert "建议补充" in final


@pytest.mark.asyncio
async def test_resume_polish_attaches_job_req_when_target_is_recruitment(
    monkeypatch,
):
    """定向目标解析为岗位时，岗位公开要求进入润色提示词（不虚构）。"""
    from app.core.config import settings
    from app.services.llm import LLMCompletionResult
    from app.services.resume_dialogue import (
        resolve_recruitment_target as _real_resolve,
    )

    captured: list[list] = []

    def fake_result() -> LLMCompletionResult:
        return LLMCompletionResult(
            text='{"polished": "测试润色后的简历", "notes": ["已按岗位要求调整"]}',
            provider="test",
            model="test",
        )

    async def fake_llm(messages, *, timeout_seconds=None):
        captured.append(messages)
        return fake_result()

    monkeypatch.setattr(
        "app.services.resume_dialogue._llm_complete_result", fake_llm
    )
    # 模块级 settings 替换为带测试凭据的最小配置（llm_credentials 是只读
    # property，实例私有属性存在遮蔽无法直接注入）
    monkeypatch.setattr(
        "app.services.resume_dialogue.settings",
        types.SimpleNamespace(
            llm_credentials=(("glm", "secret"),),
            LLM_TIMEOUT=30,
            QXD_ATTACHMENTS_ENABLED=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.resume_dialogue.resolve_recruitment_target",
        lambda db, target, interests=None: {
            "recruit_id": "R001",
            "title": "计算机系 NLP 课题组招募科研助理",
            "type": "科研助理",
            "req": "熟悉 PyTorch，有 NLP 项目经验者优先",
            "major": "自然语言处理",
        },
    )
    with SessionLocal() as db:
        reply, _ = await handle_resume_polish(
            db,
            latest_user="做过情感分类项目，用了 PyTorch",
            session_id="polish-job-test",
            student_id="student-test-16",
            target="第1个",
        )
    assert "润色后的简历" in reply
    assert "已按岗位要求调整" in reply
    assert captured, "应调用 LLM"
    user_message = captured[0][-1].content
    assert "目标岗位公开核心要求" in user_message
    assert "熟悉 PyTorch，有 NLP 项目经验者优先" in user_message
    assert "计算机系 NLP 课题组招募科研助理" in user_message
