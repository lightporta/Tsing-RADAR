"""ORM 模型聚合，便于 init_db 一次性导入。"""

from app.models.student import Student
from app.models.advisor import Advisor  # 旧表，保留前端兼容
from app.models.match_record import MatchRecord
from app.models.resume import Resume
from app.models.recruitment import Recruitment
from app.models.application import Application
from app.models.feedback import Feedback
from app.models.questionnaire_session import QuestionnaireSession
from app.models.training_sample import TrainingSample
from app.models.storage_object import StorageObject

# RADAR 规范扩展（9 张新表）
from app.models.entity import Entity, EntityName, Relation
from app.models.direction import Direction, EntityDirection
from app.models.catalog import CatalogLink
from app.models.opportunity import Opportunity
from app.models.claim import Claim, Source

# 私域信号层（D 级来源，物理隔离，永不进公开接口）
from app.models.private_signal import PrivateFeedbackRaw, PrivateSignal

# 治理层（审核 / 问题 / 批次指标，对应规范第 3.3 节）
from app.models.governance import Review, Issue, BatchMetric

__all__ = [
    # 旧表
    "Student",
    "Advisor",
    "MatchRecord",
    "Resume",
    "Recruitment",
    "Application",
    "Feedback",
    "QuestionnaireSession",
    "TrainingSample",
    "StorageObject",
    # RADAR 公开层（A/B/C 级来源）
    "Entity",
    "EntityName",
    "Relation",
    "Direction",
    "EntityDirection",
    "CatalogLink",
    "Opportunity",
    "Claim",
    "Source",
    # RADAR 私域层（D 级来源，物理隔离）
    "PrivateFeedbackRaw",
    "PrivateSignal",
    # 治理层（发布门禁工作流）
    "Review",
    "Issue",
    "BatchMetric",
]
