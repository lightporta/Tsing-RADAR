// =====================================================================
// 导师服务 API（/api/mentor/*）
// 邮箱验证码登录 → 档案认领 → 字段编辑 → 意向中心 → 招募 → 隐私
// =====================================================================

import { get, patch, post, remove } from './request'
import type {
  MentorAuthStatus,
  MentorCampusCardStatus,
  MentorCandidate,
  MentorClaimRecord,
  MentorClaimResult,
  MentorEditRecord,
  MentorFeedbackSummary,
  MentorInboundApplications,
  MentorInboundMatches,
  MentorPrivacyStatus,
  MentorProfile,
  MentorRecruitmentItem,
  MentorTakedownRecord,
} from '@/types/mentor'
import type { RecruitmentFormData } from './recruitment'

// ---------------------------------------------------------------- 登录

export function fetchMentorAuthStatus() {
  return get<MentorAuthStatus>('/api/mentor/auth/status')
}

export function sendMentorEmailCode(email: string) {
  return post<{ status: 'sent'; expires_in: number }>('/api/mentor/auth/email-code', {
    email,
  })
}

export function mentorLogin(email: string, code: string) {
  return post<MentorAuthStatus>('/api/mentor/auth/login', { email, code })
}

export function mentorLogout() {
  return post<{ logged_in: false }>('/api/mentor/auth/logout')
}

// ---------------------------------------------------------------- 校园卡
// 认领导师档案的前置身份审核：邮箱验证码只用于登录

export function fetchCampusCardStatus() {
  return get<MentorCampusCardStatus>('/api/mentor/verification/campus-card')
}

export function uploadCampusCard(file: File) {
  const form = new FormData()
  form.append('upload', file)
  return post<{ status: string; card_id: string; scan_method: string }>(
    '/api/mentor/verification/campus-card',
    form,
  )
}

// ---------------------------------------------------------------- 认领

export interface MentorClaimEligibleResult {
  data: MentorCandidate[]
  meta: { basis: string }
}

export function fetchMentorClaimEligible(name: string, department: string) {
  return get<MentorClaimEligibleResult>('/api/mentor/claim/eligible', {
    name,
    department,
  })
}

export function submitMentorClaim(body: {
  candidate_id: string
  name: string
  department: string
}) {
  return post<MentorClaimResult>('/api/mentor/claim', body)
}

export function fetchMentorClaimHistory() {
  return get<{ data: MentorClaimRecord[] }>('/api/mentor/claim/history')
}

// ---------------------------------------------------------------- 档案

export function fetchMentorProfile() {
  return get<MentorProfile>('/api/mentor')
}

export function fetchMyMentorEdits() {
  return get<{ data: MentorEditRecord[] }>('/api/mentor/profile/edits')
}

export function submitMentorFieldEdit(fieldName: string, newValue: string) {
  return post<{ edit_id: string; field_name: string; status: string }>(
    '/api/mentor/profile/edits',
    { field_name: fieldName, new_value: newValue },
  )
}

// ---------------------------------------------------------------- 意向中心

export function fetchMentorInboundMatches() {
  return get<MentorInboundMatches>('/api/mentor/inbound/matches')
}

export function fetchMentorInboundApplications() {
  return get<MentorInboundApplications>('/api/mentor/inbound/applications')
}

export function fetchMentorInboundFeedback() {
  return get<MentorFeedbackSummary>('/api/mentor/inbound/feedback')
}

// ---------------------------------------------------------------- 招募

export function fetchMyMentorRecruitments() {
  return get<{ data: MentorRecruitmentItem[] }>('/api/mentor/recruitments')
}

export function publishMentorRecruitment(
  req: RecruitmentFormData,
  idempotencyKey: string,
) {
  return post<{ recruit_id: string; status: string; publication_status: string }>(
    '/api/mentor/recruitments',
    req,
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function updateMentorRecruitment(
  recruitId: string,
  req: RecruitmentFormData,
  idempotencyKey: string,
) {
  return patch<{ recruit_id: string; status: string; publication_status: string }>(
    `/api/mentor/recruitments/${recruitId}`,
    { ...req, submit_for_review: true },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function withdrawMentorRecruitment(recruitId: string, idempotencyKey: string) {
  return remove<{ status: 'withdrawn'; recruit_id: string }>(
    `/api/mentor/recruitments/${recruitId}`,
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

// ---------------------------------------------------------------- 隐私

export function fetchMentorPrivacyStatus() {
  return get<MentorPrivacyStatus>('/api/mentor/privacy')
}

export function updateMentorVisibility(visibility: Record<string, boolean>) {
  return patch<{ visibility: Record<string, boolean> }>(
    '/api/mentor/privacy/visibility',
    { visibility },
  )
}

export function fetchMyMentorTakedowns() {
  return get<{ data: MentorTakedownRecord[] }>('/api/mentor/privacy/takedowns')
}

export function submitMentorTakedown(body: {
  reason: string
  scope: 'full' | 'field'
  field_name?: string
}) {
  return post<{ req_id: string; status: string }>('/api/mentor/privacy/takedowns', body)
}
