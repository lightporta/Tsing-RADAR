<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { TRAITS } from '@/types/advisor'
import { displayTime } from '@/utils/format'
import { useRatingSummary } from '@/composables/useRatingSummary'

// =====================================================================
// 学生评价聚合摘要（M1）
// 维度分布条 + 样本量 + 采集时间；N=0 诚实空态「暂无学生评价」
// =====================================================================

const props = defineProps<{ advisorId: string }>()

const { ensureRatingSummary, peekRatingSummary } = useRatingSummary()

onMounted(() => {
  void ensureRatingSummary(props.advisorId)
})

const summary = computed(() => peekRatingSummary(props.advisorId))

const rows = computed(() => {
  const current = summary.value
  if (!current) return []
  return TRAITS.map((trait) => {
    const dimension = current.dimensions[trait.key]
    const value = dimension?.value ?? null
    const n = dimension?.n ?? 0
    return {
      label: trait.label,
      value,
      n,
      percent: value != null ? (value / 5) * 100 : 0,
    }
  })
})
</script>

<template>
  <div class="rating-summary">
    <p v-if="!summary" class="summary-loading">评价数据加载中…</p>
    <p v-else-if="summary.total_n === 0" class="summary-empty">暂无学生评价</p>
    <template v-else>
      <div class="summary-meta">
        <span class="summary-n">🧑‍🎓 {{ summary.total_n }} 条学生评价</span>
        <span class="summary-time">采集时间 {{ displayTime(summary.last_collected_at) }}</span>
      </div>
      <div class="summary-bars">
        <div v-for="row in rows" :key="row.label" class="summary-row">
          <div class="summary-row-head">
            <span class="summary-label">{{ row.label }}</span>
            <span v-if="row.value != null" class="summary-value">
              {{ row.value.toFixed(1) }}
              <small v-if="row.n < 3" class="insufficient">样本不足</small>
            </span>
            <span v-else class="summary-value dim">暂无</span>
          </div>
          <div class="summary-bar">
            <div class="summary-fill" :style="{ width: row.percent + '%' }" />
          </div>
        </div>
      </div>
      <p class="summary-disclaimer">社区主观评价，非官方事实</p>
    </template>
  </div>
</template>

<style scoped lang="scss">
.rating-summary {
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
}

.summary-loading,
.summary-empty {
  font-size: 12px;
  color: $text-placeholder;
}

.summary-meta {
  display: flex;
  align-items: baseline;
  gap: $spacing-sm;
  .summary-n {
    font-size: 12px;
    font-weight: 600;
    color: #67c23a;
  }
  .summary-time {
    font-size: 10px;
    color: $text-placeholder;
  }
}

.summary-bars {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: $spacing-sm $spacing-md;
}

.summary-row {
  .summary-row-head {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    margin-bottom: 3px;
  }
  .summary-label {
    color: $text-regular;
  }
  .summary-value {
    color: #67c23a;
    font-weight: 600;
    &.dim {
      color: $text-placeholder;
      font-weight: 400;
    }
    .insufficient {
      margin-left: 4px;
      font-size: 10px;
      font-weight: 400;
      color: $text-placeholder;
    }
  }
  .summary-bar {
    height: 4px;
    background: $color-border-light;
    border-radius: 2px;
    overflow: hidden;
  }
  .summary-fill {
    height: 100%;
    background: linear-gradient(90deg, #85ce61, #67c23a);
    border-radius: 2px;
    transition: width 0.5s ease;
  }
}

.summary-disclaimer {
  font-size: 10px;
  color: $text-placeholder;
}

@media (max-width: $bp-tablet) {
  .summary-bars {
    grid-template-columns: 1fr;
  }
}
</style>
