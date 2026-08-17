import { get, patch, post, remove } from './request'
import type { RecruitmentItem } from '@/types/api'

export function fetchRecruitments(urgent?: boolean) {
  return get<{ data: RecruitmentItem[] }>(
    '/api/recruitments',
    urgent === undefined ? {} : { urgent },
  )
}

export interface RecruitmentFormData {
  type: string
  title: string
  req: string
  major: string
  deadline: string
  is_urgent: boolean
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
