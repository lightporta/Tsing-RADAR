import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { MatchedAdvisor, SortMetric, ScatterPoint } from '@/types/advisor'
import * as advisorApi from '@/api/advisor'
import * as mockApi from '@/mock'

// =====================================================================
// 导师 Store（文档 §7.1 useAdvisorStore）
// 导师列表 / 当前选中 / 筛选排序 / 散点数据
// =====================================================================

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

export const useAdvisorStore = defineStore('advisor', () => {
  // —— 匹配后的导师（带 score / synergy / reason）——
  const matchedAdvisors = ref<MatchedAdvisor[]>([])
  // —— 散点数据 ——
  const scatterPoints = ref<ScatterPoint[]>([])
  // —— 当前选中的导师名（联动卡片 / 散点 / 右栏）——
  const selectedName = ref<string | null>(null)
  // —— 排序指标 ——
  const sortMetric = ref<SortMetric>('score')
  // —— 象限筛选（散点图右上复选框组）——
  const quadrantFilter = ref<Record<string, boolean>>({
    国热: true,
    国冷: true,
    私热: true,
    私冷: true,
  })
  // —— 加载态 ——
  const loading = ref(false)
  const resultStatus = ref<'idle' | 'matched' | 'no_published_data' | 'no_match' | 'error'>('idle')
  const resultMessage = ref('请先完成访谈并确认画像。')
  const resultMeta = ref<Record<string, unknown>>({})
  const comparisonIds = ref<string[]>([])

  const totalCount = computed(() => matchedAdvisors.value.length)

  /** 当前选中的导师对象 */
  const selectedAdvisor = computed<MatchedAdvisor | null>(() => {
    if (!selectedName.value) return null
    return (
      matchedAdvisors.value.find((m) => m.name === selectedName.value) || null
    )
  })

  /** 首页只加载公开可视化；导师推荐必须由确认画像后的 bounded match 产生。 */
  async function loadAll() {
    loading.value = true
    try {
      if (USE_MOCK) {
        scatterPoints.value = mockApi.mockScatterPoints
      } else {
        const scatter = await advisorApi.fetchScatter()
        scatterPoints.value = scatter.data
      }
      // 导师公开列表不等同于推荐；确认画像前不生成匹配结果。
      matchedAdvisors.value = []
    } finally {
      loading.value = false
    }
  }

  /** 综合匹配 */
  async function match(
    interest: string,
    sessionId: string,
    portrait?: Record<string, unknown>,
    weight?: Record<string, number>,
  ) {
    loading.value = true
    try {
      if (USE_MOCK) {
        matchedAdvisors.value = mockApi.mockMatch(interest)
      } else {
        const res = await advisorApi.matchAdvisors({
          interest,
          session_id: sessionId,
          portrait,
          weight,
        })
        matchedAdvisors.value = res.data
        resultStatus.value = res.status
        resultMessage.value = res.message
        resultMeta.value = res.meta
      }
      selectedName.value = null
      comparisonIds.value = []
    } catch (error) {
      resultStatus.value = 'error'
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      resultMessage.value =
        typeof detail === 'object' && detail && 'message' in detail
          ? String((detail as { message: unknown }).message)
          : '匹配请求失败，请检查画像中的待澄清条件后重试。'
      throw error
    } finally {
      loading.value = false
    }
  }

  /** 按指标排序 */
  async function sortBy(metric: SortMetric) {
    sortMetric.value = metric
    matchedAdvisors.value.sort(
      (a, b) => Number(b[metric] ?? 0) - Number(a[metric] ?? 0),
    )
  }

  /** 选中导师（联动） */
  function selectAdvisor(name: string | null) {
    selectedName.value = name
  }

  /** 设置象限筛选 */
  function toggleQuadrant(name: string, value: boolean) {
    quadrantFilter.value[name] = value
  }

  function toggleComparison(advisorId: string) {
    if (comparisonIds.value.includes(advisorId)) {
      comparisonIds.value = comparisonIds.value.filter((item) => item !== advisorId)
      return
    }
    if (comparisonIds.value.length >= 3) return
    comparisonIds.value = [...comparisonIds.value, advisorId]
  }

  const comparedAdvisors = computed(() =>
    matchedAdvisors.value.filter((item) =>
      comparisonIds.value.includes(item.advisor_id || item.name),
    ),
  )

  function resetResults() {
    matchedAdvisors.value = []
    selectedName.value = null
    comparisonIds.value = []
    resultStatus.value = 'idle'
    resultMessage.value = '请先完成访谈并确认画像。'
    resultMeta.value = {}
  }

  /** 按象限筛选后的散点 */
  const filteredScatter = computed(() =>
    scatterPoints.value.filter((p) => {
      const q = quadrantName(p.x, p.y)
      return quadrantFilter.value[q]
    }),
  )

  return {
    matchedAdvisors,
    scatterPoints,
    filteredScatter,
    selectedName,
    selectedAdvisor,
    sortMetric,
    quadrantFilter,
    loading,
    totalCount,
    resultStatus,
    resultMessage,
    resultMeta,
    comparisonIds,
    comparedAdvisors,
    loadAll,
    match,
    sortBy,
    selectAdvisor,
    toggleQuadrant,
    toggleComparison,
    resetResults,
  }
})

/** 根据散点坐标判定象限名 */
export function quadrantName(x: number, y: number): '国热' | '国冷' | '私热' | '私冷' {
  const hot = x > 60
  const guo = y === 0 // y=0 国 / y=1 私
  if (guo && hot) return '国热'
  if (guo && !hot) return '国冷'
  if (!guo && hot) return '私热'
  return '私冷'
}
