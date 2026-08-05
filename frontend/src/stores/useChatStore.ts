import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatAttachment, ChatMessage, QuickQuestion } from '@/types/chat'
import type {
  InterviewProfilePatch,
  InterviewQuestion,
  InterviewPortrait,
  InterviewState,
  InterviewStatus,
} from '@/types/interview'
import { genId } from '@/utils/format'
import { streamChat } from '@/api/chat'
import {
  confirmInterviewProfile as confirmInterviewProfileApi,
  editInterviewProfile,
} from '@/api/interview'
import * as mockApi from '@/mock'

// =====================================================================
// 对话 Store（文档 §7.1 useChatStore）
// 对话消息 / 会话状态 / 流式输出
// =====================================================================

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | undefined>(undefined)
  const interviewStatus = ref<InterviewStatus>('in_progress')
  const profile = ref<InterviewPortrait | null>(null)
  const profileVersion = ref<number | null>(null)
  const currentQuestion = ref<InterviewQuestion | null>(null)
  const needsConfirmation = ref(false)
  const streaming = ref(false)
  /** 当前流式请求的 AbortController */
  let controller: AbortController | null = null

  /** 是否可以触发推荐（问卷已收集足够信息） */
  const recommendReady = ref(false)

  /** 引导问题快捷按钮 */
  const quickQuestions = ref<QuickQuestion[]>([
    { label: '我对 NLP 感兴趣', prompt: '我对自然语言处理和对话系统很感兴趣' },
    { label: '想做计算机视觉', prompt: '我想做计算机视觉方向的研究' },
    { label: '倾向机器人控制', prompt: '我对机器人和强化学习感兴趣' },
    { label: '想读博发论文', prompt: '我希望读博并发表顶会论文，看重学术指导' },
  ])

  const messageCount = computed(() => messages.value.length)
  const userTurns = computed(() => messages.value.filter((m) => m.role === 'user').length)

  /** 初始化欢迎语 */
  function initWelcome() {
    if (messages.value.length === 0) {
      messages.value = [
        {
          id: genId('msg'),
          role: 'assistant',
          content:
            '👋 你好！我是 **Tsing-RADAR 清研寻师雷达**，你的学术合伙人匹配助手。\n\n' +
            '告诉我你的**专业背景、研究兴趣、职业规划**，我会通过多轮对话为你精准匹配合适的导师。\n\n' +
            '你可以直接输入关键词（如「自然语言处理」「机器人」），或点击下方引导问题开始 👇',
          createdAt: Date.now(),
        },
      ]
    }
  }

  /** 添加一条消息 */
  function pushMessage(msg: Omit<ChatMessage, 'id' | 'createdAt'>): ChatMessage {
    const full: ChatMessage = { ...msg, id: genId('msg'), createdAt: Date.now() }
    messages.value.push(full)
    return messages.value[messages.value.length - 1]
  }

  /** 更新最后一条 assistant 消息内容（流式追加） */
  function appendToLast(delta: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.content += delta
    }
  }

  function applyInterviewState(state: InterviewState) {
    sessionId.value = state.session_id
    interviewStatus.value = state.status
    profile.value = state.profile
    profileVersion.value = state.profile_version
    currentQuestion.value = state.current_question
    needsConfirmation.value = state.needs_confirmation
    recommendReady.value = state.recommend_ready
  }

  /**
   * 发送消息并接收流式回复
   * @param content 用户输入
   * @param attachments 已私有保存的附件元数据；文件内容不注入访谈。
   */
  async function send(content: string, attachments: ChatAttachment[] = []) {
    if (!content.trim() || streaming.value) return
    if (!sessionId.value) sessionId.value = crypto.randomUUID()

    // 1) 推入用户消息
    pushMessage({ role: 'user', content, attachments })

    // 2) 推入空的 assistant 消息占位（流式填充）
    const assistantMsg = pushMessage({ role: 'assistant', content: '', streaming: true })

    streaming.value = true

    // 3) 构造后端 messages（剥离 streaming 标记，仅传 role/content）
    const payloadMessages = messages.value
      .filter((m) => m.id !== assistantMsg.id)
      .map((m) => ({ role: m.role, content: m.content }))

    // Mock 模式：本地模拟流式
    if (USE_MOCK) {
      const reply = mockApi.mockChatReply(content, userTurns.value)
      await mockStream(reply, (delta) => {
        assistantMsg.content += delta
      })
      assistantMsg.content = assistantMsg.content.trim()
      assistantMsg.content +=
        '\n\n_持久化访谈与画像确认在 Mock 模式下不可用，请连接后端进行 A3 流程。_'
      recommendReady.value = false
      needsConfirmation.value = false
      assistantMsg.streaming = false
      streaming.value = false
      return
    }

    // 真实 SSE 流式
    controller = streamChat(
      { messages: payloadMessages, session_id: sessionId.value },
      (delta) => {
        assistantMsg.content += delta
      },
      (state) => {
        applyInterviewState(state)
        assistantMsg.streaming = false
        streaming.value = false
      },
      () => {
        assistantMsg.content += '\n\n_⚠️ 对话服务暂时不可用，已切换本地兜底模式_'
        assistantMsg.streaming = false
        streaming.value = false
      },
    )
  }

  async function updateInterviewProfile(patch: InterviewProfilePatch) {
    if (!sessionId.value || profileVersion.value === null) {
      throw new Error('请先开始访谈')
    }
    const state = await editInterviewProfile(
      sessionId.value,
      profileVersion.value,
      patch,
    )
    applyInterviewState(state)
  }

  async function confirmInterviewProfile() {
    if (!sessionId.value || profileVersion.value === null) {
      throw new Error('请先开始访谈')
    }
    const state = await confirmInterviewProfileApi(
      sessionId.value,
      profileVersion.value,
    )
    applyInterviewState(state)
  }

  /** 中断当前流式 */
  function abort() {
    controller?.abort()
    streaming.value = false
    const last = messages.value[messages.value.length - 1]
    if (last?.streaming) last.streaming = false
  }

  /** 新对话（清空上下文，保留欢迎语） */
  function newConversation() {
    abort()
    sessionId.value = undefined
    interviewStatus.value = 'in_progress'
    profile.value = null
    profileVersion.value = null
    currentQuestion.value = null
    needsConfirmation.value = false
    recommendReady.value = false
    messages.value = []
    initWelcome()
  }

  return {
    messages,
    sessionId,
    interviewStatus,
    profile,
    profileVersion,
    currentQuestion,
    needsConfirmation,
    streaming,
    recommendReady,
    quickQuestions,
    messageCount,
    userTurns,
    initWelcome,
    pushMessage,
    appendToLast,
    updateInterviewProfile,
    confirmInterviewProfile,
    send,
    abort,
    newConversation,
  }
})

/** Mock 流式输出：模拟逐字显示 */
async function mockStream(text: string, onDelta: (delta: string) => void) {
  const chunks = text.match(/.{1,4}/g) || [text]
  for (const chunk of chunks) {
    onDelta(chunk)
    await new Promise((r) => setTimeout(r, 20))
  }
}
