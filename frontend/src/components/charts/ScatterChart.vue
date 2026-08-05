<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useEChart } from '@/composables/useEChart'
import type { EChartsOption } from 'echarts'
import type { ScatterPoint } from '@/types/advisor'
import { useAdvisorStore, quadrantName } from '@/stores/useAdvisorStore'

// =====================================================================
// 二维四象限散点图（文档 §3.5 / §4.3.2）
// 横轴：冷方向 ← 热门指数 → 热方向
// 纵轴：国有 ↑ 行业性质 ↓ 私营
// 四象限：国热(左上) / 国冷(左下) / 私热(右上) / 私冷(右下)
// 散点大小映射契合度，颜色按院系
// 点击散点联动选中导师卡片
// =====================================================================

const props = withDefaults(defineProps<{ height?: string }>(), { height: '100%' })

const advisorStore = useAdvisorStore()
const el = ref<HTMLElement | null>(null)

// 反转 y 轴显示：y=0(国) 在上，y=1(私) 在下
const chartData = computed(() =>
  advisorStore.filteredScatter.map((p: ScatterPoint) => ({
    name: p.name,
    value: [p.x, p.y === 0 ? 0 : 1, p.value ?? 50],
    itemStyle: { color: p.color, opacity: 0.85 },
    advisor: p.advisor,
  })),
)

const option = computed<EChartsOption>(() => ({
  tooltip: {
    trigger: 'item',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    formatter: (params: any) => {
      const d = params?.data
      if (!d || !Array.isArray(d.value)) return ''
      const [x, , v] = d.value
      const q = quadrantName(x, d.value[1])
      return `<strong>${d.name}</strong><br/>热门指数：${x}<br/>象限：${q}<br/>契合度：${v}`
    },
  },
  grid: {
    left: 50,
    right: 30,
    top: 30,
    bottom: 50,
    containLabel: true,
  },
  xAxis: {
    name: '冷方向 ← 热门指数 → 热方向',
    nameLocation: 'middle',
    nameGap: 30,
    min: 0,
    max: 100,
    splitLine: { show: true, lineStyle: { color: '#ebeef5', type: 'dashed' } },
    axisLine: { lineStyle: { color: '#dcdfe6' } },
    axisLabel: { color: '#909399' },
  },
  yAxis: {
    name: '国有 ↑ 行业性质 ↓ 私营',
    nameLocation: 'middle',
    nameGap: 35,
    min: -0.5,
    max: 1.5,
    interval: 1,
    // 反转：0(国)在上，1(私)在下
    inverse: false,
    splitLine: { show: true, lineStyle: { color: '#ebeef5', type: 'dashed' } },
    axisLine: { lineStyle: { color: '#dcdfe6' } },
    axisLabel: {
      color: '#909399',
      formatter: (val: number) => (val === 0 ? '国' : val === 1 ? '私' : ''),
    },
  },
  // 四象限背景区域（极淡色）
  markArea: {
    silent: true,
    data: [
      // 国热（左上 x<60, y=0）
      [
        { xAxis: 0, yAxis: -0.5, itemStyle: { color: 'rgba(103, 194, 58, 0.06)' } },
        { xAxis: 60, yAxis: 0.5 },
      ],
      // 国冷（左下 x<60, y=1）—— 实际 y=0 在上，y=1 在下
      [
        { xAxis: 0, yAxis: 0.5, itemStyle: { color: 'rgba(144, 147, 153, 0.06)' } },
        { xAxis: 60, yAxis: 1.5 },
      ],
      // 私热（右上 x>=60, y=0）
      [
        { xAxis: 60, yAxis: -0.5, itemStyle: { color: 'rgba(230, 162, 60, 0.06)' } },
        { xAxis: 100, yAxis: 0.5 },
      ],
      // 私冷（右下 x>=60, y=1）
      [
        { xAxis: 60, yAxis: 0.5, itemStyle: { color: 'rgba(64, 158, 255, 0.06)' } },
        { xAxis: 100, yAxis: 1.5 },
      ],
    ],
  },
  series: [
    {
      type: 'scatter',
      symbolSize: (data: number[]) => Math.max(10, Math.min(40, (data[2] ?? 50) / 3)),
      data: chartData.value,
      emphasis: {
        focus: 'self',
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
      },
      // 国热标记区作为 series 的 markArea
      markArea: {
        silent: true,
        data: [
          [
            {
              xAxis: 0,
              yAxis: -0.5,
              itemStyle: { color: 'rgba(103, 194, 58, 0.06)' },
            },
            { xAxis: 60, yAxis: 0.5 },
          ],
          [
            { xAxis: 0, yAxis: 0.5, itemStyle: { color: 'rgba(144, 147, 153, 0.06)' } },
            { xAxis: 60, yAxis: 1.5 },
          ],
          [
            { xAxis: 60, yAxis: -0.5, itemStyle: { color: 'rgba(230, 162, 60, 0.06)' } },
            { xAxis: 100, yAxis: 0.5 },
          ],
          [
            { xAxis: 60, yAxis: 0.5, itemStyle: { color: 'rgba(64, 158, 255, 0.06)' } },
            { xAxis: 100, yAxis: 1.5 },
          ],
        ],
      },
    },
  ],
}))

const { refresh, chart } = useEChart(el, () => option.value)
watch(option, () => refresh(), { deep: true })

// 点击散点联动选中导师
function bindClick() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart.value?.on('click', (params: any) => {
    const name = params?.data?.name
    if (name) {
      advisorStore.selectAdvisor(name)
    }
  })
}

import { onMounted } from 'vue'
onMounted(() => {
  setTimeout(bindClick, 100)
})
</script>

<template>
  <div ref="el" class="scatter-chart" :style="{ height }" />
</template>

<style scoped lang="scss">
.scatter-chart {
  width: 100%;
}
</style>
