import { get, post, newIdempotencyKey } from './request'
import type {
  MyRatingItem,
  RatingListItem,
  RatingSubmitRequest,
  RatingSubmitResponse,
  RatingSummary,
} from '@/types/advisor'

// =====================================================================
// 学生评价体系 M1 API（六维匿名评分提交 + 聚合摘要 + 脱敏列表）
// =====================================================================

/** 提交六维评分；网络失败后的手动重试应复用同一幂等键 */
export function submitRating(
  advisorId: string,
  req: RatingSubmitRequest,
  idempotencyKey?: string,
) {
  return post<RatingSubmitResponse>(
    `/api/advisors/${encodeURIComponent(advisorId)}/ratings`,
    req,
    {
      headers: {
        'Idempotency-Key': idempotencyKey ?? newIdempotencyKey('rating'),
      },
    },
  )
}

/** 读取导师评分聚合摘要（无评分时返回 total_n=0 的诚实空态结构） */
export function getRatingSummary(advisorId: string) {
  return get<RatingSummary>(
    `/api/advisors/${encodeURIComponent(advisorId)}/ratings/summary`,
  )
}

/** 脱敏评价列表（仅在组时长 + 认证徽章 + 时间） */
export function listRatings(advisorId: string) {
  return get<{ data: RatingListItem[] }>(
    `/api/advisors/${encodeURIComponent(advisorId)}/ratings`,
  )
}

/** 当前会话提交过的全部评价 */
export function myRatings() {
  return get<{ data: MyRatingItem[] }>('/api/ratings/mine')
}
