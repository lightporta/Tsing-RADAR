import { post } from './request'
import type { ResumeSubmitRequest } from '@/types/api'
import type { PrivateDocument } from './actions'

// =====================================================================
// 简历 API
// =====================================================================

export interface ResumeGenerateRequest {
  student_name: string
  dept: string
  email: string
  phone: string
  education: string
  research_interests: string[]
  projects: Array<{ name: string; detail: string }>
  awards: string[]
  positions: string[]
  target_advisor?: string
  format: 'pdf' | 'docx'
  confirm_generation: true
}

/** 只按用户确认字段确定性排版，不调用外部模型补写经历。 */
export function generateResume(req: ResumeGenerateRequest, idempotencyKey: string) {
  return post<PrivateDocument>('/api/resume/generate', req, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

/** 仅创建站内行动记录，不联系或投递给第三方。 */
export function submitResume(req: ResumeSubmitRequest, idempotencyKey: string) {
  return post<{ app_id: string; status: string }>('/api/resume/submit', req, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}
