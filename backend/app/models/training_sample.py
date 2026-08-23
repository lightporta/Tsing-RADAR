"""training_samples 训练样本表（文档表 9）。"""

from sqlalchemy import JSON, Column, DateTime, Float, String, func

from app.db.base import Base
from app.models.match_record import _uuid


class TrainingSample(Base):
    __tablename__ = "training_samples"

    sample_id = Column(String(36), primary_key=True, default=lambda: str(_uuid()))
    student_id = Column(String(20), index=True)
    questionnaire_id = Column(String(36))
    chosen_advisor_id = Column(String(20))
    features = Column(JSON)
    label = Column(Float)
    created_at = Column(DateTime, server_default=func.now())
