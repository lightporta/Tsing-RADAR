"""Fail-closed learned-ranking activation gate.

Preference feedback and interview completion are not outcome labels. A7 keeps
the learned model disabled until a future, separately approved data contract
can satisfy the privacy, quality, and offline-evaluation gates.
"""

from typing import Any

from app.db.session import SessionLocal
from app.services.evaluation import assess_learning_readiness

MODEL_WEIGHTS: dict[str, Any] | None = None


def train() -> dict[str, Any]:
    """Return the readiness decision without training or creating weights."""
    global MODEL_WEIGHTS
    MODEL_WEIGHTS = None
    with SessionLocal() as db:
        readiness = assess_learning_readiness(db)
    return {
        "status": "blocked_by_data_readiness_gate",
        "training_started": False,
        "weights": None,
        "readiness": readiness,
    }


def get_model_weights() -> dict[str, Any] | None:
    """Learned weights remain unavailable while the gate is blocked."""
    return MODEL_WEIGHTS
