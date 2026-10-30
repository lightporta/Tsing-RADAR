<script setup lang="ts">
import { computed } from 'vue'
import ScatterChart from './ScatterChart.vue'
import AdvisorDetail from '@/components/advisor/AdvisorDetail.vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'

const advisorStore = useAdvisorStore()
const selected = computed(() => advisorStore.selectedAdvisor)
const quadrants = ['国热', '国冷', '私热', '私冷'] as const
const objectiveLabels: Record<string, string> = {
  topic_fit: '研究主题',
  research_mode_fit: '研究方式',
  mentorship_fit: '指导方式',
  career_fit: '生涯方向',
  innovation_fit: '创新偏好',
  opportunity_fit: '机会信号',
}
const breakdown = computed(() => selected.value?.score_breakdown || [])
function percent(value: number | undefined) {
  return value === undefined ? '—' : `${(value * 100).toFixed(0)}%`
}
function score(value: number | null | undefined) {
  return value == null ? '未评分' : (value * 100).toFixed(0)
}
</script>

<template>
  <aside class="chart-panel" aria-label="匹配依据">
    <header class="panel-header">
      <div>
        <p class="eyebrow">MATCH INSIGHTS</p>
        <h2>匹配依据</h2>
      </div>
      <button v-if="selected" class="back-btn" @click="advisorStore.selectAdvisor(null)">查看概览</button>
    </header>

    <div v-if="selected" class="insight-content">
      <section class="advisor-summary">
        <h3>{{ selected.name }}</h3>
        <p>{{ selected.dept }}<span v-if="selected.field"> · {{ selected.field }}</span></p>
        <div class="score-grid">
          <div class="main-score"><span>保守排序分</span><strong>{{ selected.score.toFixed(1) }}<small>/100</small></strong></div>
          <div><span>适配分</span><strong>{{ selected.fit_score?.toFixed(1) ?? '—' }}</strong></div>
          <div><span>证据覆盖</span><strong>{{ percent(selected.evidence_coverage) }}</strong></div>
          <div><span>证据置信</span><strong>{{ percent(selected.evidence_confidence) }}</strong></div>
        </div>
        <p class="metric-note">排序分按各项适配与证据置信加权计算，用于比较候选，不代表录取概率。</p>
      </section>

      <section class="breakdown-section" aria-label="六项匹配分解">
        <h3>六项匹配分解</h3>
        <p class="section-note">条形表示适配程度；贡献分已考虑权重与证据置信。</p>
        <div v-for="item in breakdown" :key="item.objective" class="objective-row">
          <div class="objective-heading">
            <span>{{ objectiveLabels[item.objective] || item.objective }}</span>
            <strong>{{ score(item.score) }}</strong>
          </div>
          <div
            class="objective-track"
            :class="{ unavailable: item.score == null }"
            role="progressbar"
            :aria-label="objectiveLabels[item.objective] || item.objective"
            :aria-valuenow="item.score == null ? undefined : Math.round(item.score * 100)"
            :aria-valuetext="item.score == null ? '缺少证据，未评分' : undefined"
            :aria-valuemin="0"
            :aria-valuemax="100"
          >
            <span :style="{ width: `${(item.score ?? 0) * 100}%` }" />
          </div>
          <p class="objective-meta">
            权重 {{ percent(item.effective_weight) }} · 置信 {{ percent(item.evidence_confidence) }}
            <span v-if="item.conservative_contribution !== undefined"> · 贡献 {{ (item.conservative_contribution * 100).toFixed(1) }} 分</span>
          </p>
        </div>
        <p v-if="!breakdown.length" class="section-note">当前结果未提供评分分解。</p>
      </section>
      <AdvisorDetail :advisor="selected" />
    </div>

    <div v-else class="insight-content">
      <section v-if="advisorStore.matchedAdvisors.length" class="candidate-picker">
        <h3>选择导师查看匹配解释</h3>
        <p class="section-note">查看每一项适配、证据来源和需要进一步核实的问题。</p>
        <button
          v-for="advisor in advisorStore.matchedAdvisors"
          :key="advisor.advisor_id"
          class="candidate-button"
          @click="advisorStore.selectAdvisor(advisor.advisor_id)"
        >
          <span>{{ advisor.name }}<small>{{ advisor.dept }}</small></span>
          <strong>{{ advisor.score.toFixed(1) }} <span aria-hidden="true">↗</span></strong>
        </button>
      </section>
      <section v-else class="insight-placeholder">
        <div class="insight-symbol" aria-hidden="true">◎</div>
        <h3>让每一项推荐都有依据</h3>
        <p>先完成访谈并确认画像，再从推荐卡片查看六项匹配分解、支持证据与待核实问题。</p>
        <ol>
          <li><span>01</span> 描述研究兴趣与目标</li>
          <li><span>02</span> 检查画像和硬约束</li>
          <li><span>03</span> 对比适配与证据</li>
        </ol>
      </section>

      <details v-if="advisorStore.scatterPoints.length" class="public-distribution">
        <summary>公开导师方向分布</summary>
        <div class="quadrant-filter">
          <el-checkbox
            v-for="q in quadrants"
            :key="q"
            :model-value="advisorStore.quadrantFilter[q]"
            @update:model-value="(value) => advisorStore.toggleQuadrant(q, !!value)"
          >
            {{ q }}
          </el-checkbox>
        </div>
        <ScatterChart height="300px" />
        <p class="section-note">颜色表示院系，点大小一致。分布坐标来自公开资料，不表示个人契合度。</p>
      </details>
      <p v-else class="axis-empty">当前资料未提供足够的方向分布依据；这不影响基于已确认画像的匹配。</p>
    </div>
  </aside>
