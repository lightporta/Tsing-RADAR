import { reactive } from 'vue'
import { getRatingSummary } from '@/api/rating'
import type { RatingSummary } from '@/types/advisor'

// =====================================================================
// 学生评价聚合摘要缓存（按 advisor_id）
// 仅详情面板与大雷达图主动拉取；卡片角标只读缓存，避免列表 N+1
// =====================================================================

const cache = reactive(new Map<string, RatingSummary>())
const pending = new Set<string>()

export function useRatingSummary() {
  /** 拉取并缓存指定导师的评分摘要；进行中或已缓存的请求自动去重 */
  async function ensureRatingSummary(advisorId: string): Promise<void> {
    if (!advisorId || cache.has(advisorId) || pending.has(advisorId)) return
    pending.add(advisorId)
    try {
      const summary = await getRatingSummary(advisorId)
      cache.set(advisorId, summary)
    } catch {
      // 静默失败：摘要缺失不阻塞导师信息展示，空态由调用方诚实兜底
    } finally {
      pending.delete(advisorId)
    }
  }

  /** 已缓存则返回摘要（无评分导师 total_n=0），从未拉取返回 undefined */
  function peekRatingSummary(advisorId: string): RatingSummary | undefined {
    return cache.get(advisorId)
  }

  /** 提交成功后失效缓存，下次拉取获得新聚合结果 */
  function invalidateRatingSummary(advisorId: string): void {
    cache.delete(advisorId)
  }

  return {
    ensureRatingSummary,
    peekRatingSummary,
    invalidateRatingSummary,
  }
}
