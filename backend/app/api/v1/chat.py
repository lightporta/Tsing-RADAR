"""清小搭兼容的对话接口（v1/chat/completions）。"""

import json
import random
import re

from fastapi import APIRouter

from app.schemas.advisor import MatchRequest
from app.services.data_loader import load_mentors
from app.services.matching import keyword_score

router = APIRouter()


@router.get("/v1/models")
def list_models():
    """返回模型列表（清小搭兼容）。"""
    return {
        "object": "list",
        "data": [
            {"id": "tsing-radar-v1", "object": "model"},
            {"id": "tsing-radar-v2", "object": "model"},
        ],
    }


@router.post("/v1/chat/completions")
def chat(req: MatchRequest):
    """清小搭兼容接口：保留关键词匹配。"""
    user_input = req.interest.lower().strip()
    keywords = re.split(r"[\s,，、]+", user_input)
    mentors = load_mentors()
    matched = [m for m in mentors if keyword_score(m, keywords) > 0]
    # 不足 5 条随机补充
    pool = [x for x in mentors if x not in matched]
    random.shuffle(pool)
    matched += pool[: max(0, 5 - len(matched))]
    matched = matched[:5]
    return {
        "choices": [
            {"message": {"role": "assistant", "content": json.dumps(matched, ensure_ascii=False)}}
        ]
    }
