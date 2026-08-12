import { get, post } from './request'
import type {
  MatchedAdvisor,
  MentorResource,
  MentorResourceMeta,
  MentorResourceType,
  ScatterPoint,
} from '@/types/advisor'
import type { MatchRequest } from '@/types/api'

// =====================================================================
// 导师 / 匹配 / 散点图 API
// =====================================================================

/** 获取四象限散点图数据 */
export function fetchScatter() {
  return get<{ data: ScatterPoint[] }>('/api/scatter')
}

export function fetchMentorResources(params: {
  q?: string
  dept?: string
  resource_type?: MentorResourceType
  catalog_type?: 'doctoral_general' | 'doctoral_recommendation_exempt'
  page?: number
  page_size?: number
}) {
  return get<{ data: MentorResource[]; meta: MentorResourceMeta }>(
    '/api/mentors',
    params,
  )
}

/** 综合匹配（关键词 + 画像向量契合度 + Synergy） */
export function matchAdvisors(req: MatchRequest) {
  return post<{
    data: MatchedAdvisor[]
    status: 'matched' | 'no_published_data' | 'no_match'
    message: string
    meta: Record<string, unknown>
  }>('/api/match', req)
}
