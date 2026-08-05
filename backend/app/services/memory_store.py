"""内存存储（开发期兜底）。

未启用数据库持久化时，招募 / 反馈 / 投递 / 问卷会话存在内存。
启用数据库后这些会被 ORM 表替代。
"""

# 通过 POST 发布的招募（内存）
RECRUITMENTS_STORE: list[dict] = []
# 用户反馈（内存，镜像 feedback 表）
FEEDBACK_STORE: list[dict] = []
# 简历投递（内存，镜像 applications 表）
APPLICATIONS_STORE: list[dict] = []
# 问卷会话 session_id -> messages（内存，镜像 questionnaire_sessions 表）
QUESTIONNAIRE_SESSIONS: dict[str, list[dict]] = {}
