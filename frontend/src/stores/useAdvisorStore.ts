import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { MatchedAdvisor, SortMetric, ScatterPoint } from '@/types/advisor'
import * as advisorApi from '@/api/advisor'
import * as mockApi from '@/mock'
import { useRuntimeStore } from '@/stores/useRuntimeStore'
import { useChatStore } from '@/stores/useChatStore'

// =====================================================================
// 导师 Store（文档 §7.1 useAdvisorStore）
// 导师列表 / 当前选中 / 筛选排序 / 散点数据
// =====================================================================

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

export const useAdvisorStore = defineStore('advisor', () => {
  const chatStore = useChatStore()
  // —— 匹配后的导师（带 score / synergy / reason）——
  const matchedAdvisors = ref<MatchedAdvisor[]>([])
  // —— 散点数据 ——
  const scatterPoints = ref<ScatterPoint[]>([])
  // 姓名只作展示；选中、对比和反馈均使用稳定导师 ID。
  const selectedId = ref<string | null>(null)
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
  const scatterLoading = ref(false)
  const resultStatus = ref<'idle' | 'matched' | 'no_published_data' | 'no_match' | 'error'>('idle')
  const resultMessage = ref('请先完成访谈并确认画像。')
  const resultMeta = ref<Record<string, unknown>>({})
  const comparisonIds = ref<string[]>([])
  let requestId = 0
  let scatterRequestId = 0
  let matchController: AbortController | null = null
  let activeProfileKey: string | null = null

  const totalCount = computed(() => matchedAdvisors.value.length)

  /** 当前选中的导师对象 */
  const selectedAdvisor = computed<MatchedAdvisor | null>(() => {
    if (!selectedId.value) return null
    return (
      matchedAdvisors.value.find((m) => m.advisor_id === selectedId.value) || null
    )
  })
  const selectedName = computed(() => selectedAdvisor.value?.name || null)

  function confirmedContext() {
    if (
      !chatStore.recommendReady ||
      chatStore.interviewStatus !== 'confirmed' ||
      !chatStore.sessionId ||
      chatStore.profileVersion === null
    ) return null
    return {
      sessionId: chatStore.sessionId,
      profileVersion: chatStore.profileVersion,
    }
  }

  function profileKey(context: { sessionId: string; profileVersion: number }) {
    return `${context.sessionId}:${context.profileVersion}`
  }

  const canRetry = computed(() => resultStatus.value === 'error' && !!confirmedContext())

  /** 首页只加载公开可视化；导师推荐必须由确认画像后的 bounded match 产生。 */
  async function loadAll() {
    const id = ++scatterRequestId
    scatterLoading.value = true
    try {
      if (USE_MOCK) {
        scatterPoints.value = mockApi.mockScatterPoints
      } else {
        const scatter = await advisorApi.fetchScatter()
        if (id === scatterRequestId) scatterPoints.value = scatter.data
      }
    } finally {
      if (id === scatterRequestId) scatterLoading.value = false
    }
  }

  /** 结果只属于发起请求时的已确认画像，路由挂载不参与其生命周期。 */
  async function runMatch(context: { sessionId: string; profileVersion: number }) {
    const id = ++requestId
    matchController?.abort()
    const controller = new AbortController()
    matchController = controller
    const key = profileKey(context)
    activeProfileKey = key
    clearResultData()
    loading.value = true
    resultMessage.value = '正在根据已确认画像匹配…'
    const isCurrent = () => {
      const current = confirmedContext()
      return id === requestId && !!current && profileKey(current) === key
    }
    try {
      if (USE_MOCK) {
        matchedAdvisors.value = []
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
        const res = await advisorApi.matchAdvisors(
          { session_id: context.sessionId },
          controller.signal,
        )
        if (!isCurrent()) return
        matchedAdvisors.value = res.data
        resultStatus.value = res.status
        resultMessage.value = res.message
        resultMeta.value = res.meta
        if (typeof res.meta?.policy === 'string') {
          useRuntimeStore().applySessionMeta({ mentor_policy: res.meta.policy })
        }
      }
    } catch (error) {
      if (!isCurrent() || controller.signal.aborted) return
      resultStatus.value = 'error'
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      resultMessage.value =
        typeof detail === 'string'
          ? detail
          : typeof detail === 'object' && detail && 'message' in detail
            ? String((detail as { message: unknown }).message)
            : '匹配请求失败，可以重新匹配；如画像仍有待澄清条件，请先修改并确认。'
    } finally {
      if (id === requestId) {
        loading.value = false
        matchController = null
      }
    }
  }

  async function retryMatch() {
    const context = confirmedContext()
    if (context && !loading.value) await runMatch(context)
  }

  /** 按指标排序 */
  async function sortBy(metric: SortMetric) {
    sortMetric.value = metric
    matchedAdvisors.value.sort(
      (a, b) => Number(b[metric] ?? 0) - Number(a[metric] ?? 0),
    )
  }

  /** 选中导师（联动） */
  function selectAdvisor(idOrName: string | null) {
    if (!idOrName) {
      selectedId.value = null
      return
    }
    const byId = matchedAdvisors.value.find((item) => item.advisor_id === idOrName)
    const byName = matchedAdvisors.value.filter((item) => item.name === idOrName)
    selectedId.value = byId?.advisor_id || (byName.length === 1 ? byName[0].advisor_id : null)
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

  function clearResultData() {
    matchedAdvisors.value = []
    selectedId.value = null
    comparisonIds.value = []
    resultStatus.value = 'idle'
    resultMessage.value = '请先完成访谈并确认画像。'
    resultMeta.value = {}
  }

  function resetResults() {
    requestId++
    matchController?.abort()
    matchController = null
    activeProfileKey = null
    loading.value = false
    clearResultData()
  }

  // Pinia store 的订阅在跨路由时持续存在；确认门或版本变化统一在此编排。
  watch(
    () => [chatStore.recommendReady, chatStore.interviewStatus, chatStore.sessionId, chatStore.profileVersion] as const,
    () => {
      const context = confirmedContext()
      if (!context) {
        resetResults()
      } else if (profileKey(context) !== activeProfileKey) {
        void runMatch(context)
      }
    },
    { immediate: true },
  )

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
    selectedId,
    selectedAdvisor,
    sortMetric,
    quadrantFilter,
    loading,
    scatterLoading,
    canRetry,
    totalCount,
    resultStatus,
    resultMessage,
    resultMeta,
    comparisonIds,
    comparedAdvisors,
    loadAll,
    retryMatch,
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
