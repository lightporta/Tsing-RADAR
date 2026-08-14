// =====================================================================
// 用户（学生）相关类型定义
// =====================================================================

import type { TraitKey } from './advisor'

/** 学生类别 */
export type StudentCategory =
  | '本科大一'
  | '本科大二'
  | '本科大三'
  | '本科大四'
  | '硕士研一'
  | '硕士研二'
  | '博士博一'
  | '博士博二'
  | '博士博三'

/** 学生信息（对应后端 students 表） */
export interface StudentProfile {
  name: string
  /** 当前浏览器会话内使用的头像图片（Data URL） */
  avatarUrl?: string
  email: string
  dept: string // 院系
  category: StudentCategory // 类别
  grade: string // 年级，如 2023级
  phone?: string
  gpa?: string
  research_experience?: string
  research_interest?: string
  interest_tags: string[] // 研究兴趣标签
  /** 六维需求权重（学生可调整短板） */
  weights: Record<TraitKey, number>
}

/** 简历条目类型 */
export interface ResumeEntry {
  id: string
  type: 'project' | 'award' | 'position'
  title: string
  detail: string
}

/** 简历（对应后端 resumes 表） */
export interface Resume {
  resume_id: string
  title: string
  content: ResumeEntry[]
  polished_text: string
  target_advisor?: string
  created_at: number
}
