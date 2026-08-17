import type { EChartsOption } from 'echarts'
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
  values: number[]
  color: string // line color
  areaColor: string // fill color
  lineType?: 'solid' | 'dashed' | 'dotted'
  lineWidth?: number
}

/** 构造雷达图 option */
export function buildRadarOption(
  series: RadarSeries[],
  options: { showAxisLabel?: boolean; showLegend?: boolean; radius?: string | number } = {},
): EChartsOption {
  const { showAxisLabel = true, showLegend = true, radius = '65%' } = options

  return {
    tooltip: { trigger: 'item' },
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
