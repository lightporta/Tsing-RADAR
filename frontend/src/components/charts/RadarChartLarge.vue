<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useEChart } from '@/composables/useEChart'
import {
  buildRadarOption,
  traitToArray,
  defaultTraitArray,
  defaultObjectiveArray,
  objectiveToArray,
  STUDENT_SERIES_NAME,
  OBJECTIVE_SERIES_NAME,
  OBJECTIVE_BASELINE_SERIES_NAME,
  TRAIT_BASELINE_SERIES_NAME,
  RATING_SERIES_NAME,
  STUDENT_RADAR,
  OBJECTIVE_RADAR,
  OBJECTIVE_DEFAULT_RADAR,
  RATING_RADAR,
  RATING_MIN_DIMENSION_N,
  OBJECTIVE_RADAR_INDICATORS,
  type RadarSeries,
} from '@/composables/useRadarOption'
import { useRatingSummary } from '@/composables/useRatingSummary'
import { displayTime } from '@/utils/format'
import type { MatchedAdvisor } from '@/types/advisor'
import { TRAITS } from '@/types/advisor'
import type { TraitKey } from '@/types/advisor'

// =====================================================================
// 大尺寸双雷达（右栏选中导师时展示），客观与主观严格分离：
//   客观雷达（四维，橙实线）= 已审核公开证据（objective_radar）
//   主观雷达（六维）= 学生需求（蓝）+ 学生匿名评价（绿虚线，n≥8）
// 任一侧无数据时显示灰色虚线 50 视觉基准（无数据、非评分），
// 基准不参与匹配与推荐计算。
// =====================================================================

const props = defineProps<{
  advisor?: MatchedAdvisor
  studentWeights: Record<TraitKey, number>
}>()

const objectiveEl = ref<HTMLElement | null>(null)
const subjectiveEl = ref<HTMLElement | null>(null)

const { ensureRatingSummary, peekRatingSummary } = useRatingSummary()

const advisorId = computed(() => props.advisor?.advisor_id ?? '')
watch(
  advisorId,
  (id) => {
    if (id) void ensureRatingSummary(id)
  },
  { immediate: true },
)
const ratingSummary = computed(() =>
  advisorId.value ? peekRatingSummary(advisorId.value) : undefined,
)

const hasObjectiveEvidence = computed(() => {
  const objective = props.advisor?.objective_radar
  if (!objective) return false
  const values = Object.values(objective)
  return values.length === 4 && values.every((v) => typeof v === 'number' && v >= 0)
})

const hasRatingData = computed(() => {
  const summary = ratingSummary.value
  if (!summary || summary.total_n <= 0) return false
  return TRAITS.some(
    (trait) =>
      summary.dimensions[trait.key] &&
      summary.dimensions[trait.key].n >= RATING_MIN_DIMENSION_N &&
      summary.dimensions[trait.key].value != null,
  )
})

// 客观四维雷达：有证据橙实线；无证据灰虚线 50 基准（非评分）
const objectiveOption = computed(() => {
  const series: RadarSeries[] = []
  if (hasObjectiveEvidence.value && props.advisor?.objective_radar) {
    series.push({
      name: OBJECTIVE_SERIES_NAME,
      values: objectiveToArray(props.advisor.objective_radar),
      ...OBJECTIVE_RADAR,
      lineType: 'solid' as const,
      lineWidth: 2.5,
      tooltipText: '来自已审核公开证据（项目/主题/联系/资料完整度），非学生主观评价',
    })
  } else {
    series.push({
      name: OBJECTIVE_BASELINE_SERIES_NAME,
      values: defaultObjectiveArray(),
      ...OBJECTIVE_DEFAULT_RADAR,
      tooltipText: '无数据、非评分：仅视觉基准（50/100），不代表任何客观分',
    })
  }
  return buildRadarOption(series, {
    showAxisLabel: true,
    showLegend: true,
    radius: '58%',
    indicators: OBJECTIVE_RADAR_INDICATORS,
  })
})

// 主观六维雷达：学生需求（蓝）+ 学生评价（绿虚线，n≥8）/ 无数据灰基准
const subjectiveOption = computed(() => {
  const series: RadarSeries[] = [
    {
      name: STUDENT_SERIES_NAME,
      values: traitToArray(props.studentWeights),
      ...STUDENT_RADAR,
    },
  ]

  const summary = ratingSummary.value
  if (summary && summary.total_n > 0) {
    series.push({
      name: `${RATING_SERIES_NAME} (N=${summary.total_n})`,
      values: TRAITS.map((trait) => {
        const dimension = summary.dimensions[trait.key]
        return dimension &&
          dimension.n >= RATING_MIN_DIMENSION_N &&
          dimension.value != null
          ? (dimension.value / 5) * 100
          : null
      }),
      ...RATING_RADAR,
      tooltipText: `社区主观评价，样本 N=${summary.total_n}，采集时间 ${displayTime(summary.last_collected_at)}，非官方事实；单维不足 ${RATING_MIN_DIMENSION_N} 份不展示`,
    })
  }

  if (!hasRatingData.value) {
    series.push({
      name: TRAIT_BASELINE_SERIES_NAME,
      values: defaultTraitArray(),
      ...OBJECTIVE_DEFAULT_RADAR,
      tooltipText: '无数据、非评分：仅视觉基准（50/100），不代表该导师任何特质分',
    })
  }

  return buildRadarOption(series, {
    showAxisLabel: true,
    showLegend: true,
    radius: '58%',
  })
})

const objectiveChart = useEChart(objectiveEl, () => objectiveOption.value)
const subjectiveChart = useEChart(subjectiveEl, () => subjectiveOption.value)
watch(objectiveOption, () => objectiveChart.refresh(), { deep: true })
watch(subjectiveOption, () => subjectiveChart.refresh(), { deep: true })
</script>

<template>
  <div class="radar-large-wrap">
    <div class="radar-block">
      <h4 class="radar-block-title">客观证据雷达（四维）</h4>
      <div ref="objectiveEl" class="radar-large" />
    </div>
    <div class="radar-block">
      <h4 class="radar-block-title">主观评价雷达（六维）</h4>
      <div ref="subjectiveEl" class="radar-large" />
    </div>
    <div v-if="!hasObjectiveEvidence" class="radar-hint">
      <span class="hint-badge">基准示意</span>
      <span class="hint-text">
        该导师暂无已审核客观证据，虚线仅为视觉基准（50/100，无数据、非评分），
        不参与匹配与推荐计算；客观指标与学生匿名评价严格分离。
      </span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.radar-large-wrap {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
}

.radar-block {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.radar-block-title {
  font-size: 12px;
  font-weight: 600;
  color: $text-secondary;
  text-align: center;
}

.radar-large {
  flex: 1;
  width: 100%;
  min-height: 200px;
}

.radar-hint {
  padding: 8px 12px;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  background: rgba(192, 196, 204, 0.08);
  border-radius: 8px;
  flex-shrink: 0;
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
