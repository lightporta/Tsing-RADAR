"""向量数据库服务（Milvus 占位 + 词项特征哈希内存兜底）。

生产期配置 MILVUS_HOST 后启用真实向量检索；否则仅做确定性词项重合回退，
不得把该回退描述为可靠的语义 embedding。
"""

from typing import Any, Optional

from app.core.config import settings
from app.services.matching import cosine_similarity, hash_embedding


class InMemoryVectorStore:
    """内存向量库（开发期兜底，确定性词项特征哈希）。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[list[float], dict[str, Any]]] = {}

    def upsert(self, key: str, text: str, metadata: Optional[dict[str, Any]] = None) -> list[float]:
        vec = hash_embedding(text, 128)
        self._store[key] = (vec, metadata or {})
        return vec

    def search(self, query_vec: list[float], top_k: int = 5) -> list[tuple[str, float, dict[str, Any]]]:
        results = []
        for key, (vec, meta) in self._store.items():
            score = cosine_similarity(query_vec, vec)
            results.append((key, score, meta))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def clear(self) -> None:
        self._store.clear()


# 全局单例
_vector_store: Optional[Any] = None


def get_vector_store() -> Any:
    """获取向量库实例。

    配置了 MILVUS_HOST 时返回 Milvus 客户端（需 pymilvus），
    否则返回内存兜底实现。
    """
    global _vector_store
    if _vector_store is not None:
        return _vector_store

    if settings.MILVUS_HOST:
        try:
            from pymilvus import MilvusClient

            _vector_store = MilvusClient(uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}")
            return _vector_store
        except ImportError:
            pass  # pymilvus 未安装，降级

    _vector_store = InMemoryVectorStore()
    return _vector_store
