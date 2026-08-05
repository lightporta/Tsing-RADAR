"""[PATCH] 简历生成与投递路由。

修改点：
- resume_submit 注入 get_current_student 鉴权依赖
- resume_generate 响应增加 x_soda.attachments 字段（清小搭多模态附件协议）
"""

import uuid

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import get_current_student
from app.schemas.advisor import LLMMessage
from app.schemas.resume import ResumeGenerateRequest, ResumeSubmitRequest
from app.schemas.qxd import Attachment
from app.services.llm import llm_complete
from app.services.memory_store import APPLICATIONS_STORE

router = APIRouter()


def _attachment(title: str, owner_subject: str) -> dict:
    """构造清小搭多模态附件元数据。

    [v2.2] 附件协议硬约束：清小搭必须能从真实 HTTPS 地址取得附件。
    未配置 PUBLIC_BASE_URL 时，附件标记为「不可交付」（downloadable=False），
    fileUrl 留空，不得降级为测试域或相对路径。配置后，fileUrl 指向
    /api/storage/download 的签名令牌 URL（需真实对象存储路由支持）。
    """
    if not settings.PUBLIC_BASE_URL:
        return {
            "downloadable": False,
            "reason": "未配置 PUBLIC_BASE_URL，附件不可交付（不降级为测试域）",
        }
    from urllib.parse import quote
    from app.services.signing import issue_download_token

    # 占位 object_id（真实场景应来自已上传对象的 id）
    object_id = f"resume-{owner_subject}-{uuid.uuid4().hex[:8]}"
    token = issue_download_token(object_id)
    return Attachment(
        fileUrl=f"{settings.PUBLIC_BASE_URL}/api/storage/download?token={token}",
        fileName=f"{title}.txt",
        fileType="txt",
        mimeType="text/plain",
    ).model_dump()


@router.post("/resume/generate")
async def resume_generate(
    req: ResumeGenerateRequest,
    owner_subject: str = Depends(get_current_student),
):
    """调用 LLM 生成打磨简历正文；无 key 用模板拼接。

    [PATCH] 响应增加 x_soda.attachments 字段，支持清小搭多模态附件协议。
    [v2.2] 附件 fileUrl 受 PUBLIC_BASE_URL 门禁：未配置公网基址时返回
    「不可交付」，不降级为测试域（见 _attachment）。
    """
    projects_text = "\n".join(
        [f"- {p.get('name', p) if isinstance(p, dict) else p}" for p in req.projects] or ["（暂无项目）"]
    )
    awards_text = "\n".join([f"- {a}" for a in req.awards] or ["（暂无奖项）"])
    positions_text = "\n".join([f"- {p}" for p in req.positions] or ["（暂无职务）"])
    target_line = f"（目标导师：{req.target_advisor}）" if req.target_advisor else ""
    target_section = f"\n\n【目标导师】\n{target_line}" if req.target_advisor else ""
    title = f"{req.student_name}-个人简历"

    # 尝试 LLM 生成
    if req.target_advisor:
        prompt = (
            f"请为 {req.student_name}（{req.dept}）生成一份面向导师 {req.target_advisor} 的个人简历。"
            f"项目经历：{projects_text}，获奖：{awards_text}，职务：{positions_text}。"
            "请润色为学术风格，突出与导师方向的契合点。"
        )
        messages = [LLMMessage(role="user", content=prompt)]
        polished = await llm_complete(messages)
        if polished:
            return {
                "polished_text": polished,
                "title": title,
                "x_soda": {"attachments": [_attachment(title, owner_subject)]},
            }

    # 模板兜底
    template = (
        f"{req.student_name} | {req.dept} | {req.email} | {req.phone}\n\n"
        f"【项目经历】\n{projects_text}\n\n"
        f"【获奖荣誉】\n{awards_text}\n\n"
        f"【担任职务】\n{positions_text}\n"
        f"{target_section}"
    )
    return {
        "polished_text": template,
        "title": title,
        "x_soda": {"attachments": [_attachment(title, owner_subject)]},
    }


@router.post("/resume/submit")
def resume_submit(
    req: ResumeSubmitRequest,
    # [PATCH] 注入身份校验依赖
    student_id: str = Depends(get_current_student),
):
    """投递简历至招募方（内存存储）。

    [PATCH] 添加 get_current_student 鉴权依赖。
    """
    app_id = f"app_{uuid.uuid4().hex[:8]}"
    APPLICATIONS_STORE.append(
        {
            "app_id": app_id,
            "recruit_id": req.recruit_id,
            "student_id": req.student_id,
            "resume_id": req.resume_id,
            "status": "待处理",
        }
    )
    return {"app_id": app_id, "status": "待处理"}
