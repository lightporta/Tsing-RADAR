import { get, post } from './request'
import type { Advisor, MatchedAdvisor, ScatterPoint, SortMetric } from '@/types/advisor'
import type { MatchRequest } from '@/types/api'

// =====================================================================
// 导师 / 匹配 / 散点图 API
// =====================================================================

/** 获取全部导师（含六维雷达 / 热门指数 / 行业性质） */
export function fetchAdvisors() {
  return get<{ data: Advisor[] }>('/api/mentors')
}

/** 按指标排序导师（六维 + 热门指数） */
export function sortAdvisors(metric: SortMetric) {
  return get<{ data: Advisor[]; metric: string }>('/api/mentors/sort', { metric })
}

/** 获取四象限散点图数据 */
export function fetchScatter() {
  return get<{ data: ScatterPoint[] }>('/api/scatter')
}

/** 综合匹配（关键词 + 画像向量契合度 + Synergy） */
export function matchAdvisors(req: MatchRequest) {
  return post<{ data: MatchedAdvisor[] }>('/api/match', req)
}

/** 清小搭兼容接口（关键词匹配，返回 OpenAI 风格 choices） */
export function legacyChat(interest: string) {
  return post<{
    choices: { message: { role: string; content: string } }[]
  }>('/api/v1/chat/completions', { interest })
}
