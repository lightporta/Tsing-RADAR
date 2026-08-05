<script setup lang="ts">
import { computed, ref } from 'vue'
import { useEChart } from '@/composables/useEChart'
import {
  buildRadarOption,
  traitToArray,
  STUDENT_SERIES_NAME,
  ADVISOR_SERIES_NAME,
  STUDENT_RADAR,
  ADVISOR_RADAR,
} from '@/composables/useRadarOption'
import type { RadarTraits } from '@/types/advisor'
import type { TraitKey } from '@/types/advisor'

// =====================================================================
// 迷你双轨雷达图（卡片内，80px，无坐标轴标签）
// 学生需求半透明蓝 + 导师特质实橙
// =====================================================================

const props = withDefaults(
  defineProps<{
    advisorTraits: RadarTraits
    studentWeights?: Record<TraitKey, number>
    size?: number
  }>(),
  {
    size: 80,
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

const option = computed(() =>
  buildRadarOption(
    [
      {
        name: STUDENT_SERIES_NAME,
        values: traitToArray(props.studentWeights || ({} as Record<TraitKey, number>)),
        ...STUDENT_RADAR,
      },
      {
        name: ADVISOR_SERIES_NAME,
        values: traitToArray(props.advisorTraits),
        ...ADVISOR_RADAR,
      },
    ],
    { showAxisLabel: false, showLegend: false, radius: '62%' },
  ),
)

const { refresh } = useEChart(el, () => option.value)
// 监听 props 变化刷新
import { watch } from 'vue'
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
