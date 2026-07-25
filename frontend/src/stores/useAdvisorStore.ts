import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Advisor, MatchedAdvisor, SortMetric, ScatterPoint } from '@/types/advisor'
import * as advisorApi from '@/api/advisor'
import * as mockApi from '@/mock'

// =====================================================================
// 导师 Store（文档 §7.1 useAdvisorStore）
// 导师列表 / 当前选中 / 筛选排序 / 散点数据
// =====================================================================

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

export const useAdvisorStore = defineStore('advisor', () => {
  // —— 全量导师 ——
  const advisors = ref<Advisor[]>([])
  // —— 匹配后的导师（带 score / synergy / reason）——
  const matchedAdvisors = ref<MatchedAdvisor[]>([])
  // —— 散点数据 ——
  const scatterPoints = ref<ScatterPoint[]>([])
  // —— 当前选中的导师名（联动卡片 / 散点 / 右栏）——
  const selectedName = ref<string | null>(null)
  // —— 排序指标 ——
  const sortMetric = ref<SortMetric>('synergy')
  // —— 象限筛选（散点图右上复选框组）——
  const quadrantFilter = ref<Record<string, boolean>>({
    国热: true,
    国冷: true,
    私热: true,
    私冷: true,
  })
  // —— 加载态 ——
  const loading = ref(false)

  const totalCount = computed(() => matchedAdvisors.value.length || advisors.value.length)

  /** 当前选中的导师对象 */
  const selectedAdvisor = computed<MatchedAdvisor | null>(() => {
    if (!selectedName.value) return null
    return (
      matchedAdvisors.value.find((m) => m.name === selectedName.value) ||
      (advisors.value.find((m) => m.name === selectedName.value) as MatchedAdvisor | undefined) ||
      null
    )
  })

  /** 加载全量导师 + 散点数据 */
  async function loadAll() {
    loading.value = true
    try {
      if (USE_MOCK) {
        advisors.value = mockApi.mockAdvisors
        scatterPoints.value = mockApi.mockScatterPoints
      } else {
        const [a, s] = await Promise.all([advisorApi.fetchAdvisors(), advisorApi.fetchScatter()])
        advisors.value = a.data
        scatterPoints.value = s.data
      }
      // 默认匹配结果 = 全量（按 score 降序）
      matchedAdvisors.value = advisors.value.map((a) => ({
        ...a,
        score: a.score,
        reason: a.reason,
        synergy: 0,
      }))
    } finally {
      loading.value = false
    }
  }

  /** 综合匹配 */
  async function match(interest: string, portrait?: Record<string, unknown>, weight?: Record<string, number>) {
    loading.value = true
    try {
      if (USE_MOCK) {
        matchedAdvisors.value = mockApi.mockMatch(interest)
      } else {
        const res = await advisorApi.matchAdvisors({ interest, portrait, weight })
        matchedAdvisors.value = res.data
      }
      selectedName.value = null
    } finally {
      loading.value = false
    }
  }

  /** 按指标排序 */
  async function sortBy(metric: SortMetric) {
    sortMetric.value = metric
    if (metric === 'synergy') {
      matchedAdvisors.value.sort((a, b) => b.synergy - a.synergy || b.score - a.score)
      return
    }
    if (metric === 'popularity') {
      matchedAdvisors.value.sort((a, b) => b.popularity - a.popularity)
      return
    }
    // 六维雷达指标
    const key = metric as keyof typeof matchedAdvisors.value[number]['radar_traits']
    matchedAdvisors.value.sort((a, b) => (b.radar_traits[key] ?? 0) - (a.radar_traits[key] ?? 0))
  }

  /** 选中导师（联动） */
  function selectAdvisor(name: string | null) {
    selectedName.value = name
  }

  /** 设置象限筛选 */
  function toggleQuadrant(name: string, value: boolean) {
    quadrantFilter.value[name] = value
  }

  /** 按象限筛选后的散点 */
  const filteredScatter = computed(() =>
    scatterPoints.value.filter((p) => {
      const q = quadrantName(p.x, p.y)
      return quadrantFilter.value[q]
    }),
  )

  return {
    advisors,
    matchedAdvisors,
    scatterPoints,
    filteredScatter,
    selectedName,
    selectedAdvisor,
    sortMetric,
    quadrantFilter,
    loading,
    totalCount,
    loadAll,
    match,
    sortBy,
    selectAdvisor,
    toggleQuadrant,
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
