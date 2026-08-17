<script setup lang="ts">
import { computed } from 'vue'
import MentorDistributionChart from './MentorDistributionChart.vue'
import RadarChartLarge from './RadarChartLarge.vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useUserStore } from '@/stores/useUserStore'
import { TRAITS } from '@/types/advisor'
import { topTraits } from '@/utils/synergy'
import { TRAIT_LABEL_MAP } from '@/types/advisor'

// =====================================================================
// 可视化看板栏（文档 §3.5）
// 默认状态：已发布导师资源的真实院系分布
// 选中导师状态：大雷达图 + 契合指数 + 匹配理由 + 返回按钮
// =====================================================================

const advisorStore = useAdvisorStore()
const userStore = useUserStore()

const selected = computed(() => advisorStore.selectedAdvisor)
const resourceTypeLabels: Record<string, string> = {
  verified_mentor_profile: '已核验画像',
  mentor_catalog_entry: '目录导师资源',
  advisor_group_catalog_entry: '目录导师组资源',
}

// 大雷达图下方的 3 条核心匹配理由
const matchReasons = computed<string[]>(() => {
  const traits = selected.value?.radar_traits
  if (!traits) return []
  const tops = topTraits(traits, 3)
  return tops.map((k) => {
    const score = traits[k]
    return `${TRAIT_LABEL_MAP[k]}：${score} 分 — ${TRAITS.find((t) => t.key === k)?.description}`
  })
})
</script>

<template>
  <div class="chart-panel">
    <!-- 默认：真实聚合分布 -->
    <template v-if="!selected">
      <div class="panel-header">
        <h2 class="panel-title">📊 已发布导师资源分布</h2>
      </div>
      <div class="resource-summary">
        <span
          v-for="item in advisorStore.distribution.resource_types"
          :key="item.resource_type"
        >
          {{ resourceTypeLabels[item.resource_type] }} {{ item.resource_count }}
        </span>
      </div>
      <div class="chart-body">
        <MentorDistributionChart />
        <p class="chart-hint">
          展示已发布资源合并后的院系数量；不推断热度、经费、指导风格或国/私属性。<br />
          共 {{ advisorStore.distribution.meta.grouped_advisors }} 位导师/导师组，来自
          {{ advisorStore.distribution.meta.raw_resource_records }} 条公开资源。
        </p>
      </div>
    </template>

    <!-- 选中导师：大雷达图 -->
    <template v-else>
      <div class="panel-header radar-header">
        <div class="advisor-meta">
          <h2 class="advisor-name">{{ selected.name }}</h2>
          <p class="advisor-dept">{{ selected.dept }} · {{ selected.field }}</p>
        </div>
        <button class="back-btn" @click="advisorStore.selectAdvisor(null)">
          <el-icon aria-hidden="true">←</el-icon>
          返回分布图
        </button>
      </div>

      <div class="radar-body">
        <RadarChartLarge
          :advisor="selected"
          :student-weights="userStore.profile.weights"
        />
        <div v-if="!selected.radar_traits" class="evidence-overview">
          <strong>仅展示你的六维需求轮廓</strong>
          <p>
            证据覆盖 {{ ((selected.evidence_coverage ?? 0) * 100).toFixed(0) }}% ·
            置信度 {{ ((selected.evidence_confidence ?? 0) * 100).toFixed(0) }}%
          </p>
          <p>导师暂缺已审核六维特质，因此不绘制导师侧橙色轮廓。</p>
        </div>
      </div>

      <div class="radar-footer">
        <div class="synergy-score">
          <span class="score-label">保守排序分</span>
          <span class="score-value">{{ selected.score.toFixed(1) }}</span>
        </div>
        <ul class="match-reasons">
          <li v-for="(reason, i) in matchReasons" :key="i">{{ reason }}</li>
        </ul>
        <p v-if="selected.reason" class="advisor-reason">💡 {{ selected.reason }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
.chart-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: $spacing-xl;
  background: $color-bg-card;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;
  flex-shrink: 0;
}
.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
}

.resource-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: $spacing-md;
  padding: $spacing-sm $spacing-md;
  background: $color-bg;
  border-radius: $card-radius;
  margin-bottom: $spacing-md;
  flex-shrink: 0;

  span {
    font-size: 12px;
    color: $text-secondary;
  }
}

.chart-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.chart-hint {
  margin-top: $spacing-sm;
  font-size: 11px;
  color: $text-placeholder;
  text-align: center;
  line-height: 1.6;
}

// 大雷达图区域
.radar-header {
  .advisor-meta {
    min-width: 0;
  }
  .advisor-name {
    font-size: 18px;
    font-weight: 700;
    color: $text-primary;
  }
  .advisor-dept {
    font-size: 12px;
    color: $text-secondary;
    margin-top: 2px;
  }
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 1px solid $color-border;
  border-radius: $card-radius;
  font-size: 12px;
  color: $text-regular;
  transition: $transition-fast;

  &:hover {
    color: $color-primary;
    border-color: $color-primary;
  }
}

.radar-body {
  flex: 1;
  min-height: 280px;
  display: flex;
  justify-content: center;
  flex-direction: column;
}

.evidence-overview {
  margin: 0 auto;
  padding: 0 $spacing-xl $spacing-lg;
  text-align: center;
  color: $text-secondary;

  p {
    margin-top: $spacing-sm;
    font-size: 12px;
  }
}

.radar-footer {
  flex-shrink: 0;
  padding-top: $spacing-md;
  border-top: 1px solid $color-border-light;
}

.synergy-score {
  display: flex;
  align-items: baseline;
  gap: $spacing-md;
  margin-bottom: $spacing-sm;

  .score-label {
    font-size: 12px;
    color: $text-secondary;
  }
  .score-value {
    font-size: 32px;
    font-weight: 800;
    color: $color-accent;
    small {
      font-size: 14px;
      margin-left: 2px;
    }
  }
}

.match-reasons {
  margin: $spacing-sm 0;
  li {
    font-size: 12px;
    color: $text-regular;
    line-height: 1.7;
    padding-left: 12px;
    position: relative;
    &::before {
      content: '✓';
      position: absolute;
      left: 0;
      color: $color-success;
    }
  }
}

.advisor-reason {
  font-size: 12px;
  color: $text-regular;
  background: rgba(255, 149, 0, 0.06);
  padding: $spacing-sm $spacing-md;
  border-radius: $card-radius;
  border-left: 3px solid $color-accent;
}
</style>
