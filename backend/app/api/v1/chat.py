"""清小搭 OpenAI-compatible 平台入口。"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.core.config import settings
from app.core.deps import verify_admin
from app.core.qxd_auth import get_qxd_principal, verify_qxd_bearer
from app.schemas.advisor import LLMMessage
from app.schemas.qxd import (
    FileContentPart,
    ImageURLContentPart,
    InputAudioContentPart,
    QXDChatRequest,
    SodaAttachment,
    SodaExtension,
    TextContentPart,
)
from app.db.session import SessionLocal
from app.db.session import get_db
from app.services.artifact_delivery import (
    artifact_download_response,
    assert_qxd_delivery_ready,
    issue_delivery_grant,
    issue_radar_chart_token,
    redeem_delivery_token,
    redeem_radar_chart_token,
)
from app.services.artifact_generation import create_match_report_artifact
from app.services.chat_expression import (
    build_interview_fact_pack,
    render_interview_reply,
)
from app.services.interview import (
    InterviewAccessError,
    InterviewConflictError,
    InterviewNotFoundError,
    answer_session,
    confirmed_portrait,
    state_response,
    sync_user_transcript,
)
from app.services.match_application import (
    format_match_outcome,
    run_confirmed_match,
)
from app.services.mentor_score_governance import public_score_bundles
from app.services.radar_chart import (
    ADVISOR_TRAIT_COLOR,
    RADAR_DIMENSION_LABELS,
    TRAIT_KEYS,
    RadarSeries,
    build_radar_series_for_advisor,
    render_radar_svg,
)
from app.services.recruitment_public import (
    format_recruitment_digest,
    list_public_recruitments,
)
from app.services.qxd_media import (
    MediaFetchError,
    MediaSecurityError,
    MediaTooLargeError,
    SafeMediaFetcher,
)
from app.services.identity import Principal
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1")
media_fetcher = SafeMediaFetcher.from_settings()
logger = logging.getLogger("tsing_radar.qxd")
_REPORT_INTENTS = (
    "生成匹配报告",
    "导出匹配报告",
    "下载匹配报告",
)
_REPORT_DELIVERY_CONFIRMATION = "确认生成并通过清小搭附件交付"
_RADAR_INTENTS = (
    "雷达图",
    "查看雷达",
    "显示雷达",
    "看看雷达",
)
_RECRUITMENT_INTENTS = (
    "招募",
    "实习信息",
    "招生信息",
    "科研助理",
)
_SITE_HOME_URL = "https://www.tsingradar.com.cn"
_TRIAL_RESET_UTTERANCES = {
    "重新开始",
    "开始新访谈",
    "重置访谈",
    "restart interview",
}


@dataclass
class _TrialConversation:
    """进程内、短期、单人试聊状态；不代表可验证的终端用户身份。"""

    subject_id: str
    session_id: str
    created_monotonic: float
    last_seen_monotonic: float
    consumed_turns: int = 0


_trial_state: _TrialConversation | None = None
_trial_state_lock = threading.Lock()
_trial_request_lock = threading.Lock()


@dataclass(frozen=True)
class AgentReply:
    content: str
    attachments: tuple[SodaAttachment, ...] = ()
    reasoning: tuple[str, ...] = ()


def _reply_reasoning_steps(*, stage: str, attachments_count: int) -> tuple[str, ...]:
    """按业务阶段生成确定性的思考过程文案（不冒充模型推理）。

    帧序：role → reasoning… → content… → stop；reasoning 只出不入。
    """
    if attachments_count > 0:
        return ("正在准备文件…",)
    if stage == "matched":
        return (
            "正在检索匹配导师…",
            "正在核实证据与置信度…",
        )
    if stage == "recommend_ready":
        return ("正在读取已确认画像…",)
    return ("正在理解你的回答…", "正在更新访谈画像…")


def _reset_trial_state() -> None:
    """使旧随机试聊会话立即不可复用；不删除既有审计/访谈记录。"""
    global _trial_state
    with _trial_state_lock:
        _trial_state = None


def _reset_trial_state_for_tests() -> None:
    """仅供合同测试隔离进程内的单人试聊状态。"""
    _reset_trial_state()


def _is_platform_probe(
    request: QXDChatRequest,
    user_messages: list[str],
) -> bool:
    # 官方连接探测固定发送 max_tokens:1；探测绝不能污染真实试聊状态。
    return request.max_tokens == 1 and len(user_messages) == 1


def _safe_user_label(value: str | None) -> str:
    """只输出有密钥 HMAC 标签，绝不记录 OpenAI user 字段原值。"""
    if not value:
        return "absent"
    digest = hmac.new(
        settings.SESSION_HMAC_SECRET.encode("utf-8"),
        f"qxd-request-user:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"present:{digest[:12]}"


def _trial_scope(
    request: QXDChatRequest,
    user_messages: list[str],
) -> tuple[_TrialConversation, list[str]]:
    """返回随机试聊范围；无传输 request id 时不伪装正文幂等。"""
    global _trial_state
    if not settings.DEBUG:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="单人试聊兼容模式只允许本地调试环境",
        )
    now = time.monotonic()
    latest = user_messages[-1].strip().lower() if user_messages else ""
    reset_requested = latest in _TRIAL_RESET_UTTERANCES
    with _trial_state_lock:
        idle_expired = _trial_state is not None and (
            now - _trial_state.last_seen_monotonic
            > settings.QXD_TRIAL_IDLE_TTL_SECONDS
        )
        absolute_expired = _trial_state is not None and (
            now - _trial_state.created_monotonic
            > settings.QXD_TRIAL_ABSOLUTE_TTL_SECONDS
        )
        expired = idle_expired or absolute_expired
        if _trial_state is None or expired or reset_requested:
            _trial_state = _TrialConversation(
                subject_id=f"qtrial_{uuid.uuid4().hex}",
                session_id=str(uuid.uuid4()),
                created_monotonic=now,
                last_seen_monotonic=now,
            )
        else:
            _trial_state.last_seen_monotonic = now
        state = _trial_state
    effective_messages = [] if reset_requested else user_messages
    return state, effective_messages


def _complete_trial_request(
    state: _TrialConversation,
    *,
    consumed_answer: bool,
) -> None:
    now = time.monotonic()
    with _trial_state_lock:
        if _trial_state is not state:
            raise RuntimeError("试聊会话代际已变化，拒绝迟到提交")
        if consumed_answer:
            state.consumed_turns += 1
        state.last_seen_monotonic = now


def _usage() -> dict[str, int]:
    """当前无统一 tokenizer，按官方要求用 0 表示无法准确统计。"""
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


async def _prepare_llm_messages(request: QXDChatRequest) -> list[LLMMessage]:
    prepared: list[LLMMessage] = []
    media_parts = 0
    total_bytes = 0

    for message in request.messages:
        if message.role == "tool":
            continue
        if isinstance(message.content, str):
            prepared.append(LLMMessage(role=message.role, content=message.content))
            continue

        text_parts: list[str] = []
        for part in message.content:
            if isinstance(part, TextContentPart):
                text_parts.append(part.text)
                continue

            # Reject every non-text part before touching the resolver or HTTP
            # transport. This inbound capability is independent from outbound
            # signed report delivery.
            if not settings.QXD_REMOTE_MEDIA_FETCH_ENABLED:
                raise MediaFetchError("清小搭远程媒体输入当前未启用")

            media_parts += 1
            if media_parts > settings.QXD_MAX_MEDIA_PARTS:
                raise MediaFetchError("单次请求的多模态附件数量过多")
            remaining_bytes = settings.QXD_MEDIA_MAX_TOTAL_BYTES - total_bytes
            if remaining_bytes <= 0:
                raise MediaTooLargeError("单次请求的附件总大小超过限制")

            if isinstance(part, ImageURLContentPart):
                fetched = await media_fetcher.fetch(
                    part.image_url.url,
                    "image",
                    max_bytes=remaining_bytes,
                )
                label = "图片"
            elif isinstance(part, InputAudioContentPart):
                fetched = await media_fetcher.fetch(
                    part.input_audio.url,
                    "audio",
                    max_bytes=remaining_bytes,
                )
                label = f"音频（{part.input_audio.format}）"
            elif isinstance(part, FileContentPart):
                if part.file.file_id:
                    text_parts.append(
                        f"[平台文件 {part.file.filename} 使用 file_id 引用，"
                        "当前服务未配置 file_id 内容解析]"
                    )
                    continue
                fetched = await media_fetcher.fetch(
                    part.file.url or "",
                    "file",
                    filename=part.file.filename,
                    max_bytes=remaining_bytes,
                )
                label = f"文件 {part.file.filename}"
            else:  # pragma: no cover - Pydantic 判别联合已封闭
                continue

            total_bytes += fetched.size
            if total_bytes > settings.QXD_MEDIA_MAX_TOTAL_BYTES:
                raise MediaTooLargeError("单次请求的附件总大小超过限制")
            text_parts.append(
                f"[已安全获取{label}：{fetched.content_type}，{fetched.size} 字节；"
                "当前模型未启用二进制内容解析]"
            )

        prepared.append(
            LLMMessage(role=message.role, content="\n".join(text_parts).strip())
        )

    return prepared


async def generate_agent_reply(
    request: QXDChatRequest,
    principal: Principal | None = None,
) -> AgentReply:
    """复用访谈与匹配应用服务；协议层不复制排序逻辑。"""
    messages = await _prepare_llm_messages(request)
    user_messages = [
        message.content for message in messages if message.role == "user"
    ]
    resolved_principal = principal or Principal(
        subject_id=f"qreq_{uuid.uuid4().hex}",
        channel="qxd",
        auth_session_id=None,
        persistent=False,
    )
    probe = _is_platform_probe(request, user_messages)
    trial_enabled = (
        settings.QXD_TRIAL_SINGLE_USER_MODE
        and not resolved_principal.persistent
        and not probe
    )
    role_counts = {
        role: sum(1 for message in messages if message.role == role)
        for role in ("system", "user", "assistant", "tool")
    }
    logger.info(
        "qxd_request_metadata persistent=%s trial=%s probe=%s "
        "stream=%s roles=%s user_field=%s",
        resolved_principal.persistent,
        trial_enabled,
        probe,
        request.stream,
        role_counts,
        _safe_user_label(request.user),
    )

    trial_lock_acquired = False
    trial_state: _TrialConversation | None = None
    effective_user_messages = user_messages
    try:
        if trial_enabled:
            trial_lock_acquired = _trial_request_lock.acquire(blocking=False)
            if not trial_lock_acquired:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="单人试聊已有请求正在处理，请稍后重试",
                )
            trial_state, effective_user_messages = _trial_scope(
                request,
                user_messages,
            )

        if resolved_principal.persistent and request.sessionId:
            # 网关 sessionId（同一通对话每轮相同）优先作为会话记忆键；
            # 与终端用户主体绑定派生，不同主体即使传相同 sessionId 也不会互串。
            session_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    (
                        "tsing-radar:qxd-session:"
                        f"{resolved_principal.subject_id}:{request.sessionId}"
                    ),
                )
            )
            student_id = resolved_principal.subject_id
        elif resolved_principal.persistent:
            conversation_key = (request.user or "default").strip() or "default"
            session_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    (
                        "tsing-radar:qxd-interview:"
                        f"{resolved_principal.subject_id}:{conversation_key}"
                    ),
                )
            )
            student_id = resolved_principal.subject_id
        elif trial_state is not None:
            session_id = trial_state.session_id
            student_id = trial_state.subject_id
        else:
            # 未验证终端用户 claim 且未显式启用单人试聊兼容时，每请求独立。
            session_id = str(uuid.uuid4())
            student_id = resolved_principal.subject_id

        db = SessionLocal()
        pending_attachments: list[SodaAttachment] = []
        reply_stage = "interviewing"
        try:
            if trial_state is not None and trial_state.consumed_turns > 0:
                session = answer_session(
                    db,
                    session_id=session_id,
                    answer=effective_user_messages[-1],
                    student_id=student_id,
                )
            else:
                session = sync_user_transcript(
                    db,
                    session_id=session_id,
                    student_id=student_id,
                    user_messages=effective_user_messages,
                )
            state = state_response(session)
            visible = state.assistant_message
            # 表达层：LLM 基于确定性事实包整段重写；任何失败降级回固定模板。
            # 诚实性红线：画像确认门（needs_confirmation）与匹配结果
            # （recommend_ready）不增强，保持确定性原文（确认指令/匹配证据）。
            # 推荐结果优先短路，避免对非完整状态桩的字段依赖。
            if not probe and not state.recommend_ready and not state.needs_confirmation:
                expression = await render_interview_reply(
                    build_interview_fact_pack(
                        state,
                        user_messages[-1].strip() if user_messages else "",
                    )
                )
                if expression.text:
                    visible = expression.text
            if state.recommend_ready:
                outcome = run_confirmed_match(
                    db,
                    session_id=session_id,
                    student_id=student_id,
                )
                try:
                    portrait = confirmed_portrait(
                        db,
                        session_id=session_id,
                        student_id=student_id,
                    )
                except (
                    InterviewNotFoundError,
                    InterviewAccessError,
                    InterviewConflictError,
                ):
                    portrait = None
                reply_stage = (
                    "matched" if outcome.status == "matched" else "recommend_ready"
                )
                visible = format_match_outcome(outcome, profile=portrait)
                latest_user = user_messages[-1].strip() if user_messages else ""
                earlier_users = user_messages[:-1]
                if any(intent in latest_user for intent in _REPORT_INTENTS):
                    if not settings.QXD_ATTACHMENTS_ENABLED:
                        visible = "清小搭附件交付当前未启用；可继续查看文本匹配结果。"
                    elif not resolved_principal.persistent:
                        visible = (
                            "当前请求没有可验证、稳定的终端用户身份，因此不能生成"
                            "可下载附件。你仍可查看本轮文本匹配结果。"
                        )
                    else:
                        visible = (
                            "我可以生成一份 PDF 匹配报告。报告会包含已确认画像、"
                            "当前匹配结果或诚实空数据原因，并通过一个短时签名 URL "
                            "交给清小搭转存；不会包含用户上传原件，也不会发送给导师。"
                            f"\n\n如同意，请单独回复“{_REPORT_DELIVERY_CONFIRMATION}”。"
                        )
                elif any(intent in latest_user for intent in _RADAR_INTENTS):
                    radar_text, radar_attachment = _radar_intent_reply(
                        outcome,
                        latest_user=latest_user,
                    )
                    visible = radar_text
                    if radar_attachment is not None:
                        pending_attachments.append(radar_attachment)
                elif any(intent in latest_user for intent in _RECRUITMENT_INTENTS):
                    records, _withheld = list_public_recruitments(db)
                    visible = format_recruitment_digest(records, profile=portrait)
                elif latest_user == _REPORT_DELIVERY_CONFIRMATION:
                    if not settings.QXD_ATTACHMENTS_ENABLED:
                        visible = "清小搭附件交付当前未启用；未生成或公开任何文件。"
                    elif not any(
                        any(intent in turn for intent in _REPORT_INTENTS)
                        for turn in earlier_users
                    ):
                        visible = "请先回复“生成匹配报告”，查看交付范围后再确认。"
                    elif not resolved_principal.persistent:
                        visible = (
                            "当前请求没有可验证、稳定的终端用户身份，"
                            "不能生成可下载附件。"
                        )
                    else:
                        assert_qxd_delivery_ready()
                        request_digest = hashlib.sha256(
                            json.dumps(
                                user_messages,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        document, report_outcome = create_match_report_artifact(
                            db,
                            owner_subject_id=student_id,
                            channel="qxd",
                            session_id=session_id,
                            output_format="pdf",
                            confirmed=True,
                            idempotency_key=f"qxd-report:{request_digest}",
                        )
                        issued = issue_delivery_grant(
                            db,
                            document=document,
                            principal=resolved_principal,
                            audience="qxd_platform",
                            confirmed=True,
                            idempotency_key=f"qxd-grant:{request_digest}",
                        )
                        attachment = SodaAttachment(
                            fileUrl=issued.download_url,
                            fileName=document.original_name,
                            fileType="pdf",
                            mimeType=document.media_type,
                            fileSize=document.size_bytes,
                            expiresAt=issued.expires_at,
                        )
                        visible = (
                            "匹配报告已生成并通过短时签名链接交给清小搭转存。"
                            f"\n\n{report_outcome.message}"
                        )
                        return AgentReply(
                            content=visible,
                            attachments=(attachment,),
                            reasoning=_reply_reasoning_steps(
                                stage=reply_stage, attachments_count=1
                            ),
                        )
                if (
                    outcome.status == "matched"
                    and outcome.items
                    and not pending_attachments
                    and not any(
                        intent in latest_user
                        for intent in (
                            _RADAR_INTENTS
                            + _RECRUITMENT_INTENTS
                            + _REPORT_INTENTS
                        )
                    )
                    and latest_user != _REPORT_DELIVERY_CONFIRMATION
                    and _radar_available_for_items(outcome.items)
                ):
                    visible += (
                        "\n\n需要雷达图吗？回复「雷达图」查看首位候选，"
                        "或「雷达图 + 姓名」指定导师。"
                    )
        finally:
            db.close()

        reply = AgentReply(
            content=visible,
            attachments=tuple(pending_attachments),
            reasoning=_reply_reasoning_steps(
                stage=reply_stage,
                attachments_count=len(pending_attachments),
            ),
        )
        if trial_state is not None:
            _complete_trial_request(
                trial_state,
                consumed_answer=bool(effective_user_messages),
            )
        return reply
    finally:
        if trial_lock_acquired:
            _trial_request_lock.release()


def _radar_available_for_items(items: list[dict]) -> bool:
    """匹配候选中是否至少有一位导师具有已审核六维评分（用于自动提示）。"""
    try:
        bundles, _status = public_score_bundles()
    except Exception:  # noqa: BLE001 —— 评分数据异常时按"无雷达"处理，不影响对话主链路
        logger.exception("radar_bundle_lookup_failed")
        return False
    return any(str(item.get("advisor_id")) in bundles for item in items)


def _select_radar_item(
    items: list[dict], latest_user: str, bundles: dict[str, dict]
) -> dict | None:
    """优先返回用户点名（姓名包含在消息中）且有评分数据的候选，否则首位有数据者。"""
    for item in items:
        name = str(item.get("name") or "")
        if name and name in latest_user and str(item.get("advisor_id")) in bundles:
            return item
    for item in items:
        if str(item.get("advisor_id")) in bundles:
            return item
    return None


def _radar_text_table(name: str, values_by_key: dict[str, float]) -> str:
    lines = [f"{name} 六维评分（已审核，满分 100）："]
    for key in TRAIT_KEYS:
        value = values_by_key.get(key)
        if value is None:
            lines.append(f"- {RADAR_DIMENSION_LABELS[key]}：暂无已审核评分")
        else:
            lines.append(f"- {RADAR_DIMENSION_LABELS[key]}：{value:.0f}")
    return "\n".join(lines)


def _radar_intent_reply(
    outcome,
    *,
    latest_user: str,
) -> tuple[str, SodaAttachment | None]:
    """雷达图意图处理：有已审核评分则发 image 附件，否则诚实空态 + 文本表格。"""
    items = outcome.items or []
    if not items:
        return (
            "当前匹配结果为空，暂无可展示雷达图的导师。可以先检查画像或匹配条件。"
            if outcome.status == "no_match"
            else outcome.message,
            None,
        )
    try:
        bundles, status = public_score_bundles()
    except Exception:  # noqa: BLE001 —— 评分数据异常时走诚实空态
        logger.exception("radar_bundle_lookup_failed")
        bundles, status = {}, {}

    item = _select_radar_item(items, latest_user, bundles)
    if item is None:
        first = items[0]
        name = str(first.get("name") or "该导师")
        values = {}
        return (
            "暂无候选导师的已审核六维评分，不能诚实地绘制雷达图"
            "（评分门控状态：未开放或未覆盖）。\n\n"
            f"{_radar_text_table(name, values)}\n\n"
            f"交互式雷达图与完整证据 👉 {_SITE_HOME_URL}",
            None,
        )

    advisor_id = str(item.get("advisor_id"))
    name = str(item.get("name") or advisor_id)
    series = build_radar_series_for_advisor(advisor_id, bundles)
    if series is None:
        return (
            f"{name} 暂无完整的已审核六维评分，不伪造雷达图。\n\n"
            f"交互式雷达图与完整证据 👉 {_SITE_HOME_URL}",
            None,
        )
    if not settings.QXD_ATTACHMENTS_ENABLED:
        release_note = (
            f"样本来源：已审核评分发布 v{status.get('release_version', '?')}"
            if status.get("release_version")
            else "样本来源：已审核评分发布"
        )
        return (
            "雷达图附件当前未启用；文本版六维数据如下。\n\n"
            f"{_radar_text_table(name, dict(zip(TRAIT_KEYS, series.values)))}\n\n"
            f"{release_note}\n交互式雷达图 👉 {_SITE_HOME_URL}",
            None,
        )
    try:
        assert_qxd_delivery_ready()
    except HTTPException as exc:
        logger.warning("radar_delivery_not_ready status=%s", exc.status_code)
        return (
            "雷达图附件交付尚未配置公网地址；文本版六维数据如下。\n\n"
            f"{_radar_text_table(name, dict(zip(TRAIT_KEYS, series.values)))}\n\n"
            f"交互式雷达图 👉 {_SITE_HOME_URL}",
            None,
        )
    token, expires_at = issue_radar_chart_token(advisor_id)
    attachment = SodaAttachment(
        fileUrl=f"{settings.PUBLIC_BASE_URL}/v1/radar/{token}",
        fileName=f"导师雷达图_{name}.svg",
        fileType="image",
        mimeType="image/svg+xml",
        expiresAt=expires_at,
    )
    others = [
        str(other.get("name") or "")
        for other in items
        if other is not item and str(other.get("advisor_id")) in bundles
    ]
    extra = (
        f"\n其他候选也可查看：回复「雷达图 {'、'.join(others[:2])}」。"
        if others
        else ""
    )
    text = (
        f"已生成 {name} 的导师特质雷达图（已审核评分，短时签名链接）：\n"
        "- 六维：学术敏锐度、人脉资源、指导意愿、性格包容度、经费实力、产出效率"
        f"{extra}\n\n"
        f"完整对比与交互式雷达图 👉 {_SITE_HOME_URL}"
    )
    return text, attachment


@router.get("/radar/{token}")
def download_radar_chart(token: str):
    """无状态雷达图端点：令牌即凭证（HMAC 签名 + 短时过期）。

    雷达图由已发布的公开评分确定性渲染，不落对象存储、不经过私有文档管线。
    """
    advisor_id = redeem_radar_chart_token(token)
    series = build_radar_series_for_advisor(advisor_id)
    if series is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该导师暂无已审核六维评分",
        )
    svg = _render_radar_svg_cached(advisor_id, tuple(series.values))
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@functools.lru_cache(maxsize=64)
def _render_radar_svg_cached(advisor_id: str, values: tuple[float, ...]) -> str:
    series = RadarSeries(
        name="导师特质（已审核评分）",
        values=list(values),
        color=ADVISOR_TRAIT_COLOR,
    )
    return render_radar_svg(
        series=[series],
        title="导师特质雷达图（已审核评分）",
        sample_note="社区与官方目录数据请以网站为准；样本量与时间窗见详情页",
    )


@router.get("/attachments/{token}")
def download_qxd_attachment(
    token: str,
    db: Session = Depends(get_db),
):
    """无平台 Bearer 的短时 GET，只能兑换已确认生成的报告授权。"""
    redeemed = redeem_delivery_token(
        db,
        token=token,
        audience="qxd_platform",
        principal=None,
    )
    return artifact_download_response(redeemed)


def _x_soda_payload(reply: AgentReply) -> dict | None:
    if not reply.attachments:
        return None
    extension = SodaExtension(attachments=list(reply.attachments))
    return extension.model_dump(mode="json", exclude_none=True)


def _nonstream_payload(
    *,
    completion_id: str,
    created: int,
    model: str,
    reply: AgentReply,
) -> dict:
    payload = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply.content},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(),
    }
    x_soda = _x_soda_payload(reply)
    if x_soda is not None:
        payload["x_soda"] = x_soda
    return payload


def _stream_frame(
    *,
    completion_id: str,
    created: int,
    model: str,
    delta: dict,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    x_soda: dict | None = None,
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage is not None:
        payload["usage"] = usage
    if x_soda is not None:
        payload["x_soda"] = x_soda
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/models", dependencies=[Depends(verify_qxd_bearer)])
async def list_models() -> dict:
    """返回平台探测所需的模型列表。"""
    return {
        "object": "list",
        "data": [
            {
                "id": "tsing-radar",
                "object": "model",
                "owned_by": "tsing-radar",
            }
        ],
    }


@router.post("/chat/completions", dependencies=[Depends(verify_qxd_bearer)])
async def chat(
    request: QXDChatRequest,
    principal: Principal = Depends(get_qxd_principal),
    trial_gateway_marker: str | None = Header(
        default=None,
        alias="X-Tsing-Radar-QXD1-Trial",
    ),
):
    """同时支持非流式 JSON 与严格顺序的 OpenAI-compatible SSE。"""
    if (
        settings.QXD_TRIAL_SINGLE_USER_MODE
        and not principal.persistent
        and not hmac.compare_digest(
            trial_gateway_marker or "",
            "qxd1-single-user-trial",
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="单人试聊兼容模式只接受本地 QXD1 临时网关请求",
        )
    try:
        reply = await asyncio.wait_for(
            generate_agent_reply(request, principal),
            timeout=settings.QXD_REQUEST_TIMEOUT_SECONDS,
        )
    except MediaSecurityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="多模态 URL 未通过安全校验",
        ) from exc
    except MediaTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="多模态附件超过大小限制",
        ) from exc
    except MediaFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="多模态附件无法获取",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="智能体处理超时",
        ) from exc

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = request.model or "tsing-radar"

    if not request.stream:
        return JSONResponse(
            _nonstream_payload(
                completion_id=completion_id,
                created=created,
                model=model,
                reply=reply,
            )
        )

    async def sse_stream():
        yield _stream_frame(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={"role": "assistant"},
        )
        # 思考过程帧（只出不入；确定性阶段文案，不冒充模型推理）
        for step in reply.reasoning:
            yield _stream_frame(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={"reasoning": step},
            )
            await asyncio.sleep(0)
        for index in range(0, len(reply.content), 8):
            yield _stream_frame(
                completion_id=completion_id,
                created=created,
                model=model,
                delta={"content": reply.content[index : index + 8]},
            )
            await asyncio.sleep(0)
        yield _stream_frame(
            completion_id=completion_id,
            created=created,
            model=model,
            delta={},
            finish_reason="stop",
            usage=_usage(),
            x_soda=_x_soda_payload(reply),
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/internal/trial-reset",
    dependencies=[Depends(verify_admin)],
    include_in_schema=False,
)
async def reset_trial_conversation() -> dict[str, str]:
    """供本机隧道生命周期脚本使旧的进程内试聊代际立即失效。"""
    _reset_trial_state()
    return {"status": "reset"}
