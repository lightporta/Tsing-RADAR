<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts'
import { useEChart } from '@/composables/useEChart'
import { useAdvisorStore } from '@/stores/useAdvisorStore'

const { height = '100%' } = defineProps<{ height?: string }>()
const advisorStore = useAdvisorStore()
const el = ref<HTMLElement | null>(null)

const rows = computed(() => [...advisorStore.distribution.departments].reverse())

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

const option = computed<EChartsOption>(() => ({
  animationDuration: 450,
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    formatter: (items: unknown) => {
      const first = Array.isArray(items) ? items[0] as { name?: string; value?: number } : null
      return first
        ? `<strong>${escapeHtml(first.name)}</strong><br/>合并后导师/导师组：${first.value ?? 0}`
        : ''
    },
  },
  grid: { left: 8, right: 24, top: 8, bottom: 20, containLabel: true },
  xAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: '#ebeef5', type: 'dashed' } },
    axisLabel: { color: '#909399', fontSize: 10 },
  },
  yAxis: {
    type: 'category',
    data: rows.value.map((item) => item.name),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#606266', width: 118, overflow: 'truncate', fontSize: 10 },
  },
  series: [{
    name: '导师/导师组',
    type: 'bar',
    barMaxWidth: 14,
    data: rows.value.map((item) => item.advisor_count),
    itemStyle: { color: '#409eff', borderRadius: [0, 5, 5, 0] },
  }],
}))

const { refresh } = useEChart(el, () => option.value)
watch(option, () => refresh(), { deep: true })
</script>

<template>
  <div ref="el" class="distribution-chart" :style="{ height }" />
</template>

<style scoped lang="scss">
.distribution-chart { width: 100%; min-height: 220px; }
</style>
