<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useEChart } from '@/composables/useEChart'
import {
  buildRadarOption,
  traitToArray,
  STUDENT_SERIES_NAME,
  ADVISOR_SERIES_NAME,
  STUDENT_RADAR,
  ADVISOR_RADAR,
} from '@/composables/useRadarOption'
import type { MatchedAdvisor } from '@/types/advisor'
import type { TraitKey } from '@/types/advisor'

// =====================================================================
// 大尺寸双轨雷达图（右栏选中导师时展示，文档 §3.5）
// =====================================================================

const props = defineProps<{
  advisor?: MatchedAdvisor
  studentWeights: Record<TraitKey, number>
}>()

const el = ref<HTMLElement | null>(null)

const option = computed(() => {
  const series = [
      {
        name: STUDENT_SERIES_NAME,
        values: traitToArray(props.studentWeights),
        ...STUDENT_RADAR,
      },
  ]
  if (props.advisor?.radar_traits) {
    series.push({
        name: ADVISOR_SERIES_NAME,
        values: traitToArray(props.advisor.radar_traits),
        ...ADVISOR_RADAR,
    })
  }
  return buildRadarOption(
    series,
    { showAxisLabel: true, showLegend: true, radius: '60%' },
  )
})

const { refresh } = useEChart(el, () => option.value)
watch(option, () => refresh(), { deep: true })
</script>

<template>
  <div ref="el" class="radar-large" />
</template>

<style scoped lang="scss">
.radar-large {
  width: 100%;
  height: 100%;
  min-height: 320px;
}
</style>
