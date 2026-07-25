"""训练闭环服务（文档 §9）。

聚合反馈与问卷样本，训练线性 stub（sigmoid + MSE + 梯度下降），
产出 MODEL_WEIGHTS 供 /api/match 推理加权。
"""

import math
from typing import Any

from app.db.session import SessionLocal
from app.models.feedback import Feedback
from app.models.questionnaire_session import QuestionnaireSession

# 全局训练产出（开发期内存持有，生产期应持久化）
MODEL_WEIGHTS: dict[str, Any] | None = None


def sigmoid(z: float) -> float:
    """数值稳定的 sigmoid。"""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def collect_samples() -> list[tuple[list[float], float]]:
    """从数据库聚合训练样本（反馈 + 问卷会话）。

    表不存在或查询失败时优雅降级为空样本（保证开箱即用）。
    """
    samples: list[tuple[list[float], float]] = []
    db = SessionLocal()
    try:
        try:
            for fb in db.query(Feedback).all():
                feat = [1.0, float(fb.rating or 0), 1.0 if fb.comment else 0.0, 0.0]
                label = 1.0 if (fb.rating or 0) > 0 else 0.0
                samples.append((feat, label))

            for sess in db.query(QuestionnaireSession).all():
                msgs = sess.messages or []
                user_turns = sum(1 for m in msgs if m.get("role") == "user")
                total_turns = len(msgs)
                feat = [1.0, user_turns / 10.0, total_turns / 20.0, 1.0]
                samples.append((feat, 1.0))  # 完成问卷视为正样本
        except Exception:
            # 表未建或查询失败，降级为空样本
            samples = []
    finally:
        db.close()
    return samples


def train(epochs: int = 20, lr: float = 0.05) -> dict[str, Any]:
    """训练线性 stub 模型，返回训练日志与权重。"""
    global MODEL_WEIGHTS

    samples = collect_samples()
    samples_count = len(samples)
    dim = 4
    weights = [0.0] * dim
    final_loss = 0.0

    if samples_count > 0:
        for _epoch in range(epochs):
            total_loss = 0.0
            grads = [0.0] * dim
            for feat, label in samples:
                z = sum(w * x for w, x in zip(weights, feat))
                pred = sigmoid(z)
                err = pred - label
                total_loss += err * err
                for i in range(dim):
                    grads[i] += err * feat[i]
            for i in range(dim):
                weights[i] -= lr * grads[i] / samples_count
            final_loss = total_loss / samples_count
    else:
        # 无样本时给出合理默认权重，保证闭环可运行
        weights = [0.0, 1.0, 0.5, 0.3]
        final_loss = 0.0

    model_version = f"v2.{1 + samples_count // 10}"

    # 将训练权重映射为推理加权系数
    keyword_factor = max(0.5, min(2.0, 1.0 + weights[1]))
    portrait_factor = max(0.5, min(2.0, 1.0 + weights[2]))
    synergy_factor = max(0.5, min(2.0, 1.0 + weights[3]))
    MODEL_WEIGHTS = {
        "model_version": model_version,
        "keyword_factor": round(keyword_factor, 4),
        "portrait_factor": round(portrait_factor, 4),
        "synergy_factor": round(synergy_factor, 4),
        "raw_weights": [round(w, 4) for w in weights],
    }

    return {
        "status": "training_started",
        "samples_count": samples_count,
        "epochs": epochs,
        "final_loss": round(final_loss, 6),
        "model_version": model_version,
        "weights": MODEL_WEIGHTS,
    }


def get_model_weights() -> dict[str, Any] | None:
    """获取当前训练产出的权重（供 /api/match 推理加权）。"""
    return MODEL_WEIGHTS
