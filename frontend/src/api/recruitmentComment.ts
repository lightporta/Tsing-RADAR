import { get, post, remove } from './request'

// =====================================================================
// 招募评论 API（两级树；公开输出无作者身份，徽章由服务端计算）
// =====================================================================

export interface CommentNode {
  comment_id: string
  badge: string
  is_op: boolean
  /** 当前会话主体是否作者（仅用于展示删除入口，不代表身份） */
  own: boolean
  content: string
  deleted: boolean
  like_count: number
  created_at: string | null
  replies?: CommentNode[]
  reply_total?: number
}

export interface CommentTreeResult {
  data: CommentNode[]
  meta: { total: number; page: number; page_size: number }
}

export function fetchComments(recruitId: string, page: number, pageSize = 10) {
  return get<CommentTreeResult>(`/api/recruitments/${recruitId}/comments`, {
    page,
    page_size: pageSize,
  })
}

export interface CommentMutationResult {
  comment_id: string
  recruit_id?: string
  review_status?: 'approved' | 'pending_review'
  deleted?: boolean
  like_count?: number
}

export function postComment(
  recruitId: string,
  content: string,
  parentId: string | null,
  key: string,
) {
  return post<CommentMutationResult>(
    `/api/recruitments/${recruitId}/comments`,
    { content, parent_id: parentId },
    { headers: { 'Idempotency-Key': key } },
  )
}

export function likeComment(recruitId: string, commentId: string, key: string) {
  return post<CommentMutationResult>(
    `/api/recruitments/${recruitId}/comments/${commentId}/like`,
    {},
    { headers: { 'Idempotency-Key': key } },
  )
}

export function reportComment(
  recruitId: string,
  commentId: string,
  reason: string,
  key: string,
) {
  return post<CommentMutationResult>(
    `/api/recruitments/${recruitId}/comments/${commentId}/report`,
    { reason },
    { headers: { 'Idempotency-Key': key } },
  )
}

export function deleteComment(recruitId: string, commentId: string, key: string) {
  return remove<CommentMutationResult>(
    `/api/recruitments/${recruitId}/comments/${commentId}`,
    { headers: { 'Idempotency-Key': key } },
  )
}
