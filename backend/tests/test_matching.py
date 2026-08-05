"""Synergy 算法单元测试（文档 §3.5）。"""

from app.services.matching import compute_synergy, keyword_score, normalize_weights, cosine_similarity, hash_embedding


def test_compute_synergy_full_match():
    """完全匹配：学生需求 = 导师特质，synergy 应为 100。"""
    weights = normalize_weights({"acumen": 80, "network": 80, "mentorship": 80, "tolerance": 80, "funding": 80, "efficiency": 80})
    traits = [80, 80, 80, 80, 80, 80]
    score = compute_synergy(weights, traits)
    assert score == 100.0


def test_compute_synergy_zero_match():
    """完全不匹配：导师特质全 0，synergy 应为 0。"""
    weights = normalize_weights({"acumen": 80, "network": 80, "mentorship": 80, "tolerance": 80, "funding": 80, "efficiency": 80})
    traits = [0, 0, 0, 0, 0, 0]
    score = compute_synergy(weights, traits)
    assert score == 0.0


def test_compute_synergy_partial():
    """部分匹配：导师特质略低于学生需求，synergy 应介于 0-100。"""
    weights = normalize_weights({"acumen": 100, "network": 100, "mentorship": 100, "tolerance": 100, "funding": 100, "efficiency": 100})
    traits = [50, 50, 50, 50, 50, 50]
    score = compute_synergy(weights, traits)
    assert 0 < score < 100


def test_keyword_score():
    """关键词评分：field 命中 +10，tags 命中 +8。"""
    mentor = {"field": "自然语言处理", "tags": ["NLP", "对话系统"]}
    score = keyword_score(mentor, ["自然语言", "对话"])
    # "自然语言" 命中 field (+10) + "对话" 命中 tag (+8) = 18
    assert score == 18


def test_normalize_weights_zero_to_one():
    """权重归一化：0-1 范围自动放大到 0-100。"""
    weights = normalize_weights({"acumen": 0.8, "network": 0.6, "mentorship": 0.9, "tolerance": 0.7, "funding": 0.5, "efficiency": 0.75})
    assert weights == [80.0, 60.0, 90.0, 70.0, 50.0, 75.0]


def test_normalize_weights_missing():
    """权重归一化：缺失维度补 50。"""
    weights = normalize_weights({"acumen": 80})
    assert weights == [80.0, 50.0, 50.0, 50.0, 50.0, 50.0]


def test_cosine_similarity_identical():
    """相同向量余弦相似度为 1。"""
    vec = [1.0, 2.0, 3.0]
    assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    """正交向量余弦相似度为 0。"""
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-6


def test_hash_embedding_deterministic():
    """相同文本生成的 hash 向量应确定性一致。"""
    vec1 = hash_embedding("测试文本", 64)
    vec2 = hash_embedding("测试文本", 64)
    assert vec1 == vec2
    assert len(vec1) == 64
    assert all(-1 <= v <= 1 for v in vec1)
