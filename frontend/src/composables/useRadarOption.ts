import type { EChartsOption } from 'echarts'
import type { TopLevelFormatterParams } from 'echarts/types/dist/shared'
import type { RadarTraits } from '@/types/advisor'
import { TRAITS } from '@/types/advisor'
import type { TraitKey } from '@/types/advisor'

// =====================================================================
// 雷达图 ECharts Option 构造器（迷你雷达 / 大雷达共用）
// 文档 §3.4 / §3.5：
//   - 蓝色半透明填充：学生需求轮廓
//   - 橙色实线填充：导师实际特质
// =====================================================================

const INDICATORS = TRAITS.map((t) => ({ name: t.label, max: 100 }))

export interface RadarSeries {
  name: string
  values: (number | null)[] // null = 该维不画线（如样本不足）
  color: string // line color
  areaColor: string // fill color
  lineType?: 'solid' | 'dashed' | 'dotted'
  lineWidth?: number
  /** 悬停该系列时的固定提示文案（如学生评价的主观性声明） */
  tooltipText?: string
}

/** 构造雷达图 option */
export function buildRadarOption(
  series: RadarSeries[],
  options: { showAxisLabel?: boolean; showLegend?: boolean; radius?: string | number } = {},
): EChartsOption {
  const { showAxisLabel = true, showLegend = true, radius = '65%' } = options

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
      indicator: INDICATORS,
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
          areaStyle: { color: s.areaColor },
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

/** 学生需求雷达系列（半透明蓝） */
export const STUDENT_SERIES_NAME = '学生需求'
export const ADVISOR_SERIES_NAME = '导师特质'
export const ADVISOR_DEFAULT_SERIES_NAME = '导师基准（无评分数据）'
/** 学生评价雷达第三系列（绿色虚线 = 主观评价，与官方事实实线区分） */
export const RATING_SERIES_NAME = '学生评价'

export const STUDENT_RADAR = {
  color: '#409EFF',
  areaColor: 'rgba(64, 158, 255, 0.2)',
}

/** 有真实证据数据时的导师雷达颜色（深色实线） */
export const ADVISOR_RADAR = {
  color: '#FF9500',
  areaColor: 'rgba(255, 149, 0, 0.6)',
}

/** 无数据时的默认基准雷达颜色（浅色虚线，值=50） */
export const ADVISOR_DEFAULT_RADAR = {
  color: '#C0C4CC',
  areaColor: 'rgba(192, 196, 204, 0.15)',
  lineType: 'dashed' as const,
  lineWidth: 1.5,
}

/** 学生评价雷达颜色（绿 #67c23a，固定虚线：主观 ≠ 事实） */
export const RATING_RADAR = {
  color: '#67c23a',
  areaColor: 'rgba(103, 194, 58, 0.25)',
  lineType: 'dashed' as const,
}

/** 单维样本量低于该值时该维不画线（隐私与抗压评阈值） */
export const RATING_MIN_DIMENSION_N = 3

/** 默认六维基准值（无证据数据时使用） */
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
