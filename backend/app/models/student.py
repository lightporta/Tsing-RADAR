"""students 学生信息表（文档表 1）。"""

from sqlalchemy import JSON, Column, String, Text

from app.db.base import Base


class Student(Base):
    __tablename__ = "students"

    student_id = Column(String(20), primary_key=True)  # 清华学号
    email = Column(String(50), index=True)
    department = Column(String(50))
    category = Column(String(20))  # 本科生/硕士生/博士生
    grade = Column(String(20))
    phone = Column(String(20))  # 加密存储
    profile_text = Column(Text)
    interest_vector = Column(JSON)  # 学业志趣自测结果 + 雷达图权重配置
