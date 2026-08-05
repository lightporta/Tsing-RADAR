"""校内数据源接口（占位，对接清华校内网关）。

生产期需申请校内网关权限，替换 stub 实现。
"""

from fastapi import APIRouter, HTTPException

from app.services.security import UnsafeURL, validate_public_url

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

    [v2.2] 入参 URL 必须通过 validate_public_url 形状校验
    （必须 HTTPS、不得为环回/私网/链路本地/保留测试域），
    防止该入口被当作 SSRF 跳板。注意：形状校验是离线近似，
    不替代真实 DNS 解析、证书与重定向复核。
    """
    url = payload.get("url", "")
    try:
        safe_url = validate_public_url(url)
    except UnsafeURL as exc:
        raise HTTPException(status_code=400, detail=f"URL 校验失败：{exc}")
    return {
        "status": "accepted",
        "url": safe_url,
        "message": "爬虫任务已入队（占位），生产期对接 Scrapy + Playwright",
    }
