import { get, post } from './request'
import type {
  MatchedAdvisor,
  MentorResource,
  MentorResourceMeta,
  MentorResourceType,
  DepartmentOption,
  MentorDistribution,
} from '@/types/advisor'
import type { MatchRequest } from '@/types/api'

// =====================================================================
// 导师 / 匹配 / 散点图 API
// =====================================================================

export function fetchStudentDepartments() {
  return get<{
    data: Array<{ name: string }>
    meta: DepartmentCatalogMeta
  }>('/api/departments/students')
}

export interface DepartmentCatalogMeta {
  scope: 'mentor' | 'student'
  basis: string
  source: { name: string; url: string; version: string; as_of: string }
}

export function fetchMentorDepartments() {
  return get<{
    data: DepartmentOption[]
    meta: DepartmentCatalogMeta
  }>('/api/departments/mentors')
}

export function fetchMentorDistribution() {
  return get<MentorDistribution>('/api/mentor-distribution')
}

export function fetchMentorResources(
  params: {
    q?: string
    dept?: string
    resource_type?: MentorResourceType
    catalog_type?: 'doctoral_regular' | 'doctoral_recommendation_exempt'
    page?: number
    page_size?: number
  },
  signal?: AbortSignal,
) {
  return get<{ data: MentorResource[]; meta: MentorResourceMeta }>(
    '/api/mentors',
    params,
    { signal },
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