</template>

<style scoped lang="scss">
.chart-panel { display: flex; flex-direction: column; height: 100%; min-height: 0; padding: $spacing-xl; background: $color-bg-card; }
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-bottom: 16px; border-bottom: 1px solid $color-border-light; flex-shrink: 0; }
.panel-header h2 { margin-top: 4px; font-size: 18px; color: $text-primary; }
.eyebrow { font-size: 10px; letter-spacing: 1.4px; color: $color-primary-dark; font-weight: 600; }
.back-btn { padding: 6px 9px; border: 1px solid $color-border; border-radius: 6px; color: $text-regular; font-size: 12px; white-space: nowrap; }
.back-btn:hover { color: $color-primary; border-color: $color-primary; }
.insight-content { flex: 1; min-height: 0; overflow-y: auto; padding-top: 20px; }
.advisor-summary h3 { font-size: 19px; color: $text-primary; }
.advisor-summary > p { margin-top: 5px; color: $text-secondary; font-size: 12px; line-height: 1.6; }
.score-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.score-grid > div { padding: 12px; border-radius: 8px; background: $color-bg; }
.score-grid span { display: block; font-size: 11px; color: $text-regular; }
.score-grid strong { display: block; margin-top: 4px; font-size: 22px; color: $text-primary; }
.score-grid .main-score { background: rgba(64, 158, 255, 0.08); }
.score-grid .main-score strong { color: $color-primary-dark; }
.score-grid small { margin-left: 2px; font-size: 11px; font-weight: 400; color: $text-secondary; }
.advisor-summary .metric-note { margin: 12px 0 20px; font-size: 11px; color: $text-regular; }
.breakdown-section { margin-bottom: 24px; }
h3 { font-size: 14px; font-weight: 600; }
.section-note { margin: 6px 0 12px; font-size: 11px; color: $text-secondary; line-height: 1.7; }
.objective-row { margin-top: 16px; }
.objective-heading { display: flex; justify-content: space-between; font-size: 12px; color: $text-regular; }
.objective-heading strong { color: $text-primary; font-size: 12px; }
.objective-track { height: 6px; overflow: hidden; border-radius: 4px; margin-top: 7px; background: $color-border-light; }
.objective-track > span { display: block; height: 100%; background: linear-gradient(90deg, $color-primary-light, $color-primary-dark); border-radius: 4px; }
.objective-track.unavailable { background: repeating-linear-gradient(135deg, #eef0f3, #eef0f3 4px, #fafbfc 4px, #fafbfc 8px); }
.objective-meta { margin-top: 5px; color: $text-secondary; font-size: 10px; }
.insight-placeholder { padding: 16px 4px; }
.insight-symbol { color: $color-primary; font-size: 44px; line-height: 1; margin-bottom: 20px; }
.insight-placeholder h3 { font-size: 17px; }
.insight-placeholder > p { margin-top: 10px; font-size: 12px; line-height: 1.9; color: $text-regular; }
.insight-placeholder ol { padding: 0; list-style: none; margin-top: 28px; display: grid; gap: 18px; }
.insight-placeholder li { font-size: 12px; color: $text-regular; display: flex; align-items: center; gap: 12px; }
.insight-placeholder li span { font-size: 10px; color: $color-primary-dark; padding: 5px 7px; border-radius: 5px; background: rgba(64, 158, 255, 0.08); }
.axis-empty { margin-top: 30px; padding-top: 16px; border-top: 1px solid $color-border-light; font-size: 11px; line-height: 1.8; color: $text-secondary; }
.candidate-button { display: flex; align-items: center; justify-content: space-between; width: 100%; text-align: left; padding: 13px 0; border-bottom: 1px solid $color-border-light; color: $text-primary; font-size: 13px; gap: 8px; }
.candidate-button small { display: block; margin-top: 4px; color: $text-secondary; font-size: 10px; }
.candidate-button strong { white-space: nowrap; color: $color-primary-dark; font-size: 15px; }
.candidate-button strong span { margin-left: 4px; }
.public-distribution { margin-top: 26px; border-top: 1px solid $color-border-light; padding-top: 16px; }
.public-distribution summary { cursor: pointer; font-size: 12px; color: $text-regular; }
.quadrant-filter { display: flex; flex-wrap: wrap; margin: 10px 0; gap: 10px; }
.quadrant-filter :deep(.el-checkbox) { margin-right: 0; }
@media (max-width: $bp-tablet) { .chart-panel { height: auto; } .insight-content { overflow-y: visible; } }
</style>
