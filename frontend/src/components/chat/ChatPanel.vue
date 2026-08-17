<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import ChatToolbar from './ChatToolbar.vue'
import ChatMessage from './ChatMessage.vue'
import InterviewProfileCard from './InterviewProfileCard.vue'
import QuestionOptions from './QuestionOptions.vue'
import ChatInput from './ChatInput.vue'
import { useChatStore } from '@/stores/useChatStore'
import { useAdvisorStore } from '@/stores/useAdvisorStore'

// =====================================================================
// 对话分析区容器（文档 §3.3）
// PC：顶部工具栏 + 消息区（流式）+ 底部输入区
// 移动端：可隐藏工具栏，仅消息 + 输入
// =====================================================================

withDefaults(defineProps<{ collapsed?: boolean; mobileMode?: boolean; hideToolbar?: boolean }>(), {
  collapsed: false,
  mobileMode: false,
  hideToolbar: false,
})

const emit = defineEmits<{ (e: 'toggle'): void }>()

const chatStore = useChatStore()
const advisorStore = useAdvisorStore()
const messagesRef = ref<HTMLElement | null>(null)
const matchedProfile = ref<string | null>(null)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let handledRestoreToken = 0

// 自动滚动到底部（消息变化 / 流式追加）
watch(
  () => chatStore.messages.map((m) => m.content).join(''),
  () => {
    nextTick(() => {
      if (messagesRef.value) {
        messagesRef.value.scrollTop = messagesRef.value.scrollHeight
      }
    })
  },
)

watch(
  () => [
    chatStore.recommendReady,
    chatStore.sessionId,
    chatStore.profileVersion,
    chatStore.historyRestoreToken,
  ] as const,
  async ([ready, sessionId, profileVersion, restoreToken]) => {
    const matchKey = `${sessionId}:${profileVersion}`
    if (restoreToken !== handledRestoreToken) {
      handledRestoreToken = restoreToken
      matchedProfile.value = matchKey
      return
    }
    if (!ready || !sessionId || matchedProfile.value === matchKey) return
    matchedProfile.value = matchKey
    try {
      await advisorStore.match(
        chatStore.profile?.interest_statement || '',
        sessionId,
      )
    } catch {
      // 失败状态与可操作说明由 advisor store 展示。
      matchedProfile.value = null
    }
  },
)

// 在状态稳定后写入本机历史；流式片段期间只重置定时器，避免长对话频繁序列化。
watch(
  () => ({
    messages: chatStore.messages,
    streaming: chatStore.streaming,
    profile: chatStore.profile,
    profileVersion: chatStore.profileVersion,
    status: chatStore.interviewStatus,
    question: chatStore.currentQuestion,
    recommendReady: chatStore.recommendReady,
    advisors: advisorStore.matchedAdvisors,
    selectedName: advisorStore.selectedName,
    resultStatus: advisorStore.resultStatus,
    resultMeta: advisorStore.resultMeta,
    comparisonIds: advisorStore.comparisonIds,
  }),
  () => {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => {
      if (!chatStore.streaming) {
        chatStore.saveCurrentSession(advisorStore.createHistorySnapshot())
      }
    }, 400)
  },
  { deep: true },
)

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  if (!chatStore.streaming) chatStore.saveCurrentSession(advisorStore.createHistorySnapshot())
})
</script>

<template>
  <div class="chat-panel" :class="{ mobile: mobileMode }">
    <ChatToolbar
      v-if="!hideToolbar"
      :collapsed="collapsed"
      :mobile-mode="mobileMode"
      @toggle="emit('toggle')"
    />

    <!-- 消息区 -->
    <div
      ref="messagesRef"
      class="messages-area"
      role="log"
      aria-label="访谈消息"
      aria-live="polite"
      aria-relevant="additions text"
    >
      <ChatMessage
        v-for="msg in chatStore.messages"
        :key="msg.id"
        :message="msg"
      />
    </div>

    <InterviewProfileCard />

    <!-- 交互式问题选项（single_choice 时显示） -->
    <QuestionOptions v-if="!chatStore.needsConfirmation" />

    <!-- 底部输入区 -->
    <ChatInput />
  </div>
</template>

<style scoped lang="scss">
.chat-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  background: $color-bg-card;
  overflow: hidden;

  &.mobile {
    background: transparent;
  }
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: $spacing-lg $spacing-xl;
  -webkit-overflow-scrolling: touch;

  &::-webkit-scrollbar {
    width: 4px;
  }
}

@media (max-width: $bp-tablet) {
  .messages-area {
    padding: $spacing-md;
  }
}
</style>
