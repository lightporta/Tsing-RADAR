"""全局常量（六维主观评价键、院系颜色、排序指标）。

注意：六维特质键（TRAIT_KEYS）只用于学生匿名主观评价体系（advisor ratings），
客观雷达四维见 services/radar_chart.py 的 OBJECTIVE_DIMENSION_KEYS。
"""

# 六维主观评价顺序（与 advisor ratings 的 scores 字段一一对应）
TRAIT_KEYS = ["acumen", "network", "mentorship", "tolerance", "funding", "efficiency"]

# 排序支持的指标键（主观六维；客观维度不提供无证据排序）
SORT_METRICS = {"acumen", "network", "mentorship", "tolerance", "funding", "efficiency"}

# 院系 → 散点颜色（hex）
DEPT_COLORS = {
    "自动化系": "#4E79A7",
    "计算机科学与技术系": "#F28E2B",
    "电子工程系": "#E15759",
    "机械工程系": "#76B7B2",
    "材料学院": "#59A14F",
    "精密仪器系": "#EDC948",
}
DEPT_FALLBACK_COLOR = "#76B7B2"
