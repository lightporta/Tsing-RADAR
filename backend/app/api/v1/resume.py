"""[PATCH] 简历生成与投递路由。

修改点：
- resume_submit 注入 get_current_student 鉴权依赖
- resume_generate 响应增加 x_soda.attachments 字段（清小搭多模态附件协议）
"""

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import get_current_student
from app.schemas.advisor import LLMMessage
from app.schemas.resume import ResumeGenerateRequest, ResumeSubmitRequest
from app.schemas.qxd import Attachment
from app.services.llm import llm_complete
from app.services.memory_store import APPLICATIONS_STORE

router = APIRouter()


@router.post("/resume/generate")
async def resume_generate(req: ResumeGenerateRequest):
    """调用 LLM 生成打磨简历正文；无 key 用模板拼接。

    [PATCH] 响应增加 x_soda.attachments 字段，支持清小搭多模态附件协议。
    当生成简历文本后，自动构造附件元数据，清小搭前端可据此展示下载入口。
    """
    projects_text = "\n".join(
        [f"- {p.get('name', p) if isinstance(p, dict) else p}" for p in req.projects] or ["（暂无项目）"]
    )
    awards_text = "\n".join([f"- {a}" for a in req.awards] or ["（暂无奖项）"])
    positions_text = "\n".join([f"- {p}" for p in req.positions] or ["（暂无职务）"])
    target_line = f"（目标导师：{req.target_advisor}）" if req.target_advisor else ""
    target_section = f"\n\n【目标导师】\n{target_line}" if req.target_advisor else ""

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
                "title": f"{req.student_name}-个人简历",
                # [PATCH] x_soda.attachments 多模态附件
                "x_soda": {
                    "attachments": [
                        Attachment(
                            fileUrl=f"/api/resume/download?title={req.student_name}-个人简历",
                            fileName=f"{req.student_name}-个人简历.txt",
                            fileType="txt",
                            mimeType="text/plain",
                        ).model_dump()
                    ]
                },
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
        "title": f"{req.student_name}-个人简历",
        # [PATCH] x_soda.attachments 多模态附件
        "x_soda": {
            "attachments": [
                Attachment(
                    fileUrl=f"/api/resume/download?title={req.student_name}-个人简历",
                    fileName=f"{req.student_name}-个人简历.txt",
                    fileType="txt",
                    mimeType="text/plain",
                ).model_dump()
            ]
        },
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
