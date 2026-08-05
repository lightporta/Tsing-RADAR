import { get, post } from './request'
import type { RecruitmentItem } from '@/types/api'

// =====================================================================
// 招募信息平台 API
// =====================================================================

/** 获取招募列表，urgent=true 仅返回急需榜 */
export function fetchRecruitments(urgent?: boolean) {
  return get<{ data: RecruitmentItem[] }>('/api/recruitments', urgent === undefined ? {} : { urgent })
}

export interface RecruitmentCreateRequest {
  type: string
  title: string
  req: string
  major: string
  deadline: string
  is_urgent: boolean
}

/** 发布招募 */
export function publishRecruitment(req: RecruitmentCreateRequest) {
  return post<{ recruit_id: string; status: string }>('/api/recruitments', req)
}
