"""未接入的校内能力显式失败，禁止用 stub 冒充真实身份或数据。"""

from fastapi import APIRouter, HTTPException, status

router = APIRouter()


def _not_integrated() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="该校内能力尚未完成可信接入，当前不会返回模拟成功或示例数据",
    )


@router.get("/tsinghua/auth/verify")
def verify_student():
    _not_integrated()


@router.get("/tsinghua/lib/papers")
def lib_papers():
    _not_integrated()


@router.post("/internal/scrape/faculty")
def scrape_faculty():
    _not_integrated()
