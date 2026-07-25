from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, Any
import json
import re
import math
import hashlib
import uuid
import os
import asyncio
import httpx
import uvicorn

app = FastAPI(title="Tsing-RADAR 清华导师推荐智能体 v2")

# ===== CORS 配置（保留兼容，加入 null 与本地预览域）=====
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "null",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 启动时加载导师库 =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "mentors.json"), "r", encoding="utf-8") as f:
    DEFAULT_MENTORS = json.load(f)

# ===== 全局内存存储 =====
RECRUITMENTS_STORE: list[dict] = []          # 通过 POST 发布的招募
FEEDBACK_STORE: list[dict] = []               # 用户反馈
APPLICATIONS_STORE: list[dict] = []           # 简历投递
QUESTIONNAIRE_SESSIONS: dict[str, list] = {}  # 问卷会话 session_id -> messages
MODEL_WEIGHTS: Optional[dict] = None          # 训练产出的模型权重，供 /api/match 推理加权

# ===== 常量 =====
# 排序支持的指标键（六维雷达 + 热门指数）
SORT_METRICS = {"acumen", "network", "mentorship", "tolerance", "funding", "efficiency", "popularity"}

# 六维雷达特质顺序（与 radar_traits 字段一一对应）
TRAIT_KEYS = ["acumen", "network", "mentorship", "tolerance", "funding", "efficiency"]

# 院系 → 散点颜色（hex）
DEPT_COLORS = {
    "自动化系": "#4E79A7",
    "计算机科学与技术系": "#F28E2B",
    "电子工程系": "#E15759",
}
DEPT_FALLBACK_COLOR = "#76B7B2"

