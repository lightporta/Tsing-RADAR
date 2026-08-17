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
import type { MatchedAdvisor } from '@/types/advisor'
import type { TraitKey } from '@/types/advisor'

// =====================================================================
// 大尺寸双轨雷达图（右栏选中导师时展示）
// 有数据：深色实线；无数据：默认基准50（浅色虚线）
// =====================================================================

const props = defineProps<{
  advisor?: MatchedAdvisor
  studentWeights: Record<TraitKey, number>
}>()

const el = ref<HTMLElement | null>(null)

const hasRealTraits = computed(() => {
  if (!props.advisor?.radar_traits) return false
  const values = Object.values(props.advisor.radar_traits)
  return values.length === 6 && values.every((v) => typeof v === 'number' && v > 0)
})

const option = computed(() => {
  const series: RadarSeries[] = [
      {
        name: STUDENT_SERIES_NAME,
        values: traitToArray(props.studentWeights),
        ...STUDENT_RADAR,
      },
  ]

  if (hasRealTraits.value && props.advisor?.radar_traits) {
    series.push({
      name: ADVISOR_SERIES_NAME,
      values: traitToArray(props.advisor.radar_traits),
      ...ADVISOR_RADAR,
      lineType: 'solid' as const,
      lineWidth: 2.5,
    })
  } else {
    series.push({
      name: ADVISOR_DEFAULT_SERIES_NAME,
      values: defaultTraitArray(),
      ...ADVISOR_DEFAULT_RADAR,
      lineWidth: 1.5,
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
  <div class="radar-large-wrap">
    <div ref="el" class="radar-large" />
    <div v-if="!hasRealTraits" class="radar-hint">
      <span class="hint-badge">基准示意</span>
      <span class="hint-text">该导师暂无已审核的六维评分数据，图中虚线为默认基准值（50/100）。有真实数据时将以实线深色显示。</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.radar-large-wrap {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.radar-large {
  flex: 1;
  width: 100%;
  min-height: 280px;
}

.radar-hint {
  padding: 8px 12px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  background: rgba(192, 196, 204, 0.08);
  border-radius: 8px;
  margin: 0 12px 8px;
}

.hint-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(192, 196, 204, 0.2);
  color: $text-secondary;
  font-size: 10px;
  font-weight: 600;
}

.hint-text {
  font-size: 11px;
  color: $text-placeholder;
  line-height: 1.5;
}
</style>
