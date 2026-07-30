"""[PATCH] 招募信息路由。

修改点：
- GET /recruitments 响应从裸 list 改为 { data: [...] } 包装
- POST /recruitments 注入 get_current_student 鉴权依赖
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends

from app.core.deps import get_current_student
from app.schemas.recruitment import RecruitmentCreateRequest
from app.services.data_loader import load_mentors
from app.services.memory_store import RECRUITMENTS_STORE

router = APIRouter()


@router.get("/recruitments")
def list_recruitments(urgent: Optional[bool] = None):
    """聚合所有导师招募信息；?urgent=true 只返回急招。

    [PATCH] 响应从裸 list 改为 { data: [...] }，与前端 { data: RecruitmentItem[] } 匹配。
    """
    result = []
    # 1) 来自 mentors.json 的静态招募
    for m in load_mentors():
        for r in m.get("recruitments", []) or []:
            if urgent is True and not r.get("is_urgent", False):
                continue
            result.append(
                {
                    "recruit_id": f"static_{m.get('name', '')}_{r.get('title', '')[:6]}",
                    "publisher_name": m.get("name", ""),
                    "publisher_type": "advisor",
                    "type": r.get("type", ""),
                    "title": r.get("title", ""),
                    "req": r.get("req", ""),
                    "major": r.get("major", ""),
                    "deadline": r.get("deadline", ""),
                    "is_urgent": r.get("is_urgent", False),
                    "dept": m.get("dept", ""),
                }
            )

    # 2) 内存中 POST 发布的招募
    for r in RECRUITMENTS_STORE:
        if urgent is True and not r.get("is_urgent", False):
            continue
        result.append(r)

    # [PATCH] 包装为 { data: [...] }
    return {"data": result}


@router.post("/recruitments")
def publish_recruitment(
    req: RecruitmentCreateRequest,
    # [PATCH] 注入身份校验依赖
    student_id: str = Depends(get_current_student),
):
    """发布招募（内存存储）。publisher_id 视为导师名，自动查表补全 dept/type。

    [PATCH] 添加 get_current_student 鉴权依赖。
    """
    mentor = next((m for m in load_mentors() if m.get("name") == req.publisher_id), None)
    dept = mentor.get("dept", "") if mentor else ""
    publisher_name = mentor.get("name", req.publisher_id) if mentor else req.publisher_id

    recruit_id = f"pub_{uuid.uuid4().hex[:8]}"
    record = {
        "recruit_id": recruit_id,
        "publisher_id": req.publisher_id,
        "publisher_name": publisher_name,
        "publisher_type": "advisor",
        "type": req.type,
        "title": req.title,
        "req": req.req,
        "major": req.major,
        "deadline": req.deadline,
        "is_urgent": req.is_urgent,
        "dept": dept,
    }
    RECRUITMENTS_STORE.append(record)
    return {"recruit_id": recruit_id, "status": "published"}
