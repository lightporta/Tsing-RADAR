import { post } from './request'

export interface LLMMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface LLMChatRequest {
  messages: LLMMessage[]
  session_id?: string
}

// =====================================================================
// LLM 对话 API
// /api/v1/llm/chat 为 SSE 流式接口，前端通过 fetch + ReadableStream 接收
// 这里提供：1) 普通 POST 封装 2) SSE 流式封装
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
  onDone: (meta: { recommend_ready: boolean; session_id?: string }) => void,
  onError?: (err: unknown) => void,
): AbortController {
  const controller = new AbortController()
  const base = import.meta.env.VITE_API_BASE || ''

  ;(async () => {
    try {
      const resp = await fetch(`${base}/api/v1/llm/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Student-Token': localStorage.getItem('tsing_radar_token') || '',
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`)
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let recommendReady = false
      let sessionId: string | undefined

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // SSE 以 \n\n 分隔事件帧
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          const line = frame.trim()
          if (!line.startsWith('data:')) continue
          const jsonStr = line.slice(5).trim()
          if (!jsonStr) continue
          // [PATCH] 兼容 OpenAI SSE 格式: data: [DONE] 表示流结束
          if (jsonStr === '[DONE]') break
          try {
            const data = JSON.parse(jsonStr)
            // [PATCH] 改为 OpenAI 格式解析: choices[0].delta.content
            if (data.choices?.[0]?.delta?.content) {
              onChunk(data.choices[0].delta.content)
            }
            // 终止帧: finish_reason === "stop"
            if (data.choices?.[0]?.finish_reason === 'stop') {
              recommendReady = !!data.x_soda?.recommend_ready
              sessionId = data.x_soda?.session_id
            }
          } catch {
            // 忽略半截 JSON
          }
        }
      }
      onDone({ recommend_ready: recommendReady, session_id: sessionId })
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
