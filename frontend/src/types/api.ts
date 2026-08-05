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

/** 匹配请求 */
export interface MatchRequest {
  interest: string
  portrait?: Record<string, unknown>
  weight?: Record<string, number>
}

/** 匹配响应 */
export interface MatchResponse {
  data: import('./advisor').MatchedAdvisor[]
}

/** 评价反馈请求 */
export interface FeedbackRequest {
  student_id: string
  advisor_id: string
  rating: 1 | -1
  comment?: string
}

/** 投递请求 */
export interface ResumeSubmitRequest {
  recruit_id: string
  student_id: string
  resume_id: string
}

/** 招募项（列表用扁平结构） */
export interface RecruitmentItem {
  recruit_id: string
  publisher_name: string
  publisher_type: 'advisor' | 'senior'
  type: string
  title: string
  req: string
  major: string
  deadline: string
  is_urgent: boolean
  dept: string
}
