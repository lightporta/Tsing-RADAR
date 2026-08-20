import { get, patch, post, remove } from './request'
import type { RecruitmentItem } from '@/types/api'

export function fetchRecruitments(filters?: {
  urgent?: boolean
  tag?: string
  advisor_id?: string
}) {
  const params: Record<string, unknown> = {}
  if (filters?.urgent !== undefined) params.urgent = filters.urgent
  if (filters?.tag) params.tag = filters.tag
  if (filters?.advisor_id) params.advisor_id = filters.advisor_id
  return get<{ data: RecruitmentItem[] }>('/api/recruitments', params)
}

/** 招募详情（公开口径；不存在/未公开返回 404） */
export interface RecruitmentDetail extends RecruitmentItem {
  created_at?: string | null
  verified_at?: string | null
  advisor: { advisor_id: string; name: string; dept: string } | null
  related: RecruitmentItem[]
}

export function fetchRecruitmentDetail(recruitId: string) {
  return get<{ data: RecruitmentDetail }>(`/api/recruitments/${recruitId}`)
}

export interface RecruitmentFormData {
  type: string
  title: string
  req: string
  major: string
  deadline: string
  is_urgent: boolean
  // 立体化扩展（全部选填）
  location?: string
  quota?: string
  compensation?: string
  duration?: string
  apply_method?: string
  tags?: string[]
  advisor_id?: string
}

export interface RecruitmentMutationResult {
  recruit_id: string
  status: 'pending_review'
  publication_status: 'restricted'
  updated?: boolean
}

export function publishRecruitment(
  req: RecruitmentFormData,
  idempotencyKey: string,
) {
  return post<RecruitmentMutationResult>('/api/recruitments', req, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export interface MyRecruitment extends RecruitmentFormData {
  recruit_id: string
  review_status: string
  publication_status: string
  review_reason?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** 编辑回填的最小结构（学生端 MyRecruitment 与导师端 MentorRecruitmentItem 均满足） */
export interface EditableRecruitment {
  recruit_id: string
  type: string
  title: string
  req: string
  major: string
  deadline?: string | null
  is_urgent: boolean
  location?: string | null
  quota?: string | null
  compensation?: string | null
  duration?: string | null
  apply_method?: string | null
  tags?: string[] | null
  advisor_id?: string | null
}

export function fetchMyRecruitments() {
  return get<{ data: MyRecruitment[] }>('/api/recruitments/mine')
}

export function updateRecruitment(
  recruitId: string,
  req: RecruitmentFormData,
  idempotencyKey: string,
) {
  return patch<RecruitmentMutationResult>(
    `/api/recruitments/${recruitId}`,
    { ...req, submit_for_review: true },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function withdrawRecruitment(
  recruitId: string,
  idempotencyKey: string,
) {
  return remove<{ status: 'withdrawn'; recruit_id: string }>(
    `/api/recruitments/${recruitId}`,
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}
