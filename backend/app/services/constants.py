"""全局常量（六维雷达键、院系颜色、排序指标）。"""

# 六维雷达特质顺序（与 radar_traits 字段一一对应）
TRAIT_KEYS = ["acumen", "network", "mentorship", "tolerance", "funding", "efficiency"]

# 排序支持的指标键
SORT_METRICS = {"acumen", "network", "mentorship", "tolerance", "funding", "efficiency", "popularity"}

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
