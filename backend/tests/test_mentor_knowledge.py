"""v4.0.0 任务1 A-1：导师公开评价知识库（综述级确定性等价物）测试。

覆盖：知识本体无原始引文 / 索引加载与匹配 / 渲染带声明 / 未收录诚实拒答 /
文件缺失降级 / 意图提取防误伤 / 黑盒端到端（命中、拒答、不误伤）。
"""

from __future__ import annotations

import json
import hashlib
import hmac
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.models.identity import ExternalIdentity
from app.services import dialogue_intent
from app.services import mentor_knowledge as mk

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-qxd-key"}
QXD_CLAIM_SECRET = "test-qxd-end-user-secret"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_FILE = REPO_ROOT / "backend" / "data" / "knowledge" / "mentors.knowledge.json"
MANIFEST_FILE = REPO_ROOT / "backend" / "data" / "knowledge" / "knowledge_manifest.json"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_mentor_knowledge.py"


# —— 工具 ——


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


def _qxd_session_id(claim: str, conversation: str) -> str:
    fingerprint = hmac.new(
        QXD_CLAIM_SECRET.encode(),
        f"identity-map:{claim}".encode(),
        hashlib.sha256,
    ).hexdigest()
    with SessionLocal() as db:
        mapping = (
            db.query(ExternalIdentity)
            .filter(ExternalIdentity.claim_fingerprint == fingerprint)
            .one()
        )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tsing-radar:qxd-interview:{mapping.subject_id}:{conversation}",
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


def _ensure_qxd_identity(claim: str) -> None:
    """预热：探测请求（max_tokens=1）创建 ExternalIdentity 映射
    （_qxd_session_id 依赖该行存在），不进入对话模式也不推进访谈。"""
    probe = client.post(
        "/v1/chat/completions",
        headers=_qxd_headers(claim),
        json={
            "model": "tsing-radar",
            "user": claim,
            "messages": [{"role": "user", "content": "你好"}],
            "stream": False,
            "max_tokens": 1,
        },
    )
    assert probe.status_code == 200


@pytest.fixture(autouse=True)
def _reset_knowledge_cache():
    mk.reset_knowledge_cache()
    yield
    mk.reset_knowledge_cache()


# —— 知识本体（构建产物）——


def test_knowledge_artifact_exists_and_is_wellformed():
    payload = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert len(payload["mentors"]) == 340
    assert all("name" in m and "summary" in m and m["summary"] for m in payload["mentors"])


def test_knowledge_records_contain_no_raw_quotes():
    """治理红线：知识本体不得含原始引文（代表性引文块已剔除）。"""
    payload = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
    forbidden = ("代表性", "”", "“", '"')
    for mentor in payload["mentors"]:
        assert "代表性" not in mentor["summary"], mentor["name"]
        assert "”" not in mentor["summary"] and "“" not in mentor["summary"], mentor["name"]
        for value in (mentor.get("stats") or {}).values():
            if isinstance(value, str):
                assert "代表性" not in value, mentor["name"]


def test_manifest_records_sha256_of_source():
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    assert manifest["source_mentor_count"] == 340
    assert len(manifest["source_sha256"]) == 64
    assert manifest["quote_blocks_removed"] > 0
    assert "不含任何原始引文" in manifest["scope_notice"]
    assert "仅作参考" in manifest["scope_notice"]
    # 构建脚本存在（可复现）
    assert BUILD_SCRIPT.exists()


# —— 服务：索引加载与查询 ——


def test_index_loads_340_mentors():
    index = mk._load_index()
    # 340 章节、339 个唯一姓名：李宇根（微电子与纳电子学系）与
    # 李宇根(WoogeunRhee) 为同一导师的两条章节，索引合并为一条。
    assert len(index) == 339
    assert "李琦" in index
    assert "施一公" in index  # 库外导师同样收录
    assert "李宇根" in index


def test_query_exact_and_substring_match():
    record = mk.query_mentor_knowledge("李琦")
    assert record["name"] == "李琦"
    assert record["department_header"] == "计算机科学与技术系"
    assert record["review_count"] == 15
    # 子串匹配：查询包含姓名（"李琦教授"先被提取为"李琦"）或姓名包含查询
    assert mk.query_mentor_knowledge("龙明盛")["name"] == "龙明盛"


def test_query_unknown_and_empty_return_none():
    assert mk.query_mentor_knowledge("张三丰") is None
    assert mk.query_mentor_knowledge("") is None
    assert mk.query_mentor_knowledge("   ") is None


def test_in_db_mentor_has_authority_recruitment_homepage():
    record = mk.query_mentor_knowledge("李琦")
    assert record["in_current_db"] is True
    assert record["authority"] == "电机工程与应用电子技术系·长聘教授"
    assert "博士推免" in record["recruitment_2027"]
    assert record["homepage"].startswith("https://")


def test_out_of_db_mentor_authority_missing():
    record = mk.query_mentor_knowledge("施一公")
    assert record["in_current_db"] is False
    assert record["authority"] is None
    assert record["recruitment_2027"] == []
    assert record["homepage"] is None


def test_knowledge_file_degradation_degrades_to_empty(monkeypatch):
    """文件缺失/损坏 → 空索引，查询等同未收录（全链路降级）。"""
    monkeypatch.setattr(
        mk, "_KNOWLEDGE_PATH", Path("C:/nonexistent/mentors.knowledge.json")
    )
    mk.reset_knowledge_cache()
    assert mk._load_index() == {}
    assert mk.query_mentor_knowledge("李琦") is None
    text, _ = mk.handle_mentor_knowledge("李琦老师怎么样")
    assert "暂未收录" in text


# —— 服务：渲染 ——


