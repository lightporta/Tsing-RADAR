import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AdvisorHistorySnapshot } from '@/types/advisor'
import type {
  ChatAttachment,
  ChatMessage,
  LocalChatSession,
} from '@/types/chat'
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
  retryInterviewEnhancement as retryInterviewEnhancementApi,
} from '@/api/interview'
import * as mockApi from '@/mock'
import {
  CHAT_HISTORY_STORAGE_KEY,
  readVersionedLocalData,
  removeLocalData,
  writeVersionedLocalData,
} from '@/utils/browserStorage'

// =====================================================================
// 对话 Store（文档 §7.1 useChatStore）
// 对话消息 / 会话状态 / 流式输出
// =====================================================================

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
const MAX_LOCAL_SESSIONS = 20
const LEGACY_ENHANCEMENT_NOTICE = '_提示：GLM 增强回复本轮不可用，结构化访谈仍已正常继续。_'

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isStoredMessage(value: unknown) {
  if (!isRecord(value)) return false
  if (
    typeof value.id !== 'string' ||
    typeof value.content !== 'string' ||
    typeof value.createdAt !== 'number' ||
    !['user', 'assistant', 'system'].includes(String(value.role))
  ) return false
  if (value.attachments === undefined) return true
  return Array.isArray(value.attachments) && value.attachments.every((attachment) =>
    isRecord(attachment) &&
    typeof attachment.documentId === 'string' &&
    typeof attachment.name === 'string' &&
    typeof attachment.size === 'number' &&
    typeof attachment.type === 'string' &&
    ['full_antivirus', 'structural_signature_only'].includes(String(attachment.scanScope)),
  )
}

function isStoredPortrait(value: unknown) {
  if (value === null) return true
  if (!isRecord(value)) return false
  const hardConstraintsValid = value.hard_constraints === null || (
    Array.isArray(value.hard_constraints) && value.hard_constraints.every((constraint) =>
      isRecord(constraint) &&
      typeof constraint.field === 'string' &&
      typeof constraint.operator === 'string' &&
      Array.isArray(constraint.value) &&
      constraint.value.every((item) => typeof item === 'string') &&
      (constraint.source_text === undefined || constraint.source_text === null || typeof constraint.source_text === 'string'),
    )
  )
  const draftConstraintsValid = Array.isArray(value.draft_hard_constraints) &&
    value.draft_hard_constraints.every((draft) =>
      isRecord(draft) &&
      typeof draft.draft_id === 'string' &&
      typeof draft.source_text === 'string' &&
      typeof draft.parsing_confidence === 'number' &&
      typeof draft.confirmation_prompt === 'string' &&
      (draft.proposed_constraint === null || (
        isRecord(draft.proposed_constraint) &&
        typeof draft.proposed_constraint.field === 'string' &&
        typeof draft.proposed_constraint.operator === 'string' &&
        Array.isArray(draft.proposed_constraint.value) &&
        draft.proposed_constraint.value.every((item) => typeof item === 'string')
      )),
    )
  return (
    Array.isArray(value.research_interests) && value.research_interests.every((item) => typeof item === 'string') &&
    (value.interest_statement === null || typeof value.interest_statement === 'string') &&
    (value.research_mode === null || ['theory', 'engineering', 'mixed', 'undecided'].includes(String(value.research_mode))) &&
    (value.mentorship_style === null || ['high_guidance', 'balanced', 'autonomous', 'undecided'].includes(String(value.mentorship_style))) &&
    (value.career_orientation === null || ['academic', 'industry', 'national_mission', 'mixed', 'undecided'].includes(String(value.career_orientation))) &&
    (value.innovation_risk === null || ['pioneering', 'balanced', 'mature', 'undecided'].includes(String(value.innovation_risk))) &&
    hardConstraintsValid &&
    draftConstraintsValid &&
    (value.unresolved_hard_constraints === null || (
      Array.isArray(value.unresolved_hard_constraints) &&
      value.unresolved_hard_constraints.every((item) => typeof item === 'string')
    ))
  )
}

function isStoredQuestion(value: unknown) {
  if (value === null) return true
  return (
    isRecord(value) &&
    typeof value.question_id === 'string' &&
    typeof value.dimension === 'string' &&
    typeof value.prompt === 'string' &&
    ['text', 'single_choice'].includes(String(value.answer_type)) &&
    Array.isArray(value.options) &&
    value.options.every((option) =>
      isRecord(option) && typeof option.value === 'string' && typeof option.label === 'string',
    ) &&
    typeof value.information_goal === 'string'
  )
}

