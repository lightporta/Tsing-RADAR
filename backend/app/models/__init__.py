"""ORM 模型聚合，便于 init_db 一次性导入。"""

from app.models.student import Student
from app.models.advisor import Advisor
from app.models.match_record import MatchRecord
from app.models.resume import Resume
from app.models.recruitment import Recruitment
from app.models.application import Application
from app.models.feedback import Feedback
from app.models.questionnaire_session import QuestionnaireSession
from app.models.training_sample import TrainingSample
from app.models.identity import ExternalIdentity, IdentitySession
from app.models.idempotency import IdempotencyRecord
from app.models.artifact_audit import ArtifactAuditEvent
from app.models.private_document import (
    ArtifactDeliveryGrant,
    DeletedArtifactTombstone,
    PrivateDocument,
)

__all__ = [
    "Student",
    "Advisor",
    "MatchRecord",
    "Resume",
    "Recruitment",
    "Application",
    "Feedback",
    "QuestionnaireSession",
    "TrainingSample",
    "ExternalIdentity",
    "IdentitySession",
    "IdempotencyRecord",
    "ArtifactAuditEvent",
    "PrivateDocument",
    "ArtifactDeliveryGrant",
    "DeletedArtifactTombstone",
]
