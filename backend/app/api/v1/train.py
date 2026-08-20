"""Learned-ranking readiness audit (administrator only)."""

from fastapi import APIRouter, Body, Depends

from app.core.deps import verify_admin
from app.services.training import train

router = APIRouter()


@router.post("/train/trigger")
def train_trigger(
    _empty_body: None = Body(default=None),
    _admin: None = Depends(verify_admin),
):
    """Evaluate the learned-ranking gate; never train on proxy labels."""
    return train()
