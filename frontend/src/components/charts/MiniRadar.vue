<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useEChart } from '@/composables/useEChart'
import {
  buildRadarOption,
  traitToArray,
  defaultTraitArray,
  STUDENT_SERIES_NAME,
  ADVISOR_SERIES_NAME,
  ADVISOR_DEFAULT_SERIES_NAME,
  STUDENT_RADAR,
  ADVISOR_RADAR,
  ADVISOR_DEFAULT_RADAR,
  type RadarSeries,
} from '@/composables/useRadarOption'
import type { RadarTraits } from '@/types/advisor'
import type { TraitKey } from '@/types/advisor'

// =====================================================================
// 迷你双轨雷达图（卡片内，80px，无坐标轴标签）
// 学生需求半透明蓝 + 导师特质实橙
// 无导师数据时：使用默认基准值50（浅灰虚线）
// =====================================================================

const props = withDefaults(
  defineProps<{
    advisorTraits?: RadarTraits
    studentWeights?: Record<TraitKey, number>
    size?: number
  }>(),
  {
    size: 80,
    advisorTraits: undefined,
    studentWeights: () => ({
      acumen: 0,
      network: 0,
      mentorship: 0,
      tolerance: 0,
      funding: 0,
      efficiency: 0,
    }),
  },
)

const el = ref<HTMLElement | null>(null)

const hasRealTraits = computed(() => {
  if (!props.advisorTraits) return false
  const values = Object.values(props.advisorTraits)
  return values.length === 6 && values.every((v) => typeof v === 'number' && v > 0)
})

const option = computed(() => {
  const series: RadarSeries[] = [
      {
        name: STUDENT_SERIES_NAME,
        values: traitToArray(props.studentWeights || ({} as Record<TraitKey, number>)),
        ...STUDENT_RADAR,
      },
  ]

  if (hasRealTraits.value && props.advisorTraits) {
    // 有真实数据：深色实线
    series.push({
      name: ADVISOR_SERIES_NAME,
      values: traitToArray(props.advisorTraits),
      ...ADVISOR_RADAR,
      lineType: 'solid' as const,
      lineWidth: 2,
    })
  } else {
    // 无数据：默认基准50，浅色虚线
    series.push({
      name: ADVISOR_DEFAULT_SERIES_NAME,
      values: defaultTraitArray(),
      ...ADVISOR_DEFAULT_RADAR,
    })
  }

  return buildRadarOption(
    series,
    { showAxisLabel: false, showLegend: false, radius: '62%' },
  )
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
