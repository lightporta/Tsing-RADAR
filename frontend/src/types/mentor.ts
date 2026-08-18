// =====================================================================
// 导师服务类型（后端 /api/mentor/* 与 /api/admin/mentor/*）
// 认领、档案编辑、意向中心、招募管理、隐私控制、管理员审批
// =====================================================================

/** 登录状态（GET /api/mentor/auth/status） */
export interface MentorAuthStatus {
  logged_in: boolean
  email?: string
  status?: string
  advisor_id?: string | null
}

/** 可认领候选（GET /api/mentor/claim/eligible） */
export interface MentorCandidate {
  advisor_id: string
  name: string
  dept: string
  title?: string | null
  resource_types?: unknown
  in_db: boolean
}

/** 认领提交结果（POST /api/mentor/claim） */
export interface MentorClaimResult {
  status: 'claimed' | 'pending_review'
  claim_id: string
  factor?: string
}

/** 认领历史记录 */
export interface MentorClaimRecord {
  claim_id: string
  advisor_id: string
  candidate_json: unknown
  factor_used: string
  status: string
  admin_note?: string | null
  created_at?: string | null
  decided_at?: string | null
}

/** 导师档案（GET /api/mentor，导师端/管理端视图） */
export interface MentorProfile {
  advisor_id: string
  name?: string | null
  dept?: string | null
  public_fields: Record<string, unknown>
  self_claims: Record<string, string>
  hidden_fields: string[]
  provenance: Record<string, unknown>
  data_status?: string | null
  takedown: {
    active: boolean
    effective_at?: string | null
  }
  visibility: Record<string, boolean>
}

/** 字段编辑申请记录 */
export interface MentorEditRecord {
  edit_id: string
  account_id: string
  advisor_id: string
  field_name: string
  old_value?: string | null
  new_value?: string | null
  status: string
  admin_note?: string | null
  created_at?: string | null
  decided_at?: string | null
}

/** 匹配意向（GET /api/mentor/inbound/matches，学生身份匿名化） */
export interface MentorInboundMatches {
  total: number
  recent: Array<{
    record_id: string
    synergy_score?: number
    match_reason?: string | null
    created_at?: string | null
  }>
}

/** 站内投递（GET /api/mentor/inbound/applications，匿名化摘要） */
export interface MentorInboundApplications {
  total: number
  data: Array<{
    app_id: string
    recruit_id: string
    status: string
    created_at?: string | null
    resume: {
      present: boolean
      extension?: string | null
      size_bytes?: number | null
    }
  }>
}

/** 反馈计数（GET /api/mentor/inbound/feedback，不含评论正文） */
export interface MentorFeedbackSummary {
  total: number
  positive: number
  negative: number
}

/** 导师自己的招募（GET /api/mentor/recruitments） */
export interface MentorRecruitmentItem {
  recruit_id: string
  type: string
  title: string
  req: string
  major: string
  deadline?: string | null
  is_urgent: boolean
  review_status: string
  publication_status: string
  review_reason?: string | null
  created_at?: string | null
  updated_at?: string | null
  // 立体化扩展（全部选填）
  location?: string | null
  quota?: string | null
  compensation?: string | null
  duration?: string | null
  apply_method?: string | null
  tags?: string[] | null
  advisor_id?: string | null
}

/** 隐私状态（GET /api/mentor/privacy） */
export interface MentorPrivacyStatus {
  visibility: Record<string, boolean>
  takedown: {
    active: boolean
    effective_at?: string | null
  }
}

/** 下架申请记录 */
export interface MentorTakedownRecord {
  req_id: string
  reason: string
  scope: 'full' | 'field'
  field_name?: string | null
  status: string
  admin_note?: string | null
  created_at?: string | null
  decided_at?: string | null
}

/** 管理端：认领审批列表项 */
export interface AdminMentorClaimItem {
  claim_id: string
  advisor_id: string
  candidate_json: unknown
  factor_used: string
  status: string
  admin_note?: string | null
  created_at?: string | null
}

/** 导师自述字段白名单（与后端 SELF_CLAIM_FIELDS 一致） */
export const SELF_CLAIM_FIELD_META: Record<
  string,
  { label: string; placeholder: string }
> = {
  self_intro: {
    label: '导师自述',
    placeholder: '介绍您的研究领域、带学生风格等（过审后对本人与管理员可见）',
  },
  research_highlights: {
    label: '研究方向亮点',
    placeholder: '近期重点研究方向与代表性进展',
  },
  recruiting_requirements: {
    label: '招生要求',
    placeholder: '对学生的背景、能力与时间投入的期望',
  },
  contact_display_policy: {
    label: '联系方式展示策略',
    placeholder: '希望以何种方式向学生展示联系方式（如邮件前缀规则等）',
  },
}

/** 可见性控制字段（与后端 VISIBILITY_FIELDS 一致） */
export const VISIBILITY_FIELD_META: Record<string, { label: string }> = {
  self_intro: { label: '导师自述' },
  research_highlights: { label: '研究方向亮点' },
  recruiting_requirements: { label: '招生要求' },
  contact_display_policy: { label: '联系方式展示策略' },
  contact_email: { label: '公开联系方式' },
  office_loc: { label: '办公室位置' },
  official_homepage: { label: '个人主页' },
}

/** 导师账号状态中文标签 */
export const MENTOR_STATUS_LABELS: Record<string, string> = {
  unclaimed: '未认领',
  claim_pending: '认领待审核',
  claimed: '已认领',
}

/** 审批流通用状态标签 */
export const REVIEW_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  approved: '已通过',
  rejected: '已驳回',
}
