import { ref, onMounted, onUnmounted, watch, type Ref } from 'vue'
import * as echarts from 'echarts/core'
import { RadarChart, ScatterChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent,
  MarkAreaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

// 注册必需的 ECharts 模块（按需引入减小包体）
echarts.use([
  RadarChart,
  ScatterChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

// =====================================================================
// ECharts 实例组合式封装
// 自动 init / 自适应 / 销毁 / option 更新
// =====================================================================

export function useEChart(
  el: Ref<HTMLElement | null>,
  getOption: () => EChartsOption,
) {
  const chart = ref<echarts.ECharts | null>(null)

  const resize = () => chart.value?.resize()

  const setOption = (option?: EChartsOption) => {
    if (!chart.value) return
    chart.value.setOption(option ?? getOption(), { notMerge: false })
  }

  const refresh = () => setOption(getOption())

  onMounted(() => {
    if (el.value) {
      chart.value = echarts.init(el.value)
      chart.value.setOption(getOption())
      window.addEventListener('resize', resize, { passive: true })
    }
  })

  // 提供 watch 依赖：依赖变化时刷新
  const watchDep = <T>(dep: Ref<T>) => {
    watch(dep, () => refresh(), { deep: true })
    return dep
  }

  onUnmounted(() => {
    window.removeEventListener('resize', resize)
    chart.value?.dispose()
    chart.value = null
  })

  return { chart, setOption, refresh, resize, watchDep }
}

export { echarts }
export default echarts
