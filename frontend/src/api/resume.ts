import { post } from './request'
import type { ResumeSubmitRequest } from '@/types/api'

// =====================================================================
// 简历 API
// =====================================================================

export interface ResumeGenerateRequest {
  student_name: string
  dept: string
  email: string
  phone: string
  projects: Array<{ name?: string; detail?: string } | string>
  awards: string[]
  positions: string[]
  target_advisor?: string
}

export interface ResumeGenerateResponse {
  polished_text: string
  title: string
}

/** 调用 LLM 生成 / 打磨简历正文 */
export function generateResume(req: ResumeGenerateRequest) {
  return post<ResumeGenerateResponse>('/api/resume/generate', req)
}

/** 投递简历至招募方 */
export function submitResume(req: ResumeSubmitRequest) {
  return post<{ app_id: string; status: string }>('/api/resume/submit', req)
}
