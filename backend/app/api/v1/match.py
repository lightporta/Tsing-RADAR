"""综合匹配路由（关键词 + 画像向量契合度 + Synergy）。"""

from fastapi import APIRouter

from app.schemas.advisor import MatchRequest
from app.services.data_loader import load_mentors
from app.services.llm import embed_text, portrait_to_text
from app.services.matching import match_mentors
from app.services.training import get_model_weights

router = APIRouter()


@router.post("/match")
async def match_mentor(req: MatchRequest):
    """升级版匹配：关键词基础分 + 画像向量契合度 + 六维 Synergy Score，输出 top 5。"""
    mentors = load_mentors()

    # 预计算画像向量（若有 portrait）
    portrait_vec = None
    if req.portrait:
        portrait_vec = await embed_text(portrait_to_text(req.portrait))

    # 预计算每名导师向量
    mentor_vecs = None
    if portrait_vec is not None:
        mentor_vecs = {}
        for m in mentors:
            txt = m.get("field", "") + " " + " ".join(m.get("tags", []))
            mentor_vecs[m.get("name", "")] = await embed_text(txt)

    result = match_mentors(
        mentors=mentors,
        interest=req.interest,
        portrait=req.portrait,
        weight=req.weight,
        portrait_vec=portrait_vec,
        mentor_vecs=mentor_vecs,
        model_weights=get_model_weights(),
        top_n=5,
    )
    return {"data": result}