function isStoredEvidenceClaim(value: unknown) {
  return isRecord(value) &&
    typeof value.statement === 'string' &&
    Array.isArray(value.citations) &&
    value.citations.every((citation) =>
      isRecord(citation) &&
      typeof citation.evidence_id === 'string' &&
      typeof citation.citation_type === 'string' &&
      typeof citation.citation === 'string' &&
      typeof citation.captured_at === 'string' &&
      typeof citation.confidence === 'number' &&
      (citation.source_url === undefined || citation.source_url === null || typeof citation.source_url === 'string'),
    )
}

function isStoredAdvisor(value: unknown) {
  if (!isRecord(value)) return false
  const projectsValid = Array.isArray(value.projects) && value.projects.every((project) =>
    isRecord(project) &&
    typeof project.title === 'string' &&
    typeof project.desc === 'string' &&
    typeof project.fund === 'string',
  )
  const recruitmentsValid = Array.isArray(value.recruitments) && value.recruitments.every((recruitment) =>
    isRecord(recruitment) &&
    typeof recruitment.type === 'string' &&
    typeof recruitment.title === 'string' &&
    typeof recruitment.req === 'string' &&
    typeof recruitment.major === 'string' &&
    typeof recruitment.deadline === 'string',
  )
  const explanationValid = value.explanation === undefined || (
    isRecord(value.explanation) &&
    Array.isArray(value.explanation.supporting_evidence) &&
    value.explanation.supporting_evidence.every(isStoredEvidenceClaim) &&
    Array.isArray(value.explanation.counter_evidence) &&
    value.explanation.counter_evidence.every(isStoredEvidenceClaim) &&
    Array.isArray(value.explanation.uncertainties) &&
    value.explanation.uncertainties.every((item) => typeof item === 'string') &&
    Array.isArray(value.explanation.questions_to_verify) &&
    value.explanation.questions_to_verify.every((item) => typeof item === 'string')
  )
  return (
    typeof value.advisor_id === 'string' &&
    typeof value.name === 'string' &&
    typeof value.dept === 'string' &&
    typeof value.field === 'string' &&
    typeof value.score === 'number' && Number.isFinite(value.score) &&
    typeof value.synergy === 'number' && Number.isFinite(value.synergy) &&
    typeof value.reason === 'string' &&
    Array.isArray(value.tags) && value.tags.every((tag) => typeof tag === 'string') &&
    projectsValid && recruitmentsValid && explanationValid
  )
}

function isStoredAdvisorSnapshot(value: unknown) {
  if (!isRecord(value) || !Array.isArray(value.matchedAdvisors)) return false
  return (
    value.matchedAdvisors.every(isStoredAdvisor) &&
    (value.selectedName === null || typeof value.selectedName === 'string') &&
    ['score', 'fit_score', 'evidence_coverage', 'evidence_confidence'].includes(String(value.sortMetric)) &&
    ['idle', 'matched', 'no_published_data', 'no_match', 'error'].includes(String(value.resultStatus)) &&
    typeof value.resultMessage === 'string' &&
    isRecord(value.resultMeta) &&
    Array.isArray(value.comparisonIds) && value.comparisonIds.every((item) => typeof item === 'string')
  )
}

function isLocalChatHistory(value: unknown): value is LocalChatSession[] {
  if (!Array.isArray(value)) return false
  return value.every((session) => {
    if (!session || typeof session !== 'object') return false
    const candidate = session as Partial<LocalChatSession>
    return (
      typeof candidate.id === 'string' &&
      typeof candidate.title === 'string' &&
      typeof candidate.createdAt === 'number' &&
      typeof candidate.updatedAt === 'number' &&
      (candidate.sessionId === undefined || typeof candidate.sessionId === 'string') &&
      Array.isArray(candidate.messages) &&
      candidate.messages.every(isStoredMessage) &&
      ['in_progress', 'awaiting_confirmation', 'confirmed'].includes(String(candidate.interviewStatus)) &&
      isStoredPortrait(candidate.profile) &&
      (candidate.profileVersion === null || typeof candidate.profileVersion === 'number') &&
      isStoredQuestion(candidate.currentQuestion) &&
      typeof candidate.needsConfirmation === 'boolean' &&
      typeof candidate.recommendReady === 'boolean' &&
      ['unknown', 'available', 'unavailable', 'disabled'].includes(String(candidate.enhancementStatus)) &&
      (candidate.enhancementProvider === null || typeof candidate.enhancementProvider === 'string') &&
      isStoredAdvisorSnapshot(candidate.advisor)
    )
  })
}

