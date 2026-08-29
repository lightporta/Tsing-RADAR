"""兴趣探索服务：活动兴趣题（研究场景）→ 候选研究方向。

题型思路参考 O*NET Interest Profiler 的活动题（选择"喜欢做什么"而非
"想研究什么"），改写为研究场景，降低研究方向不明确用户的回答门槛。

确定性约束（修改说明 §6）：
- 候选方向完全由静态映射表计算（命中活动数排序），不含任何模型调用；
- GLM 仅可作为前端表达增强，绝不改变本模块的输出结果；
- 用户选定候选方向后经 apply 写回画像 research_interests，
  走既有匹配管线继续推荐导师。
"""

from __future__ import annotations

from app.schemas.interest_exploration import (
    ActivityOption,
    ActivityQuestionResponse,
    DirectionCandidate,
    InterestExplorationSuggestionResponse,
)

# =====================================================================
# 活动兴趣题（研究场景，多选；键为稳定标识，前端不做自由输入）
# =====================================================================

ACTIVITY_OPTIONS: list[ActivityOption] = [
    ActivityOption(
        value="data_patterns",
        label="从大量数据里找规律",
        description="喜欢分析数据、发现模式、做预测和可视化",
    ),
    ActivityOption(
        value="build_devices",
        label="动手搭建和调试装置",
        description="喜欢操作实验设备、搭硬件、排查现场问题",
    ),
    ActivityOption(
        value="code_systems",
        label="写代码实现算法和系统",
        description="喜欢编程、把想法变成能运行的软件系统",
    ),
    ActivityOption(
        value="prove_theory",
        label="推导公式、证明命题",
        description="喜欢数学推理、理论建模、追根究底",
    ),
    ActivityOption(
        value="talk_people",
        label="访谈调研、理解真实的人",
        description="喜欢与人交流、做访谈或问卷、理解真实需求",
    ),
    ActivityOption(
        value="policy_social",
        label="研究社会问题与政策制度",
        description="关注公共议题、制度设计、社会运行逻辑",
    ),
    ActivityOption(
        value="life_health",
        label="观察生命现象、做医学实验",
        description="对生命科学、疾病与健康问题感兴趣",
    ),
    ActivityOption(
        value="design_create",
        label="设计产品、界面或创意作品",
        description="喜欢做设计、原型、创意表达与体验打磨",
    ),
]

_ACTIVITY_BY_VALUE = {option.value: option for option in ACTIVITY_OPTIONS}

# =====================================================================
# 候选研究方向池（静态映射：方向 → 触发活动键）
# =====================================================================

_DIRECTION_CANDIDATES: list[dict[str, object]] = [
    {
        "key": "ai_data",
        "label": "人工智能与数据科学",
        "description": (
            "研究机器学习、数据挖掘与智能系统的原理和应用，"
            "常见课题包括大模型、计算机视觉、推荐系统与数据分析。"
        ),
        "activities": ("data_patterns", "code_systems"),
    },
    {
        "key": "ics_hardware",
        "label": "集成电路与智能硬件",
        "description": (
            "研究芯片设计、电子系统与嵌入式智能硬件，"
            "覆盖数字/模拟集成电路、传感器与边缘计算设备。"
        ),
        "activities": ("build_devices", "code_systems"),
    },
    {
        "key": "robotics",
        "label": "机器人与智能制造",
        "description": (
            "研究机器人感知、控制与自动化产线，"
            "结合机械、电气与算法做能落地的智能装备。"
        ),
        "activities": ("build_devices", "code_systems", "design_create"),
    },
    {
        "key": "basic_science",
        "label": "数学与物理基础研究",
        "description": (
            "面向基础科学问题做理论推导与建模，"
            "包括基础数学、统计物理、量子信息等前沿方向。"
        ),
        "activities": ("prove_theory", "data_patterns"),
    },
    {
        "key": "biomed",
        "label": "生物医药与公共卫生",
        "description": (
            "研究疾病机理、药物开发、基因技术与人群健康，"
            "包含湿实验室实验与医学数据分析两类工作。"
        ),
        "activities": ("life_health", "data_patterns"),
    },
    {
        "key": "energy_env",
        "label": "能源与环境工程",
        "description": (
            "研究新能源、碳中和、污染治理与可持续发展技术，"
            "兼顾实验研究与工程系统设计。"
        ),
        "activities": ("build_devices", "life_health"),
    },
    {
        "key": "econ_policy",
        "label": "经济管理与公共政策",
        "description": (
            "研究经济运行、管理与政策评估，"
            "用数据与模型回答现实中的治理与商业问题。"
        ),
        "activities": ("policy_social", "talk_people"),
    },
    {
        "key": "social_humanity",
        "label": "社会科学与人文研究",
        "description": (
            "研究社会、心理、教育与历史文化现象，"
            "以访谈、民族志、文本分析等质性方法见长。"
        ),
        "activities": ("talk_people", "policy_social"),
    },
    {
        "key": "hci_design",
        "label": "人机交互与设计科学",
        "description": (
            "研究人与技术系统的交互方式与体验设计，"
            "覆盖可用性研究、交互设计与创意计算。"
        ),
        "activities": ("design_create", "talk_people", "code_systems"),
    },
    {
        "key": "materials",
        "label": "材料科学与工程",
        "description": (
            "研究新材料的合成、表征与性能调控，"
            "支撑芯片、能源、航空等领域的工程应用。"
        ),
        "activities": ("build_devices", "prove_theory"),
    },
]

