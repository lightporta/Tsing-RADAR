import { post } from './request'
import type { InterviewState } from '@/types/interview'

export interface LLMMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface LLMChatRequest {
  messages: LLMMessage[]
  session_id?: string
}

export type InterviewStreamMeta = InterviewState

// =====================================================================
// LLM 对话 API
// Web 使用同一访谈应用服务的 JSON 表面；后端仍保留 SSE 表面供合同测试与兼容客户端使用。
// =====================================================================

/**
 * SSE 流式对话
 * @param payload 消息体
 * @param onChunk 每收到一个 delta 文本片段回调
 * @param onDone 流结束时回调（含 recommend_ready 与 session_id）
 * @returns AbortController（可调用 .abort() 中断）
 */
export function streamChat(
  payload: LLMChatRequest,
  onChunk: (delta: string) => void,
  onDone: (meta: InterviewStreamMeta) => void,
  onError?: (err: unknown) => void,
): AbortController {
  const controller = new AbortController()
  ;(async () => {
    try {
      type StateWithReply = InterviewState & { assistant_message?: string }
      const state = await post<StateWithReply>(
        '/api/v1/llm/chat?stream=false',
        payload,
        { signal: controller.signal },
      )
      if (state.assistant_message) onChunk(state.assistant_message)
      onDone(state)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        onError?.(err)
      }
    }
  })()

  return controller
}

/** 文本向量化（用于画像上传简历后调用） */
export async function embedText(text: string): Promise<number[]> {
  const res = await post<{ data: number[] }>('/api/v1/llm/embeddings', { text })
  return res.data
}
