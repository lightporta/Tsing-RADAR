<script setup lang="ts">
import { computed } from 'vue'
import ScatterChart from './ScatterChart.vue'
import RadarChartLarge from './RadarChartLarge.vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useUserStore } from '@/stores/useUserStore'
import { TRAITS } from '@/types/advisor'
import { topTraits } from '@/utils/synergy'
import { TRAIT_LABEL_MAP } from '@/types/advisor'

// =====================================================================
// 可视化看板栏（文档 §3.5）
// 默认状态：四象限散点图 + 象限筛选复选框组
// 选中导师状态：大雷达图 + 契合指数 + 匹配理由 + 返回按钮
// =====================================================================

const advisorStore = useAdvisorStore()
const userStore = useUserStore()

const selected = computed(() => advisorStore.selectedAdvisor)
const quadrants = ['国热', '国冷', '私热', '私冷'] as const

const quadrantColors: Record<string, string> = {
  国热: '#67c23a',
  国冷: '#909399',
  私热: '#e6a23c',
  私冷: '#409eff',
}

// 大雷达图下方的 3 条核心匹配理由
const matchReasons = computed<string[]>(() => {
  if (!selected.value?.radar_traits) return []
  const tops = topTraits(selected.value.radar_traits, 3)
  return tops.map((k) => {
    const score = selected.value!.radar_traits[k]
    return `${TRAIT_LABEL_MAP[k]}：${score} 分 — ${TRAITS.find((t) => t.key === k)?.description}`
  })
})
</script>

<template>
  <div class="chart-panel">
    <!-- 默认：散点图 -->
    <template v-if="!selected">
      <div class="panel-header">
        <h2 class="panel-title">📊 导师四象限分布</h2>
      </div>
      <!-- 象限筛选复选框组（右上角） -->
      <div class="quadrant-filter">
        <span class="filter-label">象限筛选：</span>
        <el-checkbox
          v-for="q in quadrants"
          :key="q"
          :model-value="advisorStore.quadrantFilter[q]"
          @update:model-value="(v) => advisorStore.toggleQuadrant(q, !!v)"
        >
          <span class="quad-dot" :style="{ background: quadrantColors[q] }" />
          {{ q }}
        </el-checkbox>
      </div>
      <div class="chart-body">
        <ScatterChart />
        <p class="chart-hint">
          散点大小 = 契合度 · 颜色 = 院系 · 横轴 = 冷热门 · 纵轴 = 国/私<br />
          点击散点或左侧卡片查看导师详情雷达图
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
          返回散点图
        </button>
      </div>

      <div class="radar-body">
        <RadarChartLarge
          v-if="selected.radar_traits"
          :advisor="selected"
          :student-weights="userStore.profile.weights"
        />
        <div v-else class="evidence-overview">
          <strong>当前只展示证据化匹配结果</strong>
          <p>
            证据覆盖 {{ ((selected.evidence_coverage ?? 0) * 100).toFixed(0) }}% ·
            置信度 {{ ((selected.evidence_confidence ?? 0) * 100).toFixed(0) }}%
          </p>
          <p>缺少经审核的六维导师特质，不绘制雷达图。</p>
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

// 象限筛选
.quadrant-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: $spacing-md;
  padding: $spacing-sm $spacing-md;
  background: $color-bg;
  border-radius: $card-radius;
  margin-bottom: $spacing-md;
  flex-shrink: 0;

  .filter-label {
    font-size: 12px;
    color: $text-secondary;
  }
  .quad-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 4px;
    vertical-align: middle;
  }
  :deep(.el-checkbox) {
    margin-right: 0;
    height: auto;
  }
  :deep(.el-checkbox__label) {
    font-size: 12px;
    padding-left: 4px;
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
}

.evidence-overview {
  margin: auto;
  padding: $spacing-xl;
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
