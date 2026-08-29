import type { AdvisorHistorySnapshot } from './advisor'
import type {
  InterviewPortrait,
  InterviewQuestion,
  InterviewStatus,
} from './interview'

// =====================================================================
// 对话（Chat）相关类型定义
// =====================================================================

/** 消息角色 */
export type MessageRole = 'user' | 'assistant' | 'system'

/** 单条对话消息 */
export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  /** 是否正在流式接收中 */
  streaming?: boolean
  /** 创建时间戳 */
  createdAt: number
  /** 关联的附件（PDF/Word 简历） */
  attachments?: ChatAttachment[]
}

/** 对话附件 */
export interface ChatAttachment {
  documentId: string
  name: string
  size: number
  type: string
  scanScope: 'full_antivirus' | 'structural_signature_only'
}

/** SSE 流式响应的单帧 */
export interface SSEChunk {
  delta?: string
  role?: string
  finish?: boolean
  /** 是否触发推荐（问卷收集足够） */
  recommend_ready?: boolean
  session_id?: string
}

/** 最近会话的完整本机快照；不会由保存动作上传服务器。 */
export interface LocalChatSession {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  sessionId?: string
  messages: ChatMessage[]
  interviewStatus: InterviewStatus
  profile: InterviewPortrait | null
  profileVersion: number | null
  currentQuestion: InterviewQuestion | null
  needsConfirmation: boolean
  recommendReady: boolean
  enhancementStatus: 'unknown' | 'available' | 'unavailable' | 'disabled'
  enhancementProvider: string | null
  advisor: AdvisorHistorySnapshot
}
