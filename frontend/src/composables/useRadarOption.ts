import type { EChartsOption } from 'echarts'
import type { TopLevelFormatterParams } from 'echarts/types/dist/shared'
import type { ObjectiveRadar, RadarTraits } from '@/types/advisor'
import { OBJECTIVE_DIMENSIONS, TRAITS } from '@/types/advisor'
import type { ObjectiveDimensionKey, TraitKey } from '@/types/advisor'

// =====================================================================
// 雷达图 ECharts Option 构造器（迷你雷达 / 大雷达共用）
// 客观与主观严格分离：
//   - 客观雷达（四维）：橙色实线，仅来自已审核公开证据（objective_radar）
//   - 主观雷达（六维）：学生需求（蓝）+ 学生匿名评价（绿虚线，n≥8 展示）
// 无数据时统一使用灰色虚线 50 视觉基准，标注"无数据、非评分"，
// 且基准值不参与匹配与推荐计算。
// =====================================================================

const TRAIT_INDICATORS = TRAITS.map((t) => ({ name: t.label, max: 100 }))
const OBJECTIVE_INDICATORS = OBJECTIVE_DIMENSIONS.map((d) => ({ name: d.label, max: 100 }))

export interface RadarSeries {
  name: string
  values: (number | null)[] // null = 该维不画线（如样本不足）
  color: string // line color（v3.1.5 起雷达为边缘线图勾连，无填充）
  lineType?: 'solid' | 'dashed' | 'dotted'
  lineWidth?: number
  /** 悬停该系列时的固定提示文案（如学生评价的主观性声明） */
  tooltipText?: string
}

/** 构造雷达图 option（indicators 决定维度集合：六维主观或四维客观） */
export function buildRadarOption(
  series: RadarSeries[],
  options: {
    showAxisLabel?: boolean
    showLegend?: boolean
    radius?: string | number
    indicators?: Array<{ name: string; max: number }>
  } = {},
): EChartsOption {
  const {
    showAxisLabel = true,
    showLegend = true,
    radius = '65%',
    indicators = TRAIT_INDICATORS,
  } = options

  // 系列级固定提示文案（主观评价声明等）；无任何文案时保持默认 tooltip
  const seriesTooltips = new Map(
    series
      .filter((s) => s.tooltipText)
      .map((s) => [s.name, s.tooltipText as string]),
  )

  return {
    tooltip:
      seriesTooltips.size > 0
        ? {
            trigger: 'item',
            formatter: (params: TopLevelFormatterParams) => {
              const item = Array.isArray(params) ? params[0] : params
              const name = item?.name ?? ''
              return seriesTooltips.get(name) ?? name
            },
          }
        : { trigger: 'item' },
    legend: showLegend
      ? {
          show: true,
          bottom: 0,
          data: series.map((s) => s.name),
          textStyle: { fontSize: 11, color: '#606266' },
          itemWidth: 14,
          itemHeight: 10,
        }
      : { show: false },
    radar: {
      indicator: indicators,
      radius,
      center: ['50%', '50%'],
      axisName: {
        show: showAxisLabel,
        color: '#606266',
        fontSize: showAxisLabel ? 11 : 0,
      },
      splitArea: {
        areaStyle: {
          color: ['rgba(64,158,255,0.02)', 'rgba(64,158,255,0.04)'],
        },
      },
      splitLine: { lineStyle: { color: '#dcdfe6' } },
      axisLine: { lineStyle: { color: '#dcdfe6' } },
    },
    series: [
      {
        type: 'radar',
        data: series.map((s) => ({
          name: s.name,
          value: s.values,
          lineStyle: {
            color: s.color,
            width: s.lineWidth ?? 2,
            type: s.lineType ?? 'solid',
          },
          // v3.1.5：边缘线图勾连，无 areaStyle 填充
          symbol: 'circle',
          itemStyle: { color: s.color },
        })),
      },
    ],
  }
}

/** 把 RadarTraits / weights dict 转成 6 维顺序数组（按 TRAITS 顺序） */
export function traitToArray(traits: RadarTraits | Record<TraitKey, number>): number[] {
  return TRAITS.map((t) => Number(traits[t.key] ?? 0))
}

/** 把 ObjectiveRadar dict 转成 4 维顺序数组（按 OBJECTIVE_DIMENSIONS 顺序） */
export function objectiveToArray(objective: ObjectiveRadar): number[] {
  return OBJECTIVE_DIMENSIONS.map((d) => Number(objective[d.key] ?? 0))
}

// ---------------------------------------------------------------- 系列名与配色

/** 学生需求雷达系列（蓝勾边，主观雷达第一系列） */
export const STUDENT_SERIES_NAME = '学生需求'
/** 客观证据雷达系列（橙实线，仅来自已审核公开证据） */
export const OBJECTIVE_SERIES_NAME = '客观证据（已审核）'
/** 无客观数据时的视觉基准系列（灰虚线 50，非评分） */
export const OBJECTIVE_BASELINE_SERIES_NAME = '视觉基准（无数据，非评分）'
/** 无学生评价时的六维视觉基准系列（灰虚线 50，非评分） */
export const TRAIT_BASELINE_SERIES_NAME = '视觉基准（无数据，非评分）'
/** 学生评价雷达系列（绿虚线 = 主观评价，与客观事实实线区分） */
export const RATING_SERIES_NAME = '学生评价'

export const STUDENT_RADAR = {
  color: '#409EFF',
}

/** 有已审核公开证据时的客观雷达颜色（橙色实线，与后端 SVG 渲染一致） */
export const OBJECTIVE_RADAR = {
  color: '#FF9500',
}

/** 无数据时的默认基准雷达颜色（浅色虚线，值=50，非评分） */
export const OBJECTIVE_DEFAULT_RADAR = {
  color: '#C0C4CC',
  lineType: 'dashed' as const,
  lineWidth: 1.5,
}

/** 兼容别名：旧代码中导师橙色系列的命名 */
export const ADVISOR_SERIES_NAME = OBJECTIVE_SERIES_NAME
export const ADVISOR_DEFAULT_SERIES_NAME = OBJECTIVE_BASELINE_SERIES_NAME
export const ADVISOR_RADAR = OBJECTIVE_RADAR
export const ADVISOR_DEFAULT_RADAR = OBJECTIVE_DEFAULT_RADAR

/** 学生评价雷达颜色（绿 #67c23a，固定虚线：主观 ≠ 事实） */
export const RATING_RADAR = {
  color: '#67c23a',
  lineType: 'dashed' as const,
}

/**
 * 单维样本量低于该值时该维不画线（隐私与防操纵阈值）。
 * 修改说明 §3：匿名主观雷达单维至少 8 份评价才展示。
 */
export const RATING_MIN_DIMENSION_N = 8

/** 默认六维基准值（无数据时视觉基准，非评分，不参与匹配计算） */
export const DEFAULT_TRAIT_VALUES: Record<string, number> = {
  acumen: 50,
  network: 50,
  mentorship: 50,
  tolerance: 50,
  funding: 50,
  efficiency: 50,
}

/** 生成默认基准雷达数据 */
export function defaultTraitArray(): number[] {
  return TRAITS.map(() => 50)
}

/** 生成客观四维默认基准数据（无数据时视觉基准，非评分） */
export function defaultObjectiveArray(): number[] {
  return OBJECTIVE_DIMENSIONS.map(() => 50)
}

/** 客观雷达 indicators（四维） */
export const OBJECTIVE_RADAR_INDICATORS = OBJECTIVE_INDICATORS

export type { ObjectiveDimensionKey }
