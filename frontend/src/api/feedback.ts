import { post } from './request'
import type { FeedbackRequest } from '@/types/api'

// =====================================================================
// 评价反馈 API（点赞 / 点踩 + 评论）
// =====================================================================

export function submitFeedback(req: FeedbackRequest) {
  return post<{ feedback_id: string; status: string }>('/api/feedback', req)
}
