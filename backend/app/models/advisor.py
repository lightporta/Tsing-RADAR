"""advisors 导师画像表（文档表 2）。"""

from sqlalchemy import JSON, Column, Float, String, Text

from app.db.base import Base


class Advisor(Base):
    __tablename__ = "advisors"

    advisor_id = Column(String(20), primary_key=True)  # 教职工工号
    name = Column(String(50), index=True)
    department = Column(String(50))
    field = Column(String(200))
    tags = Column(JSON)  # 研究方向标签
    profile_text = Column(Text)
    recent_papers = Column(JSON)
    contact_email = Column(String(50))
    office_loc = Column(String(50))
    radar_traits = Column(JSON)  # 六边形雷达图得分
    popularity = Column(Float, default=0)  # 热门指数 0-100
    sector = Column(Float, default=0)  # 行业性质 0=国 1=私