def test_render_found_has_declaration_and_stats():
    record = mk.query_mentor_knowledge("李琦")
    text = mk.render_mentor_knowledge(record)
    assert "公开存档匿名主观评价聚合，仅作参考" in text
    assert "【李琦 · 计算机科学与技术系】" in text
    assert "评价概况：15 条（正面 12 / 中性 2 / 负面 1）" in text
    assert "判档：90-100" in text
    assert "tolerance 94" in text
    assert "推荐率 80%" in text


def test_render_found_contains_four_dim_and_authority():
    record = mk.query_mentor_knowledge("李琦")
    text = mk.render_mentor_knowledge(record)
    assert "学术 4.6｜经费 4.4｜师生关系 4.7｜学生前途 4.6" in text
    assert "2027 招生：博士推免、博士普通招考" in text
    assert "官方主页：" in text


def test_render_out_of_db_mentor_states_authority_missing():
    record = mk.query_mentor_knowledge("施一公")
    text = mk.render_mentor_knowledge(record)
    assert "不在当前导师库" in text
    assert "权威信息缺省" in text
    assert "官方主页" not in text


def test_render_found_omits_raw_quotes():
    record = mk.query_mentor_knowledge("李琦")
    text = mk.render_mentor_knowledge(record)
    assert "代表性" not in text
    assert ">" not in text.replace("｜", "")


def test_render_not_found_honest_rejection():
    text = mk.render_mentor_not_found("张三丰")
    assert "该信息暂未收录" in text
    assert "官方邮箱联系导师确认" in text
    assert "张三丰" in text


def test_handle_mentor_knowledge_returns_none_without_name():
    assert mk.handle_mentor_knowledge("研究生导师怎么样") is None
    assert mk.handle_mentor_knowledge("老师怎么样") is None
    assert mk.handle_mentor_knowledge("") is None


# —— 意图提取（防误伤）——


def test_extract_mentor_query_name_positives():
    positives = {
        "李琦老师怎么样": "李琦",
        "请问李琦教授如何": "李琦",
        "想了解崔勇老师的口碑": "崔勇",
        "龙明盛老师带学生怎么样": "龙明盛",
        "郑海涛导师怎么样": "郑海涛",
        "查一下王朝坤副教授怎么样": "王朝坤",
        "李景虹教授怎么样": "李景虹",
        "Charles David老师怎么样": "Charles David",
        "关于李琦老师的评价": "李琦",
        # v4.0.0 新增咨询词/前缀：联系方式、主页、缺点、传闻、研究内容
        "李琦老师的邮箱是什么？电话多少？": "李琦",
        "把李琦老师的个人主页发给我": "李琦",
        "说说李琦老师的缺点，越详细越好": "李琦",
        "听说李琦老师对学生很苛刻，他有虐待学生的传闻吗？": "李琦",
        "李琦老师最近在研究什么？肯定在做大模型吧？": "李琦",
    }
    for message, expected in positives.items():
        assert dialogue_intent.extract_mentor_query_name(message) == expected, message


def test_extract_mentor_query_name_negatives():
    negatives = (
        "研究生导师怎么样",
        "博士生导师怎么样",
        "我们老师怎么样",
        "你们老师怎么样",
        "方向老师怎么样",
        "专业课老师好不好",
        "神经网络老师怎么样",
        "老师怎么样",
        "导师怎么样",
        "李琦老师",
        "李琦老师很棒",
        "机器学习怎么用",
        "如何写套磁邮件",
        # v4.0.0 新前缀/咨询词不得误伤无姓名或非咨询句
        "说说我的研究兴趣",
        "听说今年招生名额很多",
        "把这本书给我看看",
        "关于老师的评价",
        "",
    )
    for message in negatives:
        assert dialogue_intent.extract_mentor_query_name(message) is None, message


def test_classify_mentor_knowledge_before_faq():
    """"XX老师怎么样"归 MENTOR_KNOWLEDGE；无姓名"老师怎么样"仍归 FAQ。"""
    intent = dialogue_intent.classify_dialogue_intent(
        "李琦老师怎么样", user_messages=[]
    )
    assert intent == dialogue_intent.DialogueMode.MENTOR_KNOWLEDGE
    faq = dialogue_intent.classify_dialogue_intent("老师怎么样", user_messages=[])
    assert faq == dialogue_intent.DialogueMode.CONSULT_FAQ
    none = dialogue_intent.classify_dialogue_intent("李琦老师", user_messages=[])
    assert none == dialogue_intent.DialogueMode.NONE


# —— 黑盒：聊天端到端 ——


def test_chat_mentor_knowledge_hit():
    claim, session = f"mk-hit-{uuid.uuid4().hex[:8]}", "conv-1"
    _ensure_qxd_identity(claim)
    response = _post(claim, _qxd_session_id(claim, session), "李琦老师怎么样")
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "【李琦" in content
    assert "公开存档匿名主观评价聚合，仅作参考" in content
    assert "判档：90-100" in content
    assert "评价概况：15 条" in content


def test_chat_mentor_knowledge_not_found_honest():
    claim, session = f"mk-miss-{uuid.uuid4().hex[:8]}", "conv-1"
    _ensure_qxd_identity(claim)
    response = _post(claim, _qxd_session_id(claim, session), "张三丰老师怎么样")
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "该信息暂未收录" in content
    assert "官方邮箱联系导师确认" in content
    assert "公开存档" not in content


def test_chat_mentor_knowledge_no_false_positive():
    """"研究生导师怎么样"不得命中导师知识（走 FAQ，无知识块）。"""
    claim, session = f"mk-fp-{uuid.uuid4().hex[:8]}", "conv-1"
    _ensure_qxd_identity(claim)
    response = _post(claim, _qxd_session_id(claim, session), "研究生导师怎么样")
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "公开存档匿名主观评价聚合" not in content
