export type InterviewStatus = 'in_progress' | 'awaiting_confirmation' | 'confirmed'

export type InterviewDimension =
  | 'research_interests'
  | 'research_mode'
  | 'mentorship_style'
  | 'career_orientation'
  | 'innovation_risk'
  | 'hard_constraints'

export type HardConstraintField =
  | 'location'
  | 'weekly_commitment_days'
  | 'degree_stage'
  | 'language'
  | 'confidentiality'
  | 'graduation_arrangement'
  | 'department'
  | 'research_topic'
  | 'advisor_id'

export type HardConstraintOperator =
  | 'equals'
  | 'one_of'
  | 'excludes'
  | 'contains'
  | 'minimum'
  | 'maximum'

export interface HardConstraint {
  field: HardConstraintField
  operator: HardConstraintOperator
  value: string[]
  source_text?: string | null
}

export interface HardConstraintCapability {
  field: HardConstraintField
  label: string
  available: boolean
  evidence_record_count: number
  candidate_count: number
  evidence_coverage: number
  operators: HardConstraintOperator[]
  values: string[]
  accepts_free_text: boolean
  unavailable_reason: string | null
}

export interface HardConstraintCapabilities {
  version: 'hard-constraints-v1'
  candidate_count: number
  fields: HardConstraintCapability[]
  basis: 'published_verified_candidate_fields'
}

export interface DraftHardConstraint {
  draft_id: string
  source_text: string
  proposed_constraint: HardConstraint | null
  parsing_confidence: number
  confirmation_prompt: string
}

export interface InterviewPortrait {
  research_interests: string[]
  interest_statement: string | null
  /** 兴趣探索（活动兴趣题）选择的活动键；仅用于回显，不参与匹配 */
  activity_interests?: string[]
  research_mode: 'theory' | 'engineering' | 'mixed' | 'undecided' | null
  mentorship_style: 'high_guidance' | 'balanced' | 'autonomous' | 'undecided' | null
  career_orientation:
    | 'academic'
    | 'industry'
    | 'national_mission'
    | 'mixed'
    | 'undecided'
    | null
  innovation_risk: 'pioneering' | 'balanced' | 'mature' | 'undecided' | null
  hard_constraints: HardConstraint[] | null
  draft_hard_constraints: DraftHardConstraint[]
  unresolved_hard_constraints: string[] | null
}

// =====================================================================
// 兴趣探索（活动兴趣题 → 候选研究方向；确定性映射，GLM 不改变结果）
// =====================================================================

/** 研究场景活动选项（O*NET Interest Profiler 思路改写） */
export interface ActivityOption {
  value: string
  label: string
  description: string
}

/** 活动兴趣选择题定义 */
export interface ActivityQuestion {
  version: 'activity-interests-v1'
  prompt: string
  options: ActivityOption[]
  min_selections: number
  max_selections: number
}

/** 候选研究方向（含详细介绍与命中活动） */
export interface DirectionCandidate {
  key: string
  label: string
  description: string
  matched_activities: ActivityOption[]
  match_score: number
}

/** 候选方向建议响应 */
export interface InterestExplorationSuggestions {
  version: 'activity-interests-v1'
  basis: 'deterministic_activity_mapping'
  candidates: DirectionCandidate[]
  hint: string
}

export interface InterviewQuestionOption {
  value: string
  label: string
}

export interface InterviewQuestion {
  question_id: string
  dimension: InterviewDimension
  prompt: string
  answer_type: 'text' | 'single_choice'
  options: InterviewQuestionOption[]
  information_goal: string
}

export interface InterviewState {
  session_id: string
  status: InterviewStatus
  profile: InterviewPortrait
  profile_version: number
  current_question: InterviewQuestion | null
  completed_dimensions: InterviewDimension[]
  missing_dimensions: InterviewDimension[]
  needs_confirmation: boolean
  needs_clarification: boolean
  clarification_questions: string[]
  recommend_ready: boolean
  assistant_message?: string
  assistant_mode?: 'fixed_interview_with_optional_llm_enhancement'
  enhancement_provider?: 'glm' | null
  enhancement_status?: 'available' | 'unavailable' | 'disabled'
}

export interface InterviewEnhancementRetryResult {
  session_id: string
  text: string
  provider: 'glm'
  status: 'available'
}

export type InterviewProfilePatch = Partial<InterviewPortrait>
