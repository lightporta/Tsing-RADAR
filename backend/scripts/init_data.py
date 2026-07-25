"""数据初始化脚本：把 mentors.json 导入 advisors 表。

开发期可跳过（路由直接读 JSON）；生产期启用数据库时运行。
"""

import json
import os

from app.db.session import SessionLocal, init_db
from app.models.advisor import Advisor


def main() -> None:
    init_db()
    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mentors.json")
    with open(data_path, "r", encoding="utf-8") as f:
        mentors = json.load(f)

    db = SessionLocal()
    try:
        for i, m in enumerate(mentors):
            advisor = Advisor(
                advisor_id=f"T{1000 + i}",
                name=m.get("name", ""),
                department=m.get("dept", ""),
                field=m.get("field", ""),
                tags=m.get("tags", []),
                contact_email=m.get("contact_email"),
                office_loc=m.get("office_loc"),
                radar_traits=m.get("radar_traits", {}),
                popularity=m.get("popularity", 0),
                sector=0 if m.get("sector", "国") == "国" else 1,
            )
            db.merge(advisor)
        db.commit()
        print(f"✅ 已导入 {len(mentors)} 位导师到 advisors 表")
    finally:
        db.close()


if __name__ == "__main__":
    main()
