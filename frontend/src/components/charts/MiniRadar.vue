<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useEChart } from '@/composables/useEChart'
import {
  buildRadarOption,
  defaultObjectiveArray,
  objectiveToArray,
  OBJECTIVE_SERIES_NAME,
  OBJECTIVE_BASELINE_SERIES_NAME,
  OBJECTIVE_RADAR,
  OBJECTIVE_DEFAULT_RADAR,
  OBJECTIVE_RADAR_INDICATORS,
  type RadarSeries,
} from '@/composables/useRadarOption'
import type { ObjectiveRadar } from '@/types/advisor'

// =====================================================================
// 迷你客观雷达图（卡片内，80px，无坐标轴标签）
// 橙实线 = 已审核客观证据（objective_radar，四维）
// 无数据 = 灰色虚线 50 视觉基准（无数据、非评分）
// 客观指标与学生主观评价严格分离，主观数据不在本图展示
// =====================================================================

const props = withDefaults(
  defineProps<{
    objectiveRadar?: ObjectiveRadar
    size?: number
  }>(),
  {
    size: 80,
    objectiveRadar: undefined,
  },
)

const el = ref<HTMLElement | null>(null)

const hasObjectiveEvidence = computed(() => {
  if (!props.objectiveRadar) return false
  const values = Object.values(props.objectiveRadar)
  return values.length === 4 && values.every((v) => typeof v === 'number' && v >= 0)
})

const option = computed(() => {
  const series: RadarSeries[] = []

  if (hasObjectiveEvidence.value && props.objectiveRadar) {
    // 有已审核客观证据：橙色实线
    series.push({
      name: OBJECTIVE_SERIES_NAME,
      values: objectiveToArray(props.objectiveRadar),
      ...OBJECTIVE_RADAR,
      lineType: 'solid' as const,
      lineWidth: 2,
    })
  } else {
    // 无数据：视觉基准 50，浅色虚线（无数据、非评分）
    series.push({
      name: OBJECTIVE_BASELINE_SERIES_NAME,
      values: defaultObjectiveArray(),
      ...OBJECTIVE_DEFAULT_RADAR,
    })
  }

  return buildRadarOption(series, {
    showAxisLabel: false,
    showLegend: false,
    radius: '62%',
    indicators: OBJECTIVE_RADAR_INDICATORS,
  })
})

const { refresh } = useEChart(el, () => option.value)
watch(option, () => refresh(), { deep: true })
</script>

<template>
  <div ref="el" class="mini-radar" :style="{ width: size + 'px', height: size + 'px' }" />
</template>

<style scoped lang="scss">
.mini-radar {
  flex-shrink: 0;
}
</style>
