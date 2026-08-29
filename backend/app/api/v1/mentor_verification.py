"""导师校园卡验证 API（上传与状态查询；认领导师档案的前置审核）。"""

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import (
    get_mentor_principal,
    get_mutating_mentor_principal,
)
from app.db.session import get_db
from app.services.mentor_verification import (
    campus_card_status,
    upload_campus_card,
)

router = APIRouter(prefix="/mentor/verification")

# /mentor/verification/campus-card 需要导师账号登录（无需先认领档案）


@router.get("/campus-card")
def my_campus_card_status(
    mentor=Depends(get_mentor_principal),
    db: Session = Depends(get_db),
):
    return campus_card_status(db, account=mentor.account)


@router.post("/campus-card")
async def upload_my_campus_card(
    upload: UploadFile,
    mentor=Depends(get_mutating_mentor_principal),
    db: Session = Depends(get_db),
):
    return await upload_campus_card(db, account=mentor.account, upload=upload)
