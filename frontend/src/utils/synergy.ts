import type { RadarTraits, TraitKey } from '@/types/advisor'
import { TRAITS } from '@/types/advisor'

// =====================================================================
// 合伙人契合指数（Synergy Score）前端镜像实现
// 与后端 services/matching.py 保持一致：极坐标六维多边形 + Shoelace 面积 + per-dim min 近似交集
// 公式：synergy = area(学生需求 ∩ 导师特质) / area(学生需求) × 100
// =====================================================================

const TRAIT_KEYS = TRAITS.map((t) => t.key) as TraitKey[]

/** 极坐标 → 笛卡尔坐标（6 个维度均分 60°） */
function toCartesian(values: number[]): Array<[number, number]> {
  return values.map((v, i) => {
    const angle = (i * 60 * Math.PI) / 180
    return [v * Math.cos(angle), v * Math.sin(angle)]
  })
}

/** Shoelace 公式计算多边形面积 */
function polygonArea(poly: Array<[number, number]>): number {
  const n = poly.length
  if (n < 3) return 0
  let sum = 0
  for (let i = 0; i < n; i++) {
    const [x1, y1] = poly[i]
    const [x2, y2] = poly[(i + 1) % n]
    sum += x1 * y2 - x2 * y1
  }
  return Math.abs(sum) / 2
}

/**
 * 计算导师对学生的契合指数
 * @param studentWeights 学生六维需求权重（0-100）
 * @param mentorTraits 导师六维特质（0-100）
 * @returns 0-100 的契合百分比
 */
export function computeSynergy(
  studentWeights: Record<TraitKey, number>,
  mentorTraits: RadarTraits,
): number {
  const sVals = TRAIT_KEYS.map((k) => Number(studentWeights[k] ?? 0))
  const mVals = TRAIT_KEYS.map((k) => Number(mentorTraits[k] ?? 0))
  const sArea = polygonArea(toCartesian(sVals))
  if (sArea <= 0) return 0
  const interVals = sVals.map((s, i) => Math.min(s, mVals[i]))
  const interArea = polygonArea(toCartesian(interVals))
  return Math.round((interArea / sArea) * 1000) / 10 // 保留 1 位小数
}

/** 找出导师特质中最强的 N 个维度，用于生成匹配理由 */
export function topTraits(traits: RadarTraits, n = 3): TraitKey[] {
  return [...TRAIT_KEYS]
    .sort((a, b) => (traits[b] ?? 0) - (traits[a] ?? 0))
    .slice(0, n)
}
