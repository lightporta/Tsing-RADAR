"""简历生成与投递路由。"""

import uuid

from fastapi import APIRouter

from app.schemas.advisor import LLMMessage
from app.schemas.resume import ResumeGenerateRequest, ResumeSubmitRequest
from app.services.llm import llm_complete
from app.services.memory_store import APPLICATIONS_STORE

router = APIRouter()


@router.post("/resume/generate")
async def resume_generate(req: ResumeGenerateRequest):
    """调用 LLM 生成打磨简历正文；无 key 用模板拼接。"""
    projects_text = "\n".join(
        [f"- {p.get('name', p) if isinstance(p, dict) else p}" for p in req.projects] or ["（暂无项目）"]
    )
    awards_text = "\n".join([f"- {a}" for a in req.awards] or ["（暂无奖项）"])
    positions_text = "\n".join([f"- {p}" for p in req.positions] or ["（暂无职务）"])
    target_line = f"（目标导师：{req.target_advisor}）" if req.target_advisor else ""

    if req.target_advisor:
        target_section = f"\n【投递目标】{req.target_advisor}\n"
    else:
        target_section = ""

    # 尝试 LLM 打磨
    polished = await llm_complete(
        [
            LLMMessage(
                role="user",
                content=(
                    f"请把以下学生信息打磨成一份简洁有力的中文简历正文（用于申请清华导师{target_line}），"
                    f"包含教育背景、项目经历、获奖、担任职务。姓名：{req.student_name}，"
                    f"院系：{req.dept}，邮箱：{req.email}，电话：{req.phone}。\n"
                    f"项目经历：\n{projects_text}\n获奖：\n{awards_text}\n职务：\n{positions_text}"
                ),
            )
        ]
    )
    if polished:
        return {"polished_text": polished, "title": f"{req.student_name}-个人简历"}

    # 模板兜底
    template = (
        f"{req.student_name} | {req.dept} | {req.email} | {req.phone}\n\n"
        f"【项目经历】\n{projects_text}\n\n"
        f"【获奖荣誉】\n{awards_text}\n\n"
        f"【担任职务】\n{positions_text}\n"
        f"{target_section}"
    )
    return {"polished_text": template, "title": f"{req.student_name}-个人简历"}


@router.post("/resume/submit")
def resume_submit(req: ResumeSubmitRequest):
    """投递简历至招募方（内存存储）。"""
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
