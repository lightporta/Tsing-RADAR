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
]
