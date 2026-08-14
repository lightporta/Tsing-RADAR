import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { MatchedAdvisor, MentorDistribution, SortMetric } from '@/types/advisor'
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
  // —— 已发布导师资源的真实聚合分布 ——
  const distribution = ref<MentorDistribution>({
    departments: [],
    resource_types: [],
    meta: { grouped_advisors: 0, raw_resource_records: 0, basis: 'published_resources_only' },
  })
  // —— 当前选中的导师名（联动卡片 / 散点 / 右栏）——
  const selectedName = ref<string | null>(null)
  // —— 排序指标 ——
  const sortMetric = ref<SortMetric>('score')
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
        distribution.value = {
          departments: [],
          resource_types: [],
          meta: { grouped_advisors: 0, raw_resource_records: 0, basis: 'published_resources_only' },
        }
      } else {
        distribution.value = await advisorApi.fetchMentorDistribution()
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
        resultStatus.value = 'no_published_data'
        resultMessage.value =
          '前端独立 Mock 当前没有已审核导师数据，因此不会生成虚假推荐。'
        resultMeta.value = {
          total_records: 0,
          published_records: 0,
          withheld_records: 0,
          policy: 'verified_only',
        }
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

  return {
    matchedAdvisors,
    distribution,
    selectedName,
    selectedAdvisor,
    sortMetric,
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
    toggleComparison,
    resetResults,
  }
})
