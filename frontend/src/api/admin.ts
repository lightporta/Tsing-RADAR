// =====================================================================
// 管理员审批 API（/api/admin/mentor/*）
// 通过 X-Admin-Token 鉴权；调用方需传入管理员令牌（不持久化到本地存储）
// 后端 MentorReviewRequest 要求 reviewer（审核人）必填，note 校园卡必填
// =====================================================================

import { get, post } from './request'
import type {
  AdminCampusCardItem,
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
  reviewer: string,
  note?: string,
) {
  return post<{ claim_id: string; status: string }>(
    `/api/admin/mentor/claims/${claimId}/review`,
    { action, reviewer, note },
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
  reviewer: string,
  note?: string,
) {
  return post<{ edit_id: string; status: string }>(
    `/api/admin/mentor/profile-edits/${editId}/review`,
    { action, reviewer, note },
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
  reviewer: string,
  note?: string,
) {
  return post<{ req_id: string; status: string }>(
    `/api/admin/mentor/takedowns/${reqId}/review`,
    { action, reviewer, note },
    adminHeaders(token),
  )
}

// ---------------------------------------------------------------- 校园卡
// 认领导师档案的前置身份审核；审核说明必填，终态后材料立即清理

export function fetchAdminCampusCards(token: string, status?: string) {
  return get<{ data: AdminCampusCardItem[] }>(
    '/api/admin/mentor/campus-cards',
    status ? { status } : undefined,
    adminHeaders(token),
  )
}

export function reviewCampusCard(
  token: string,
  cardId: string,
  action: 'approve' | 'reject',
  reviewer: string,
  note: string,
) {
  return post<{ card_id: string; status: string; material_cleared: boolean }>(
    `/api/admin/mentor/campus-cards/${cardId}/review`,
    { action, reviewer, note },
    adminHeaders(token),
  )
}
