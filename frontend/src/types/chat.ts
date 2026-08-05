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
  name: string
  size: number
  type: string
  /** 提取出的文本（后端 OCR/embedding 后回填） */
  extractedText?: string
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

/** 引导问题快捷按钮 */
export interface QuickQuestion {
  label: string
  prompt: string
}
