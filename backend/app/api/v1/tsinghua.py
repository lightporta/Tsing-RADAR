"""校内数据源接口（占位，对接清华校内网关）。

生产期需申请校内网关权限，替换 stub 实现。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/tsinghua/auth/verify")
def verify_student(token: str):
    """校验学生身份与权限（占位）。

    生产对接：GET /api/tsinghua/auth/verify?token={jwt}
    """
    if not token:
        return {"valid": False, "message": "缺少 token"}
    # 占位：任何非空 token 视为有效
    return {
        "valid": True,
        "student_id": "2023000000",
        "name": "测试同学",
        "department": "自动化系",
        "category": "本科生",
    }


@router.get("/tsinghua/lib/papers")
def lib_papers(author_id: str, years: int = 2):
    """获取导师指定年限内的论文列表（占位）。

    生产对接：GET /api/tsinghua/lib/papers?author_id={advisor_id}&years=2
    """
    return {
        "author_id": author_id,
        "years": years,
        "papers": [
            {"title": "（示例）面向大模型的分布式训练优化", "venue": "NeurIPS 2025", "year": 2025},
            {"title": "（示例）多模态感知与决策", "venue": "CVPR 2024", "year": 2024},
        ],
    }


@router.post("/internal/scrape/faculty")
def scrape_faculty(payload: dict):
    """院系师资爬虫触发（占位）。

    生产对接：POST /api/internal/scrape/faculty
    传入师资页面URL，异步返回抓取的导师数据。
    """
    url = payload.get("url", "")
    return {
        "status": "accepted",
        "url": url,
        "message": "爬虫任务已入队（占位），生产期对接 Scrapy + Playwright",
    }
