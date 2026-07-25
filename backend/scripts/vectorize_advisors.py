"""导师向量化脚本：把 field + tags 文本向量化后写入向量库。

用于知识库预热（文档 §8.2 步骤三）。
"""

import asyncio
import json
import os

from app.services.llm import embed_text
from app.services.vectorstore import get_vector_store


async def main() -> None:
    data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mentors.json")
    with open(data_path, "r", encoding="utf-8") as f:
        mentors = json.load(f)

    store = get_vector_store()
    count = 0
    for m in mentors:
        text = m.get("field", "") + " " + " ".join(m.get("tags", []))
        vec = await embed_text(text)
        if hasattr(store, "upsert"):
            store.upsert(m.get("name", ""), text, {"dept": m.get("dept"), "name": m.get("name")})
        count += 1
        if count % 10 == 0:
            print(f"已向量化 {count}/{len(mentors)}")
    print(f"✅ 知识库预热完成，共 {count} 位导师")


if __name__ == "__main__":
    asyncio.run(main())