_DIRECTION_BY_KEY = {str(item["key"]): item for item in _DIRECTION_CANDIDATES}

_QUESTION_PROMPT = (
    "还没想好具体研究方向也没关系——先选选看：下面这些研究场景里的活动，"
    "哪些是你做起来会感到有意思的？（可多选）"
)

_MAX_CANDIDATES = 5


class UnknownActivityError(ValueError):
    """请求中包含映射表之外的活动键。"""


class UnknownDirectionError(ValueError):
    """apply 请求中包含候选池之外的方向键。"""


def activity_question() -> ActivityQuestionResponse:
    """返回活动兴趣选择题定义（确定性静态内容）。"""
    return ActivityQuestionResponse(
        prompt=_QUESTION_PROMPT,
        options=list(ACTIVITY_OPTIONS),
        min_selections=1,
        max_selections=len(ACTIVITY_OPTIONS),
    )


def suggest_direction_candidates(
    activities: list[str],
) -> InterestExplorationSuggestionResponse:
    """从活动选择确定性推导候选研究方向。

    评分规则：每个方向计命中活动数（≥1 才入选），按命中数降序、
    方向池定义序稳定排序，最多返回 5 个。纯静态计算、无随机性。
    """
    unknown = [value for value in activities if value not in _ACTIVITY_BY_VALUE]
    if unknown:
        raise UnknownActivityError(
            "未知活动键：" + "、".join(unknown)
        )

    selected = set(activities)
    candidates: list[DirectionCandidate] = []
    for item in _DIRECTION_CANDIDATES:
        matched_keys = [
            key for key in item["activities"] if key in selected  # type: ignore[operator]
        ]
        if not matched_keys:
            continue
        candidates.append(
            DirectionCandidate(
                key=str(item["key"]),
                label=str(item["label"]),
                description=str(item["description"]),
                matched_activities=[
                    _ACTIVITY_BY_VALUE[key] for key in matched_keys
                ],
                match_score=len(matched_keys),
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.match_score, candidate.key))
    trimmed = candidates[:_MAX_CANDIDATES]
    if trimmed:
        hint = (
            "以下候选方向由你的活动选择按确定性映射生成（非模型推荐），"
            "可单选或多选后写回画像，继续推荐导师。"
        )
    else:
        hint = "暂无匹配的候选方向，可直接填写研究方向或继续访谈。"
    return InterestExplorationSuggestionResponse(
        candidates=trimmed,
        hint=hint,
    )


def direction_labels_for_keys(direction_keys: list[str]) -> list[str]:
    """把候选方向键解析为画像 research_interests 标签（保持选择顺序）。"""
    labels: list[str] = []
    for key in direction_keys:
        item = _DIRECTION_BY_KEY.get(key)
        if item is None:
            raise UnknownDirectionError(f"未知候选方向键：{key}")
        label = str(item["label"])
        if label not in labels:
            labels.append(label)
    return labels
