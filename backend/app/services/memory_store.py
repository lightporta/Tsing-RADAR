"""内存存储（开发期兜底）。

招募 / 反馈 / 投递仍保留开发期内存实现。
A3 问卷会话已强制使用数据库，不再提供内存旁路。
"""

# 通过 POST 发布的招募（内存）
RECRUITMENTS_STORE: list[dict] = []
# 用户反馈（内存，镜像 feedback 表）
FEEDBACK_STORE: list[dict] = []
# 简历投递（内存，镜像 applications 表）
APPLICATIONS_STORE: list[dict] = []
