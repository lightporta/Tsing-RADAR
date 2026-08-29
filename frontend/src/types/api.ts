// =====================================================================
// 后端 API 统一响应类型
// =====================================================================

/** 列表型响应（{ data: T[] }） */
export interface ApiResponse<T> {
  data: T
}

/** 分页参数 */
export interface PageParams {
  page: number
  size: number
}

/** A4 可验证的多目标排序配置 */
export interface RankingWeights {
  topic_fit?: number
  research_mode_fit?: number
  mentorship_fit?: number
  career_fit?: number
  innovation_fit?: number
  opportunity_fit?: number
}

export interface RankingConfig {
  weights?: RankingWeights
  recall_pool_size?: number
  result_limit?: number
  minimum_recall_score?: number
}

/** 匹配请求 */
export interface MatchRequest {
  interest?: string
  session_id?: string
  ranking?: RankingConfig
  portrait?: Record<string, unknown>
  weight?: Record<string, number>
}

/** 匹配响应 */
export interface MatchResponse {
  data: import('./advisor').MatchedAdvisor[]
}

/** 评价反馈请求 */
export interface FeedbackRequest {
  advisor_id: string
  rating: 1 | -1
  comment?: string
}

/** 投递请求 */
export interface ResumeSubmitRequest {
  recruit_id: string
  document_id: string
  confirm_in_app_only: true
}

/** 招募项（列表用扁平结构；立体化扩展字段缺省时后端不下发对应键） */
export interface RecruitmentItem {
  recruit_id: string
  publisher_name: string
  publisher_type: string
  type: string
  title: string
  req: string
  major: string
  deadline: string
  is_urgent: boolean
  dept: string
  location?: string
  quota?: string
  compensation?: string
  duration?: string
  apply_method?: string
  tags?: string[]
  advisor_id?: string
}