# LLM API Key（启动时读取环境变量）
GLM_API_KEY = os.environ.get("GLM_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


# ===== Pydantic 请求模型 =====
class MatchRequest(BaseModel):
    # v1/chat/completions 与 /api/match 共用；portrait/weight 为 v2 扩展
    interest: str
    portrait: Optional[dict] = None
    weight: Optional[dict] = None


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMChatRequest(BaseModel):
    messages: list[LLMMessage]
    session_id: Optional[str] = None


class LLMEmbeddingRequest(BaseModel):
    text: str


class RecruitmentCreateRequest(BaseModel):
    publisher_id: str
    type: str
    title: str
    req: str
    major: str
    deadline: str
    is_urgent: bool = False


class ResumeGenerateRequest(BaseModel):
    student_name: str
    dept: str
    email: str
    phone: str
    projects: list[Any] = []
    awards: list[Any] = []
    positions: list[Any] = []
    target_advisor: Optional[str] = None


class ResumeSubmitRequest(BaseModel):
    recruit_id: str
    student_id: str
    resume_id: str


class FeedbackRequest(BaseModel):
    student_id: str
    advisor_id: str
    rating: int  # 1 正向 / -1 负向
    comment: Optional[str] = None


class TrainTriggerRequest(BaseModel):
    admin_token: str


# ===== 辅助函数 =====
def _mentor_traits_list(mentor: dict) -> list[float]:
    """取出导师六维雷达特质，按固定顺序返回 0-100 数值列表。"""
    rt = mentor.get("radar_traits", {}) or {}
    return [float(rt.get(k, 0)) for k in TRAIT_KEYS]


def compute_synergy(student_weights, mentor_traits):
    """Synergy Score：学生需求多边形 ∩ 导师特质多边形面积 / 学生多边形面积。

    极坐标六维多边形 + Shoelace 面积，交集用每维 min 近似。
    """
    angles = [i * 60 for i in range(6)]  # 0,60,120,180,240,300

    def to_cart(vals):
        return [(v * math.cos(math.radians(a)), v * math.sin(math.radians(a))) for v, a in zip(vals, angles)]

    def area(poly):
        n = len(poly)
        return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2

    s_area = area(to_cart(student_weights))
    inter_vals = [min(s, m) for s, m in zip(student_weights, mentor_traits)]
    inter_area = area(to_cart(inter_vals))
    return round(inter_area / s_area * 100, 1) if s_area > 0 else 0


def _keyword_score(mentor: dict, keywords: list[str]) -> int:
    """关键词匹配得分：field 命中 +10，tags 命中 +8。"""
    field = mentor.get("field", "").lower()
    tags = [t.lower() for t in mentor.get("tags", [])]
    score = 0
    for k in keywords:
        if len(k) < 2:
            continue
        if k in field:
            score += 10
        if any(k in tag for tag in tags):
            score += 8
    return score


def _hash_embedding(text: str, dim: int = 128) -> list[float]:
    """无 API Key 时基于文本 hash 生成 128 维伪向量（确定性，范围 -1~1）。"""
    vec = []
    for i in range(dim):
        chunk = hashlib.sha256(f"{text}#{i}".encode("utf-8")).digest()
        val = int.from_bytes(chunk[:4], "big") / 0xFFFFFFFF  # 0~1
        vec.append(round(val * 2 - 1, 4))
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def _normalize_weights(weight: dict) -> list[float]:
    """把六维权重 dict 归一为 0-100 顺序列表（缺失维度补 50）。"""
    vals = [float(weight.get(k, 50)) for k in TRAIT_KEYS]
    max_v = max(vals) if vals else 0
    # 若输入是 0~1 范围，则放大到 0~100
    if max_v <= 1.0:
        vals = [v * 100 for v in vals]
    return vals


def _build_reason(mentor: dict, kw_score: int, synergy: float) -> str:
    """生成一句话推荐理由。"""
    name = mentor.get("name", "")
    field = mentor.get("field", "")
    top_trait_idx = max(range(6), key=lambda i: _mentor_traits_list(mentor)[i])
    trait_cn = {
        "acumen": "学术洞察", "network": "学术网络", "mentorship": "指导用心",
        "tolerance": "氛围包容", "funding": "经费充足", "efficiency": "出成果快",
    }[TRAIT_KEYS[top_trait_idx]]
    if kw_score > 0:
        return f"{name}：研究方向「{field}」与你的兴趣高度契合，{trait_cn}突出。"
    return f"{name}：{trait_cn}突出，研究方向「{field}」，可作为潜在备选。"


# ===== 本地 stub 问卷追问 =====
_STUB_RULES = [
    (("nlp", "自然语言", "文本", "对话系统", "语言模型", "llm"),
     "你提到对 NLP 感兴趣，能说说你具体对哪个子方向更感兴趣吗？比如机器翻译、对话系统还是知识图谱？"),
    (("cv", "计算机视觉", "图像", "视觉", "目标检测", "分割"),
     "关于计算机视觉，你更偏向基础研究（如检测、分割、生成）还是应用落地（如自动驾驶、工业质检）？"),
    (("机器人", "robot", "控制", "机械臂", "运动"),
     "机器人方向上，你更想做运动控制与感知融合，还是强化学习/仿真训练？"),
    (("机器学习", "深度学习", "ml", "dl", "模型", "算法"),
     "在机器学习里，你更看重理论（优化、泛化）还是工程（系统、大模型训练）？"),
    (("系统", "分布式", "数据库", "编译", "操作系统", "体系结构"),
     "系统方向你的偏好是偏底层（编译/体系结构）还是偏上层（分布式/数据库）？"),
    (("信号", "通信", "射频", "雷达", "电磁", "天线"),
     "通信与信号方向，你更想做硬件（射频/天线）还是算法（估计/检测/信号处理）？"),
    (("芯片", "eda", "集成电路", "半导体", "verilog"),
     "芯片方向你倾向数字前端/后端，还是模拟/射频电路设计？"),
    (("科研", "论文", "学术", "phd", "读博"),
     "你更看重导师的学术指导（手把手带）还是给资源让你自由探索？"),
   (("实习", "工业", "企业", "就业", "工作"),
     "你希望导师项目偏校企合作（便于实习就业）还是偏国家级科研（便于发论文/读博）？"),
]


def _stub_reply(messages: list[LLMMessage]) -> str:
    """基于关键词的本地模拟追问；判定完成时追加 RECOMMEND_READY。"""
    last = messages[-1].content if messages else ""
    last_lower = last.lower()

    # 完成/推荐信号：且已有至少 2 轮用户回答
    completion_signals = ["推荐", "够了", "完了", "可以了", "结束", "match", "recommend", "开始匹配", "好了", "差不多了"]
    user_turns = sum(1 for m in messages if m.role == "user")
    if any(s in last_lower for s in completion_signals) and user_turns >= 2:
        return ("感谢你的回答！我已经对你的画像有了清晰认识，"
                "正在为你匹配最合适的导师，请稍候查看推荐结果。RECOMMEND_READY")

    # 关键词规则命中
    for keys, reply in _STUB_RULES:
        if any(k in last_lower for k in keys):
            return reply

    # 兜底追问
    fallbacks = [
        "除了你提到的方向，你对导师的指导风格（手把手 vs 自由探索）有什么偏好吗？",
        "你更看重科研氛围包容度，还是出成果的效率？",
        "你希望导师的项目经费/资源充足，还是更在意学术网络与人脉？",
        "你对国有机构方向（航天/军工/国家实验室）和私营方向（互联网/初创）有偏好吗？",
        "能具体说说你最看重的科研特质吗？比如学术洞察、学术网络、指导用心、氛围包容、经费、效率。",
    ]
    return fallbacks[user_turns % len(fallbacks)]


# ===== LLM 调用（GLM 优先，DeepSeek 兜底）=====
_LLM_SYSTEM_PROMPT = (
    "你是 Tsing-RADAR 智能问卷助手，通过多轮对话挖掘学生对研究方向、科研风格、行业偏好的需求。"
    "每轮提出一个聚焦追问，参考高考志愿测评形式深入挖掘。"
    "当你认为已收集足够信息（通常 3-5 轮）可做导师推荐时，在回复末尾追加 \"RECOMMEND_READY\" 标记。"
)


async def _llm_complete(messages: list[LLMMessage]) -> Optional[str]:
    """调用 LLM 获取完整回复文本；GLM 优先，失败 fallback DeepSeek；均失败返回 None。"""
    payload_messages = [{"role": "system", "content": _LLM_SYSTEM_PROMPT}]
    payload_messages += [{"role": m.role, "content": m.content} for m in messages]

    if GLM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                    headers={"Authorization": f"Bearer {GLM_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "glm-4-flash", "messages": payload_messages, "stream": False},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass  # 降级到 DeepSeek

    if DEEPSEEK_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "deepseek-chat", "messages": payload_messages, "stream": False},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass  # 降级到本地 stub

    return None


async def _embed_text(text: str) -> list[float]:
    """文本向量化：优先 GLM embedding，失败/无 key 返回 hash 128 维伪向量。"""
    if GLM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://open.bigmodel.cn/api/paas/v4/embeddings",
                    headers={"Authorization": f"Bearer {GLM_API_KEY}", "Content-Type": "application/json"},
                    json={"model": "embedding-3", "input": text},
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
        except Exception:
            pass
    return _hash_embedding(text, 128)


# ============================================================
# 1. 保留 v1 兼容接口
# ============================================================
@app.get("/v1/models")
def models():
    """返回模型列表（清小搭兼容）。"""
    return {"object": "list", "data": [{"id": "tsing-radar-v1", "object": "model"},
                                      {"id": "tsing-radar-v2", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat(req: MatchRequest):
    """清小搭兼容接口：保留关键词匹配。"""
    user_input = req.interest.lower().strip()
    keywords = re.split(r"[\s,，、]+", user_input)
    matched = []
    for m in DEFAULT_MENTORS:
        if _keyword_score(m, keywords) > 0:
            matched.append(m)
    # 不足 5 条随机补充
    import random
    pool = [x for x in DEFAULT_MENTORS if x not in matched]
    random.shuffle(pool)
    matched += pool[: max(0, 5 - len(matched))]
    matched = matched[:5]
    return {
        "choices": [
            {"message": {"role": "assistant", "content": json.dumps(matched, ensure_ascii=False)}}
        ]
    }


@app.get("/api/mentors")
def get_all_mentors():
    """返回扩展后的导师数据（含 radar_traits/popularity/sector/projects/recruitments 等新字段）。"""
    return {"data": DEFAULT_MENTORS}


# ============================================================
# 2. v2 接口
# ============================================================
@app.get("/api/mentors/sort")
def sort_mentors(metric: str):
    """按指标降序排序导师。metric ∈ 六维雷达指标 + popularity。"""
    if metric not in SORT_METRICS:
        raise HTTPException(status_code=400, detail=f"不支持的指标: {metric}，支持: {sorted(SORT_METRICS)}")

    def metric_value(m: dict) -> float:
        if metric == "popularity":
            return float(m.get("popularity", 0))
        return float((m.get("radar_traits", {}) or {}).get(metric, 0))

    sorted_data = sorted(DEFAULT_MENTORS, key=metric_value, reverse=True)
    return {"data": sorted_data, "metric": metric}


@app.get("/api/scatter")
def scatter():
    """返回散点图数据：x=popularity, y=sector(0=国,1=私), color 按院系分配。"""
    points = []
    for m in DEFAULT_MENTORS:
        dept = m.get("dept", "")
        points.append({
            "name": m.get("name", ""),
            "x": float(m.get("popularity", 0)),
            "y": 0 if m.get("sector", "国") == "国" else 1,
            "color": DEPT_COLORS.get(dept, DEPT_FALLBACK_COLOR),
            "dept": dept,
        })
    return {"data": points}


@app.post("/api/v1/llm/chat")
async def llm_chat(req: LLMChatRequest):
    """LLM 多轮对话问卷：GLM 优先、DeepSeek 兜底、无 key 走本地 stub；SSE 流式响应。"""
    # 维护会话历史
    session_id = req.session_id or str(uuid.uuid4())
    history = QUESTIONNAIRE_SESSIONS.setdefault(session_id, [])
    # 合并最新消息到会话历史
    for m in req.messages:
        history.append({"role": m.role, "content": m.content})

    async def sse_stream():
        # 获取完整回复（LLM 或 stub）
        reply = await _llm_complete(req.messages)
        if reply is None:
            reply = _stub_reply(req.messages)

        # 检测完成标记，从可见文本中剥离
        recommend_ready = "RECOMMEND_READY" in reply
        visible = reply.replace("RECOMMEND_READY", "").strip()

        # 记录助手回复到会话历史
        QUESTIONNAIRE_SESSIONS[session_id].append({"role": "assistant", "content": visible})

        # 分块流式输出（模拟 token 级 SSE）
        chunks = [visible[i:i + 8] for i in range(0, len(visible), 8)] or [""]
        for chunk in chunks:
            payload = {"delta": chunk, "role": "assistant"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)
        # 终止帧
        yield f"data: {json.dumps({'delta': '', 'finish': True, 'recommend_ready': recommend_ready, 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@app.post("/api/v1/llm/embeddings")
async def llm_embeddings(req: LLMEmbeddingRequest):
    """文本向量化；无 API key 返回基于文本 hash 的 128 维伪向量。"""
    vec = await _embed_text(req.text)
    return {"data": vec}


@app.post("/api/match")
async def match_mentor(req: MatchRequest):
    """升级版匹配：关键词基础分 + 画像向量契合度 + 六维 Synergy Score，输出 top 5。"""
    user_input = req.interest.lower().strip()
    keywords = [k for k in re.split(r"[\s,，、]+", user_input) if k]

    # 预计算画像向量（若有 portrait）
    portrait_vec = None
    if req.portrait:
        portrait_text = json.dumps(req.portrait, ensure_ascii=False)
        portrait_vec = await _embed_text(portrait_text)

    # 预计算每名导师的 field+tags 文本向量（与画像同维度）
    mentor_vecs = None
    if portrait_vec is not None:
        mentor_vecs = {}
        for m in DEFAULT_MENTORS:
            txt = m.get("field", "") + " " + " ".join(m.get("tags", []))
            mentor_vecs[m.get("name", "")] = await _embed_text(txt)

    # 六维权重（若有）
    student_weights = _normalize_weights(req.weight) if req.weight else None

    scored = []
    for m in DEFAULT_MENTORS:
        kw = _keyword_score(m, keywords)
        # 基础分：关键词 0-60 区间映射
        kw_base = min(60.0, kw * 3.0)
        # 画像契合度加分：余弦相似度 * 40
        cos = 0.0
        cos_base = 0.0
        if portrait_vec is not None and mentor_vecs is not None:
            cos = _cosine(portrait_vec, mentor_vecs[m.get("name", "")])
            cos_base = max(0.0, cos) * 40.0
        # 训练权重加权（若已触发训练）：对关键词/画像分按 MODEL_WEIGHTS 系数调整
        if MODEL_WEIGHTS is not None:
            kw_base *= MODEL_WEIGHTS.get("keyword_factor", 1.0)
            cos_base *= MODEL_WEIGHTS.get("portrait_factor", 1.0)
        base = kw_base + cos_base
        # 兜底：无任何信号时给 mentor 自身 score 一个比例
        if kw == 0 and portrait_vec is None and student_weights is None:
            base = max(base, m.get("score", 50) * 0.4)
        score = round(min(100.0, base), 1)

        # Synergy（仅有六维权重时计算）
        synergy = 0.0
        if student_weights is not None:
            synergy = compute_synergy(student_weights, _mentor_traits_list(m))

        scored.append({
            **m,
            "score": score,
            "reason": _build_reason(m, kw, synergy),
            "synergy": synergy,
        })

    # 排序：先按 score 降序；score 相同按 synergy 降序
    scored.sort(key=lambda x: (x["score"], x["synergy"]), reverse=True)
    return {"data": scored[:5]}


@app.get("/api/recruitments")
def list_recruitments(urgent: Optional[bool] = None):
    """聚合所有导师的招募信息；?urgent=true 只返回急招。"""
    result = []
    # 1) 来自 mentors.json 的静态招募
    for m in DEFAULT_MENTORS:
        for r in m.get("recruitments", []) or []:
            if urgent is True and not r.get("is_urgent", False):
                continue
            result.append({
                "recruit_id": f"static_{m.get('name', '')}_{r.get('title', '')[:6]}",
                "publisher_name": m.get("name", ""),
                "publisher_type": "advisor",
                "type": r.get("type", ""),
                "title": r.get("title", ""),
                "req": r.get("req", ""),
                "major": r.get("major", ""),
                "deadline": r.get("deadline", ""),
                "is_urgent": bool(r.get("is_urgent", False)),
                "dept": m.get("dept", ""),
            })
    # 2) 通过 POST 发布的招募（内存）
    for r in RECRUITMENTS_STORE:
        if urgent is True and not r.get("is_urgent", False):
            continue
        result.append({
            "recruit_id": r.get("recruit_id", ""),
            "publisher_name": r.get("publisher_name", r.get("publisher_id", "")),
            "publisher_type": r.get("publisher_type", "advisor"),
            "type": r.get("type", ""),
            "title": r.get("title", ""),
            "req": r.get("req", ""),
            "major": r.get("major", ""),
            "deadline": r.get("deadline", ""),
            "is_urgent": bool(r.get("is_urgent", False)),
            "dept": r.get("dept", ""),
        })
    return {"data": result}


@app.post("/api/recruitments")
def publish_recruitment(req: RecruitmentCreateRequest):
    """发布招募（内存存储）。publisher_id 视为导师名，自动查表补全 dept/type。"""
    # 查找导师以补全院系与发布者姓名
    mentor = next((m for m in DEFAULT_MENTORS if m.get("name") == req.publisher_id), None)
    dept = mentor.get("dept", "") if mentor else ""
    publisher_name = mentor.get("name", req.publisher_id) if mentor else req.publisher_id

    recruit_id = f"pub_{uuid.uuid4().hex[:8]}"
    record = {
        "recruit_id": recruit_id,
        "publisher_id": req.publisher_id,
        "publisher_name": publisher_name,
        "publisher_type": "advisor",
        "type": req.type,
        "title": req.title,
        "req": req.req,
        "major": req.major,
        "deadline": req.deadline,
        "is_urgent": req.is_urgent,
        "dept": dept,
    }
    RECRUITMENTS_STORE.append(record)
    return {"recruit_id": recruit_id, "status": "published"}


@app.post("/api/resume/generate")
async def resume_generate(req: ResumeGenerateRequest):
    """调用 LLM 生成打磨简历正文；无 key 用模板拼接。"""
    # 构造结构化输入
    projects_text = "\n".join(
        [f"- {p.get('name', p) if isinstance(p, dict) else p}" for p in req.projects] or ["（暂无项目）"]
    )
    awards_text = "\n".join([f"- {a}" for a in req.awards] or ["（暂无奖项）"])
    positions_text = "\n".join([f"- {p}" for p in req.positions] or ["（暂无职务）"])
    target_line = f"（目标导师：{req.target_advisor}）" if req.target_advisor else ""

    # 尝试 LLM 打磨
    if GLM_API_KEY or DEEPSEEK_API_KEY:
        prompt = (
            f"请把以下学生信息打磨成一份简洁有力的中文简历正文（用于申请清华导师{target_line}），"
            f"包含教育背景、项目经历、获奖、担任职务。姓名：{req.student_name}，院系：{req.dept}，"
            f"邮箱：{req.email}，电话：{req.phone}。\n项目经历：\n{projects_text}\n获奖：\n{awards_text}\n职务：\n{positions_text}"
        )
        msgs = [LLMMessage(role="user", content=prompt)]
        polished = await _llm_complete(msgs)
        if polished:
            return {"polished_text": polished, "title": f"{req.student_name}-个人简历"}

    # 模板兜底
    template = (
        f"{req.student_name} | {req.dept} | {req.email} | {req.phone}\n\n"
        f"【项目经历】\n{projects_text}\n\n"
        f"【获奖荣誉】\n{awards_text}\n\n"
        f"【担任职务】\n{positions_text}\n"
        + (f"\n【投递目标】{req.target_advisor}\n" if req.target_advisor else "")
    )
    return {"polished_text": template, "title": f"{req.student_name}-个人简历"}


@app.post("/api/resume/submit")
def resume_submit(req: ResumeSubmitRequest):
    """投递简历至招募方（内存存储）。"""
    app_id = f"app_{uuid.uuid4().hex[:8]}"
    APPLICATIONS_STORE.append({
        "app_id": app_id,
        "recruit_id": req.recruit_id,
        "student_id": req.student_id,
        "resume_id": req.resume_id,
        "status": "待处理",
    })
    return {"app_id": app_id, "status": "待处理"}


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    """提交评价（点赞/踩 + 评论），存入全局列表。"""
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating 必须为 1 或 -1")
    feedback_id = f"fb_{uuid.uuid4().hex[:8]}"
    FEEDBACK_STORE.append({
        "feedback_id": feedback_id,
        "student_id": req.student_id,
        "advisor_id": req.advisor_id,
        "rating": req.rating,
        "comment": req.comment,
    })
    return {"feedback_id": feedback_id, "status": "recorded"}


def _sigmoid(z: float) -> float:
    """数值稳定的 sigmoid。"""
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


@app.post("/api/train/trigger")
def train_trigger(req: TrainTriggerRequest):
    """触发模型训练（管理员）：聚合反馈与问卷样本，训练线性 stub，输出训练日志。

    实现：4 维特征 [偏置, 评分信号, 文本信号, 问卷信号] + sigmoid 单元 + MSE 损失 + 批量梯度下降。
    训练产物 MODEL_WEIGHTS 供 /api/match 推理时对关键词/画像分加权调整。
    """
    global MODEL_WEIGHTS
    if req.admin_token != "admin":
        raise HTTPException(status_code=403, detail="admin_token 无效")

    # 1) 聚合训练样本（反馈 + 问卷会话）
    samples: list[tuple[list[float], float]] = []
    for fb in FEEDBACK_STORE:
        # 特征：[偏置, rating(±1), 是否有评论, 0(非问卷)]
        feat = [1.0, float(fb.get("rating", 0)), 1.0 if fb.get("comment") else 0.0, 0.0]
        label = 1.0 if fb.get("rating", 0) > 0 else 0.0
        samples.append((feat, label))
    for sid, msgs in QUESTIONNAIRE_SESSIONS.items():
        user_turns = sum(1 for m in msgs if m.get("role") == "user")
        total_turns = len(msgs)
        # 特征：[偏置, 用户轮数/10, 总消息/20, 1(问卷)]
        feat = [1.0, user_turns / 10.0, total_turns / 20.0, 1.0]
        label = 1.0  # 完成问卷视为正样本
        samples.append((feat, label))

    samples_count = len(samples)
    epochs = 20
    lr = 0.05
    dim = 4
    weights = [0.0] * dim
    final_loss = 0.0

    # 2) 纯 Python 梯度下降训练（前向 + MSE 损失 + 反向）
    if samples_count > 0:
        for _epoch in range(epochs):
            total_loss = 0.0
            grads = [0.0] * dim
            for feat, label in samples:
                z = sum(w * x for w, x in zip(weights, feat))
                pred = _sigmoid(z)
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

    # 3) 将训练权重映射为 /api/match 推理加权系数，存入全局 MODEL_WEIGHTS
    keyword_factor = max(0.5, min(2.0, 1.0 + weights[1]))    # 评分信号 → 关键词加权
    portrait_factor = max(0.5, min(2.0, 1.0 + weights[2]))   # 文本信号 → 画像加权
    synergy_factor = max(0.5, min(2.0, 1.0 + weights[3]))    # 问卷信号 → 协同加权
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