function cloneLocalSession<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function historyTitle(messages: ChatMessage[]) {
  const firstUserMessage = messages.find((message) => message.role === 'user')?.content.trim()
  if (!firstUserMessage) return '未命名对话'
  const characters = Array.from(firstUserMessage.replace(/\s+/g, ' '))
  return `${characters.slice(0, 28).join('')}${characters.length > 28 ? '…' : ''}`
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | undefined>(undefined)
  const interviewStatus = ref<InterviewStatus>('in_progress')
  const profile = ref<InterviewPortrait | null>(null)
  const profileVersion = ref<number | null>(null)
  const currentQuestion = ref<InterviewQuestion | null>(null)
  const needsConfirmation = ref(false)
  const streaming = ref(false)
  const chatError = ref('')
  const enhancementStatus = ref<'unknown' | 'available' | 'unavailable' | 'disabled'>('unknown')
  const enhancementProvider = ref<string | null>(null)
  const enhancementRetrying = ref(false)
  const enhancementRetryError = ref('')
  const enhancementTargetMessageId = ref<string | null>(null)
  const lastFailedRequest = ref<{
    content: string
    attachments: ChatAttachment[]
  } | null>(null)
  const savedSessions = ref<LocalChatSession[]>(
    readVersionedLocalData(CHAT_HISTORY_STORAGE_KEY, isLocalChatHistory) || [],
  )
  const activeHistoryId = ref<string | undefined>(undefined)
  const historyStorageError = ref('')
  const historyRestoreToken = ref(0)
  /** 当前流式请求的 AbortController */
  let controller: AbortController | null = null

  /** 是否可以触发推荐（问卷已收集足够信息） */
  const recommendReady = ref(false)

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
            '不必一次说完整，可以先从你的专业、正在关注的问题，或未来想去的方向开始。',
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
    enhancementStatus.value = state.enhancement_status || 'disabled'
    enhancementProvider.value = state.enhancement_provider || null
    if (enhancementStatus.value !== 'unavailable') {
      enhancementRetryError.value = ''
      enhancementTargetMessageId.value = null
    }
  }

  /**
   * 发送消息并接收流式回复
   * @param content 用户输入
   * @param attachments 已私有保存的附件元数据；文件内容不注入访谈。
   */
  async function send(
    content: string,
    attachments: ChatAttachment[] = [],
    retrying = false,
  ) {
    if (!content.trim() || streaming.value || enhancementRetrying.value) return
    if (!sessionId.value) sessionId.value = crypto.randomUUID()
    chatError.value = ''
    lastFailedRequest.value = null
    enhancementRetryError.value = ''
    enhancementTargetMessageId.value = null
    enhancementStatus.value = 'unknown'
    enhancementProvider.value = null

    // 1) 推入用户消息
    if (!retrying) pushMessage({ role: 'user', content, attachments })

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
        if (state.enhancement_status === 'unavailable') {
          enhancementTargetMessageId.value = assistantMsg.id
        }
        assistantMsg.streaming = false
        streaming.value = false
      },
      () => {
        const index = messages.value.findIndex((message) => message.id === assistantMsg.id)
        if (index >= 0) messages.value.splice(index, 1)
        chatError.value = '消息未送达，访谈状态没有被本地伪造。请重试本条消息。'
        lastFailedRequest.value = { content, attachments: [...attachments] }
        streaming.value = false
      },
    )
  }

  async function retryLastSend() {
    const failed = lastFailedRequest.value
    if (!failed || streaming.value) return
    await send(failed.content, [...failed.attachments], true)
  }

  /** 只重试最后一个已完成访谈轮次的 GLM 措辞增强，不重发答案或推进访谈。 */
  async function retryEnhancement() {
    if (
      enhancementRetrying.value ||
      streaming.value ||
      enhancementStatus.value !== 'unavailable' ||
      !sessionId.value
    ) return

    enhancementRetrying.value = true
    enhancementRetryError.value = ''
    const retrySessionId = sessionId.value
    const targetMessageId = enhancementTargetMessageId.value
    try {
      const result = await retryInterviewEnhancementApi(retrySessionId)
      if (sessionId.value !== retrySessionId) return
      const target =
        messages.value.find((message) => message.id === targetMessageId) ||
        [...messages.value].reverse().find((message) => message.role === 'assistant' && !message.streaming)
      if (!target) {
        enhancementRetryError.value = '未找到需要增强的固定回复，访谈状态未改变。'
        return
      }

      const fixedReply = target.content
        .replace(`\n\n${LEGACY_ENHANCEMENT_NOTICE}`, '')
        .replace(LEGACY_ENHANCEMENT_NOTICE, '')
        .trimEnd()
      target.content = `${fixedReply}\n\n**GLM 表达补充**\n\n${result.text.trim()}`
      enhancementStatus.value = 'available'
      enhancementProvider.value = 'glm'
      enhancementTargetMessageId.value = null
      enhancementRetryError.value = ''
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      enhancementRetryError.value =
        isRecord(detail) && typeof detail.message === 'string'
          ? detail.message
          : 'GLM 暂不可用，访谈状态未改变，请稍后重试。'
      enhancementStatus.value = 'unavailable'
    } finally {
      enhancementRetrying.value = false
    }
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

  function persistSessionList() {
    const result = writeVersionedLocalData(CHAT_HISTORY_STORAGE_KEY, savedSessions.value)
    historyStorageError.value = result.ok
      ? ''
      : result.reason === 'quota'
        ? '本机会话存储空间不足。请删除较早的会话后重试。'
        : '浏览器禁止了本机存储，会话暂时只能保留在当前页面。'
    return result
  }

  /**
   * 保存当前完整会话及匹配快照。该操作只写入 localStorage，不发送网络请求。
   */
  function saveCurrentSession(advisor: AdvisorHistorySnapshot) {
    if (streaming.value) return false
    const hasConversation = messages.value.some((message) => message.role === 'user')
    if (!hasConversation && !profile.value && advisor.matchedAdvisors.length === 0) return false

    const now = Date.now()
    const id = activeHistoryId.value || genId('conversation')
    const existing = savedSessions.value.find((session) => session.id === id)
    const snapshot: LocalChatSession = cloneLocalSession({
      id,
      title: historyTitle(messages.value),
      createdAt: existing?.createdAt || messages.value[0]?.createdAt || now,
      updatedAt: now,
      sessionId: sessionId.value,
      messages: messages.value.map((message) => ({ ...message, streaming: false })),
      interviewStatus: interviewStatus.value,
      profile: profile.value,
      profileVersion: profileVersion.value,
      currentQuestion: currentQuestion.value,
      needsConfirmation: needsConfirmation.value,
      recommendReady: recommendReady.value,
      enhancementStatus: enhancementStatus.value,
      enhancementProvider: enhancementProvider.value,
      advisor,
    })

    activeHistoryId.value = id
    savedSessions.value = [
      snapshot,
      ...savedSessions.value.filter((session) => session.id !== id),
    ]
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .slice(0, MAX_LOCAL_SESSIONS)
    return persistSessionList().ok
  }

  /** 恢复本机快照，并返回应同步恢复的导师匹配结果。 */
  function restoreSession(
    id: string,
    currentAdvisor?: AdvisorHistorySnapshot,
  ): AdvisorHistorySnapshot | null {
    const saved = savedSessions.value.find((session) => session.id === id)
    if (!saved) return null
    if (activeHistoryId.value !== id && currentAdvisor) saveCurrentSession(currentAdvisor)

    abort()
    const restored = cloneLocalSession(saved)
    activeHistoryId.value = restored.id
    sessionId.value = restored.sessionId
    messages.value = restored.messages
    interviewStatus.value = restored.interviewStatus
    profile.value = restored.profile
    profileVersion.value = restored.profileVersion
    currentQuestion.value = restored.currentQuestion
    needsConfirmation.value = restored.needsConfirmation
    recommendReady.value = restored.recommendReady
    enhancementStatus.value = restored.enhancementStatus
    enhancementProvider.value = restored.enhancementProvider
    enhancementRetrying.value = false
    enhancementRetryError.value = ''
    enhancementTargetMessageId.value = null
    chatError.value = ''
    lastFailedRequest.value = null
    historyRestoreToken.value += 1
    return restored.advisor
  }

  function deleteSavedSession(id: string) {
    savedSessions.value = savedSessions.value.filter((session) => session.id !== id)
    if (activeHistoryId.value === id) activeHistoryId.value = undefined
    persistSessionList()
  }

  function clearSavedSessions() {
    savedSessions.value = []
    activeHistoryId.value = undefined
    historyStorageError.value = ''
    removeLocalData(CHAT_HISTORY_STORAGE_KEY)
  }

  /** 新对话（清空上下文，保留欢迎语） */
  function newConversation(advisor?: AdvisorHistorySnapshot) {
    if (advisor) saveCurrentSession(advisor)
    abort()
    activeHistoryId.value = undefined
    sessionId.value = undefined
    interviewStatus.value = 'in_progress'
    profile.value = null
    profileVersion.value = null
    currentQuestion.value = null
    needsConfirmation.value = false
    recommendReady.value = false
    chatError.value = ''
    lastFailedRequest.value = null
    enhancementStatus.value = 'unknown'
    enhancementProvider.value = null
    enhancementRetrying.value = false
    enhancementRetryError.value = ''
    enhancementTargetMessageId.value = null
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
    chatError,
    enhancementStatus,
    enhancementProvider,
    enhancementRetrying,
    enhancementRetryError,
    lastFailedRequest,
    savedSessions,
    activeHistoryId,
    historyStorageError,
    historyRestoreToken,
    recommendReady,
    messageCount,
    userTurns,
    initWelcome,
    pushMessage,
    appendToLast,
    updateInterviewProfile,
    confirmInterviewProfile,
    send,
    retryLastSend,
    retryEnhancement,
    abort,
    saveCurrentSession,
    restoreSession,
    deleteSavedSession,
    clearSavedSessions,
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
