"""v4.3.0 阶段三：知识库向量混合召回（零依赖，诚实降级）测试。

验收口径（任务书 §三）：
- ③-① 向量索引：构建脚本产出向量文件 + manifest SHA256；无 key 诚实退出；
- ③-② 混合召回：词法命中优先；未命中时向量语义补充可召回（monkeypatch 模拟）；
- ③-③ 降级链：无索引/无 key 行为与词法基线逐字一致（测试锁死）；
- ③-④ 拒答门：全不达标（低于阈值）仍明确拒答，来源声明不变。
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import math
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.models.identity import ExternalIdentity
from app.core.config import Settings
from app.services import mentor_knowledge as mk
from app.services import mentor_knowledge_vector as mkv

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_mentor_knowledge.py"


def _keyed_settings() -> Settings:
    return Settings(_env_file=None, LLM_PROVIDER="glm", GLM_API_KEY="test-key")


def _keyless_settings() -> Settings:
    return Settings(_env_file=None)


# 2 维平面上的确定性向量（均已归一化，余弦可手算；避免任何一对
# 恰好落在 0.6 阈值边界上）：
#   李琦 = [1, 0]   龙明盛 = [0, 1]   崔勇 = [0.5, 0.86603]
_INDEX_VECTORS = {
    "李琦": [1.0, 0.0],
    "龙明盛": [0.0, 1.0],
    "崔勇": [0.5, 0.8660254037844386],
}


def _write_index(tmp_path: Path) -> Path:
    path = tmp_path / "mentors.knowledge.vectors.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model": "embedding-3",
                "dim": 2,
                "count": len(_INDEX_VECTORS),
                "vectors": _INDEX_VECTORS,
            }
        ),
        encoding="utf-8",
    )
    return path


def _fake_embed(vector: list[float]):
    async def _embed(_text: str) -> list[float] | None:
        return list(vector)

    return _embed


@pytest.fixture(autouse=True)
def _reset_caches():
    mk.reset_knowledge_cache()
    mkv.reset_vector_cache()
    yield
    mk.reset_knowledge_cache()
    mkv.reset_vector_cache()


# —— 纯 Python 余弦 ——


def test_cosine_parallel_orthogonal_and_defensive():
    assert mkv._cosine([1.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)
    assert mkv._cosine([1.0, 0.0], [0.0, 3.0]) == pytest.approx(0.0)
    assert mkv._cosine([1.0, 1.0], [1.0, 0.0]) == pytest.approx(
        1.0 / math.sqrt(2.0)
    )
    # 防御分支：长度不一致 / 空向量 / 零向量 → 0.0
    assert mkv._cosine([1.0], [1.0, 0.0]) == 0.0
    assert mkv._cosine([], []) == 0.0
    assert mkv._cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# —— ③-③ 降级链：无索引 / 无 key → 空列表（词法基线逐字一致） ——


@pytest.mark.asyncio
async def test_recall_without_index_returns_empty(monkeypatch):
    monkeypatch.setattr(
        mkv, "_VECTORS_PATH", Path("/nonexistent/vectors.json")
    )
    mkv.reset_vector_cache()
    assert await mkv.vector_recall("李琦老师怎么样") == []
    assert mkv.vector_recall_ready() is False


@pytest.mark.asyncio
async def test_recall_without_key_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    # 显式注入无凭据 settings（防开发机 backend/.env 泄漏 GLM key）
    monkeypatch.setattr(mkv, "settings", _keyless_settings())
    assert await mkv.vector_recall("李琦老师怎么样") == []
    assert mkv.vector_recall_ready() is False


@pytest.mark.asyncio
async def test_recall_with_corrupt_index_returns_empty(monkeypatch, tmp_path):
    path = tmp_path / "mentors.knowledge.vectors.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(mkv, "_VECTORS_PATH", path)
    mkv.reset_vector_cache()
    assert await mkv.vector_recall("李琦老师怎么样") == []


@pytest.mark.asyncio
async def test_recall_dim_mismatch_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    monkeypatch.setattr(mkv, "_glm_key_present", lambda: True)
    # 查询向量 3 维 vs 索引 2 维 → 诚实降级
    monkeypatch.setattr(mkv, "embed_text_strict", _fake_embed([1.0, 0.0, 0.0]))
    assert await mkv.vector_recall("李琦老师怎么样") == []


@pytest.mark.asyncio
async def test_recall_embed_failure_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    monkeypatch.setattr(mkv, "_glm_key_present", lambda: True)

    async def _fail(_text):
        return None

    monkeypatch.setattr(mkv, "embed_text_strict", _fail)
    assert await mkv.vector_recall("李琦老师怎么样") == []


# —— ③-② 混合召回：阈值门控 + top-K + 确定性排序 ——


@pytest.mark.asyncio
async def test_recall_returns_aligned_mentor_above_threshold(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    monkeypatch.setattr(mkv, "_glm_key_present", lambda: True)
    monkeypatch.setattr(mkv, "embed_text_strict", _fake_embed([1.0, 0.0]))
    records = await mkv.vector_recall("李琦老师怎么样")
    assert [r["name"] for r in records] == ["李琦"]
    assert "计算机科学与技术系" in records[0]["department_header"]


@pytest.mark.asyncio
async def test_recall_orders_by_similarity_and_caps_top_k(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    monkeypatch.setattr(mkv, "_glm_key_present", lambda: True)
    # 查询 [√2/2, √2/2]（归一化）：cos 崔勇≈0.966 > 李琦=龙明盛≈0.707
    # （同分按姓名字典序：李琦 < 龙明盛）
    monkeypatch.setattr(
        mkv, "embed_text_strict", _fake_embed([0.7071067811865476] * 2)
    )
    records = await mkv.vector_recall("做系统的老师怎么样")
    assert [r["name"] for r in records] == ["崔勇", "李琦", "龙明盛"]
    limited = await mkv.vector_recall("做系统的老师怎么样", top_k=2)
    assert [r["name"] for r in limited] == ["崔勇", "李琦"]


@pytest.mark.asyncio
async def test_recall_threshold_blocks_partial_matches(monkeypatch, tmp_path):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    monkeypatch.setattr(mkv, "_glm_key_present", lambda: True)
    # 查询 [1,2]/√5 ≈ [0.4472, 0.8944]：cos 崔勇≈0.998、龙明盛≈0.894
    # 过阈值；李琦≈0.447 低于 0.6 被阈值挡下
    monkeypatch.setattr(
        mkv, "embed_text_strict", _fake_embed([0.4472135954999579, 0.8944271909999159])
    )
    records = await mkv.vector_recall("做偏工程的老师怎么样")
    assert [r["name"] for r in records] == ["崔勇", "龙明盛"]


# —— ③-④ 拒答门 + 渲染 ——


@pytest.mark.asyncio
async def test_recall_all_below_threshold_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(mkv, "_VECTORS_PATH", _write_index(tmp_path))
    mkv.reset_vector_cache()
    monkeypatch.setattr(mkv, "_glm_key_present", lambda: True)
    # 查询 [0, -1]：与三个块余弦均为负 → 全不达标 → 拒答门守住
    monkeypatch.setattr(mkv, "embed_text_strict", _fake_embed([0.0, -1.0]))
    assert await mkv.vector_recall("张三丰老师怎么样") == []


def test_render_semantic_supplement_keeps_declaration_and_honesty():
    record = mk.query_mentor_knowledge("李琦")
    text = mk.render_semantic_supplement("李奇", [record])
    # 头部：明示"未收录 + 语义相近"，不冒充精确匹配
    assert "「李奇」的公开评价综述暂未收录" in text
    assert "语义相近" in text
    # 块内：声明与事实渲染逐字复用 render_mentor_knowledge
    assert "【李琦 · 计算机科学与技术系】" in text
    assert "公开存档匿名主观评价聚合，仅作参考" in text
    assert "评价概况：15 条" in text


# —— 黑盒：词法优先 / 补充生效 / 拒答逐字一致 ——


def _qxd_headers(claim: str) -> dict[str, str]:
    signature = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        claim.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        **AUTH,
        "X-QXD-End-User-Id": claim,
        "X-QXD-End-User-Signature": signature,
    }


def _ensure_identity(claim: str) -> str:
    fingerprint = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        f"identity-map:{claim}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with SessionLocal() as db:
        mapping = (
            db.query(ExternalIdentity)
            .filter(ExternalIdentity.claim_fingerprint == fingerprint)
            .one_or_none()
        )
        if mapping is None:
            mapping = ExternalIdentity(
                mapping_id=str(uuid.uuid4()),
                provider="qxd",
                claim_fingerprint=fingerprint,
                subject_id=f"usr_{uuid.uuid4().hex}",
            )
            db.add(mapping)
            db.commit()
        subject = mapping.subject_id
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tsing-radar:qxd-interview:{subject}:vector-eval",
        )
    )


def _post(claim: str, session_id: str, content: str):
    return client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "model": "tsing-radar",
            "user": claim,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        },
    )


def test_chat_lexical_hit_skips_vector_recall(monkeypatch):
    """③-② 词法命中优先：命中路径绝不触发向量召回。"""

    async def _boom(_query):
        raise AssertionError("词法命中不应触发向量召回")

    monkeypatch.setattr("app.api.v1.chat.vector_recall", _boom)
    claim = f"vec-lex-{uuid.uuid4().hex[:8]}"
    session_id = _ensure_identity(claim)
    response = _post(claim, session_id, "李琦老师怎么样")
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "【李琦" in content
    assert "语义相近" not in content  # 精确命中，非补充渲染


def test_chat_lexical_miss_with_supplement_renders_related(monkeypatch):
    """③-② 未命中 + 语义补充生效（monkeypatch 模拟有 key 环境）。"""
    record = mk.query_mentor_knowledge("李琦")

    async def _fake_recall(_query):
        return [record]

    monkeypatch.setattr("app.api.v1.chat.vector_recall", _fake_recall)
    claim = f"vec-sup-{uuid.uuid4().hex[:8]}"
    session_id = _ensure_identity(claim)
    response = _post(claim, session_id, "李奇老师怎么样")  # 未收录姓名
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "「李奇」的公开评价综述暂未收录" in content
    assert "语义相近" in content
    assert "【李琦" in content
    assert "公开存档匿名主观评价聚合，仅作参考" in content


def test_chat_lexical_miss_without_supplement_refuses_verbatim(monkeypatch):
    """③-③/③-④ 降级与拒答门：无补充 → 与词法基线逐字一致。"""

    async def _empty(_query):
        return []

    monkeypatch.setattr("app.api.v1.chat.vector_recall", _empty)
    claim = f"vec-ref-{uuid.uuid4().hex[:8]}"
    session_id = _ensure_identity(claim)
    response = _post(claim, session_id, "张三丰老师怎么样")
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == mk.render_mentor_not_found("张三丰")


def test_chat_default_env_matches_lexical_baseline():
    """③-③ 无 monkeypatch（无索引/无 key 的默认环境）→ 拒答逐字一致。"""
    claim = f"vec-base-{uuid.uuid4().hex[:8]}"
    session_id = _ensure_identity(claim)
    response = _post(claim, session_id, "张三丰老师怎么样")
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert content == mk.render_mentor_not_found("张三丰")


# —— ③-① 构建脚本：--rebuild-vectors ——


def _load_build_script():
    spec = importlib.util.spec_from_file_location(
        "build_mentor_knowledge_test", BUILD_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_tmp_outputs(bmk, tmp_path: Path) -> None:
    knowledge = tmp_path / "mentors.knowledge.json"
    knowledge.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "mentors": [
                    {
                        "name": "李琦",
                        "department_header": "计算机科学与技术系",
                        "summary": "综述A",
                    },
                    {
                        "name": "李宇根",
                        "department_header": "微电子与纳电子学系",
                        "summary": "综述B",
                    },
                    {
                        "name": "李宇根",
                        "department_header": "微电子与纳电子学系",
                        "summary": "同名后现，应被首现优先去重",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "knowledge_manifest.json"
    manifest.write_text(
        json.dumps({"artifact": "mentors.knowledge.json"}), encoding="utf-8"
    )
    bmk.KNOWLEDGE_OUT = knowledge
    bmk.MANIFEST_OUT = manifest
    bmk.VECTORS_OUT = tmp_path / "mentors.knowledge.vectors.json"
    # build_vectors 的输出打印用 REPO_ROOT 做 relative_to；tmp 路径下
    # 一并替换（sys.path 探测不受影响——真实 backend 已在测试 sys.path）
    bmk.REPO_ROOT = tmp_path


def test_build_vectors_exits_honestly_without_key(monkeypatch, tmp_path):
    bmk = _load_build_script()
    _seed_tmp_outputs(bmk, tmp_path)
    # build_vectors 在函数内 from app.core.config import settings →
    # 替换模块属性才可见（PrivateAttr 单例 patch 无效）
    monkeypatch.setattr("app.core.config.settings", _keyless_settings())
    with pytest.raises(SystemExit):
        bmk.build_vectors()
    assert not bmk.VECTORS_OUT.exists()


def test_build_vectors_writes_index_and_manifest_sha(monkeypatch, tmp_path):
    bmk = _load_build_script()
    _seed_tmp_outputs(bmk, tmp_path)
    keyed = _keyed_settings()
    monkeypatch.setattr("app.core.config.settings", keyed)

    async def _fake_strict(text: str):
        # 名字首字哈希到 [0,1) 的确定性二维向量
        value = (ord(text[0]) % 97) / 97.0
        return [value, 1.0 - value]

    monkeypatch.setattr(
        "app.services.llm.embed_text_strict", _fake_strict
    )
    bmk.build_vectors()

    payload = json.loads(bmk.VECTORS_OUT.read_text(encoding="utf-8"))
    # 首现优先去重：李宇根 两条章节合并为一块
    assert payload["dim"] == 2
    assert set(payload["vectors"]) == {"李琦", "李宇根"}
    assert payload["count"] == 2
    assert payload["model"] == keyed.GLM_EMBED_MODEL
    manifest = json.loads(bmk.MANIFEST_OUT.read_text(encoding="utf-8"))
    digest = hashlib.sha256(
        bmk.VECTORS_OUT.read_bytes()
    ).hexdigest()
    assert manifest["vectors_sha256"] == digest
    assert manifest["vectors_artifact"] == "mentors.knowledge.vectors.json"
    assert manifest["vectors_count"] == 2
    assert manifest["vectors_dim"] == 2


def test_build_vectors_aborts_on_embed_failure(monkeypatch, tmp_path):
    bmk = _load_build_script()
    _seed_tmp_outputs(bmk, tmp_path)
    monkeypatch.setattr("app.core.config.settings", _keyed_settings())

    async def _flaky(text: str):
        return None if text.startswith("李宇根") else [1.0, 0.0]

    monkeypatch.setattr(
        "app.services.llm.embed_text_strict", _flaky
    )
    with pytest.raises(SystemExit):
        bmk.build_vectors()
    assert not bmk.VECTORS_OUT.exists()


def test_block_text_composition():
    bmk = _load_build_script()
    text = bmk._block_text(
        {"name": "李琦", "department_header": "计算机系", "summary": "综述"}
    )
    assert text == "李琦（计算机系）：综述"
