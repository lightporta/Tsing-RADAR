// =====================================================================
// 管理员审批 API（/api/admin/mentor/*）
// 通过 X-Admin-Token 鉴权；调用方需传入管理员令牌（不持久化到本地存储）
// =====================================================================

import { get, post } from './request'
import type {
  AdminMentorClaimItem,
  MentorEditRecord,
  MentorTakedownRecord,
} from '@/types/mentor'

function adminHeaders(token: string) {
  return { headers: { 'X-Admin-Token': token } }
}

// ---------------------------------------------------------------- 认领

export function fetchAdminMentorClaims(token: string, status?: string) {
  return get<{ data: AdminMentorClaimItem[] }>(
    '/api/admin/mentor/claims',
    status ? { status } : undefined,
    adminHeaders(token),
  )
}

export function reviewMentorClaim(
  token: string,
  claimId: string,
  action: 'approve' | 'reject',
  note?: string,
) {
  return post<{ claim_id: string; status: string }>(
    `/api/admin/mentor/claims/${claimId}/review`,
    { action, note },
    adminHeaders(token),
  )
}

// ---------------------------------------------------------------- 字段编辑

export function fetchAdminMentorEdits(token: string, status?: string) {
  return get<{ data: MentorEditRecord[] }>(
    '/api/admin/mentor/profile-edits',
    status ? { status } : undefined,
    adminHeaders(token),
  )
}

export function reviewMentorEdit(
  token: string,
  editId: string,
  action: 'approve' | 'reject',
  note?: string,
) {
  return post<{ edit_id: string; status: string }>(
    `/api/admin/mentor/profile-edits/${editId}/review`,
    { action, note },
    adminHeaders(token),
  )
}

// ---------------------------------------------------------------- 下架

export function fetchAdminMentorTakedowns(token: string, status?: string) {
  return get<{ data: MentorTakedownRecord[] }>(
    '/api/admin/mentor/takedowns',
    status ? { status } : undefined,
    adminHeaders(token),
  )
}

export function reviewMentorTakedown(
  token: string,
  reqId: string,
  action: 'approve' | 'reject',
  note?: string,
) {
  return post<{ req_id: string; status: string }>(
    `/api/admin/mentor/takedowns/${reqId}/review`,
    { action, note },
    adminHeaders(token),
  )
}
