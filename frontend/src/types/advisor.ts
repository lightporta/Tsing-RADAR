// =====================================================================
// 导师（Advisor）相关类型定义
// 对应后端 mentors 数据结构 + 散点图 / 雷达图 / 招募数据
// =====================================================================

/** 六维雷达特质键（与后端 TRAIT_KEYS 一一对应） */
export type TraitKey =
  | 'acumen' // 学术敏锐度
  | 'network' // 人脉资源
  | 'mentorship' // 指导意愿
  | 'tolerance' // 性格包容度
  | 'funding' // 经费实力
  | 'efficiency' // 产出效率

/** 六维雷达特质得分（0-100） */
export type RadarTraits = Record<TraitKey, number>

/** 行业性质：国 = 国有机构方向，私 = 私营企业方向 */
export type Sector = '国' | '私'

/** 导师在研项目 */
export interface AdvisorProject {
  title: string
  desc: string
  fund: string
}

/** 招募信息 */
export interface Recruitment {
  type: string // 实习 / 科研助理 / 招生
  title: string
  req: string
  major: string
  deadline: string
  is_urgent?: boolean
}

/** 导师基础画像（仅用于通过证据审核后的公开记录） */
export interface Advisor {
  name: string
  dept: string
  field: string
  tags: string[]
  score: number
  reason: string
  radar_traits: RadarTraits
  popularity: number // 热门指数 0-100
  sector: Sector // 行业性质
  projects: AdvisorProject[]
  recruitments: Recruitment[]
  contact_email?: string
  office_loc?: string
}

/** 匹配后的导师（追加计算字段） */
export interface MatchedAdvisor extends Advisor {
  advisor_id: string
  /** 综合匹配分（关键词 + 画像向量契合度） */
  score: number
  /** 一句话推荐理由 */
  reason: string
  /** 合伙人契合指数 Synergy Score（0-100，仅当学生填写六维权重时计算） */
  synergy: number
  fit_score?: number
  evidence_coverage?: number
  evidence_confidence?: number
  recall_score?: number
  explanation?: {
    supporting_evidence: EvidenceClaim[]
    counter_evidence: EvidenceClaim[]
    uncertainties: string[]
    questions_to_verify: string[]
  }
  score_breakdown?: Array<{
    objective: string
    score?: number | null
    evidence_coverage: number
    evidence_confidence: number
  }>
}

export interface PublicCitation {
  evidence_id: string
  citation_type: string
  citation: string
  source_url?: string | null
  captured_at: string
  confidence: number
}

export type MentorResourceType =
  | 'verified_mentor_profile'
  | 'mentor_catalog_entry'
  | 'advisor_group_catalog_entry'

export interface MentorResource {
  advisor_id: string
  name: string
  dept: string
  title?: string
  official_homepage?: string
  entity_type: 'person' | 'advisor_group'
  resource_type: MentorResourceType
  identity_status?: 'verified'
  recommendation_eligibility?: 'eligible'
  academic_year?: number
  catalog_types?: Array<'doctoral_regular' | 'doctoral_recommendation_exempt'>
  programs?: string[]
  research_keywords?: string[]
  catalog_entries?: Array<{
    catalog_type: string
    department_code: string
    program_code: string
    direction_code: string
  }>
  provenance: Record<string, PublicCitation[]>
  data_status: {
    review_status: string
    verified_at?: string | null
    expires_at?: string | null
  }
}

export interface MentorResourceMeta {
  total_records: number
  published_records: number
  withheld_records: number
  catalog_records: number
  verified_profile_records: number
  match_candidate_records: number
  policy: 'formal_verified_profiles_only'
  filtered_records: number
  page: number
  page_size: number
  total_pages: number
}

export interface EvidenceClaim {
  statement: string
  citations: PublicCitation[]
}

/** 散点图单个数据点 */
export interface ScatterPoint {
  name: string
  x: number // 热门指数 0-100
  y: number // 行业性质 0=国 / 1=私
  color: string // 院系颜色
  dept: string
  value?: number // 契合度（散点半径映射）
  advisor?: Advisor
}

/** 排序指标 */
export type SortMetric =
  | 'score'
  | 'fit_score'
  | 'evidence_coverage'
  | 'evidence_confidence'

/** 六维度元数据（中文标签 + 英文键），用于雷达图与表单 */
export interface TraitMeta {
  key: TraitKey
  label: string
  description: string
}

/** 六维度常量定义（前端单点真相） */
export const TRAITS: TraitMeta[] = [
  { key: 'acumen', label: '学术敏锐度', description: '前沿课题捕捉能力、顶会/顶刊发表能力' },
  { key: 'network', label: '人脉资源', description: '学术界人脉、工业界合作资源、推荐出国/就业能力' },
  { key: 'mentorship', label: '指导意愿', description: '手把手指导频率、组会交流深度、对学生心理的关注度' },
  { key: 'tolerance', label: '性格包容度', description: '对失败的包容度、管理风格、情绪稳定性' },
  { key: 'funding', label: '经费实力', description: '课题组算力/实验设备充裕度、助研津贴发放水平' },
  { key: 'efficiency', label: '产出效率', description: '论文审稿周期、学生平均毕业年限、延毕率' },
]

/** 六维度中文键映射 */
export const TRAIT_LABEL_MAP: Record<TraitKey, string> = TRAITS.reduce(
  (acc, t) => ({ ...acc, [t.key]: t.label }),
  {} as Record<TraitKey, string>,
)
