"""导师数据加载：从 mentors.json 加载到内存。

生产期应改为从 advisors 表读取，此处保留 JSON 兼容。
"""

import json
import os
from functools import lru_cache
from typing import Any

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "mentors.json")


@lru_cache(maxsize=1)
def load_mentors() -> list[dict[str, Any]]:
    """启动时加载导师库（81 位导师）。"""
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reload_mentors() -> list[dict[str, Any]]:
    """强制重新加载（数据更新后调用）。"""
    load_mentors.cache_clear()
    return load_mentors()
