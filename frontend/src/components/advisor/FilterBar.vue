<script setup lang="ts">
import { computed } from 'vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useRuntimeStore } from '@/stores/useRuntimeStore'
import type { SortMetric } from '@/types/advisor'

// =====================================================================
// 卡片列表顶部筛选栏（文档 §3.4）
// 左侧：匹配数量；无发布数据时明确显示治理空态
// 右侧：结果内排序（保守排序 / 适配 / 证据覆盖 / 证据置信）
// =====================================================================

const advisorStore = useAdvisorStore()
const runtimeStore = useRuntimeStore()
const simulationHint = computed(() => runtimeStore.isSimulationMentors)

const sortOptions: Array<{ label: string; value: SortMetric }> = [
  { label: '保守排序分', value: 'score' },
  { label: '适配分', value: 'fit_score' },
  { label: '证据覆盖', value: 'evidence_coverage' },
  { label: '证据置信', value: 'evidence_confidence' },
]

function onSortChange(value: SortMetric) {
  advisorStore.sortBy(value)
}
</script>

<template>
  <div class="filter-bar">
    <span v-if="advisorStore.resultStatus === 'no_published_data'" class="count-text">
      已审核可发布导师 <strong>0</strong> 位
    </span>
    <span v-else class="count-text">
      共找到 <strong>{{ advisorStore.totalCount }}</strong> 位匹配导师
      <em v-if="simulationHint" class="sim-hint">（本地模拟）</em>
    </span>
    <el-select
      :model-value="advisorStore.sortMetric"
      size="small"
      class="sort-select"
      @update:model-value="onSortChange"
    >
      <el-option
        v-for="opt in sortOptions"
        :key="opt.value"
        :label="opt.label"
        :value="opt.value"
      />
    </el-select>
  </div>
</template>

<style scoped lang="scss">
.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: $panel-toolbar-height;
  padding: 0 $spacing-lg;
  background: $color-bg;
  border-bottom: 1px solid $color-border-light;
  flex-shrink: 0;
  gap: $spacing-sm;
}

.count-text {
  font-size: 13px;
  color: $text-regular;
  strong {
    color: $color-primary;
    font-size: 15px;
    margin: 0 2px;
  }
  .sim-hint {
    margin-left: 4px;
    font-style: normal;
    color: #8a5a00;
  }
}

.sort-select {
  width: 130px;
  flex-shrink: 0;
}
</style>
