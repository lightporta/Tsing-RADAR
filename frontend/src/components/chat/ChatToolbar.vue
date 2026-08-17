<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useChatStore } from '@/stores/useChatStore'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import ChatHistoryPanel from './ChatHistoryPanel.vue'

withDefaults(defineProps<{ collapsed?: boolean; mobileMode?: boolean }>(), {
  collapsed: false,
  mobileMode: false,
})
const emit = defineEmits<{ (event: 'toggle'): void }>()

const chatStore = useChatStore()
const advisorStore = useAdvisorStore()
const confirmVisible = ref(false)
const historyVisible = ref(false)
const cancelNewButton = ref<HTMLButtonElement | null>(null)
const newConversationButton = ref<HTMLButtonElement | null>(null)
const historyButton = ref<HTMLButtonElement | null>(null)
const confirmCard = ref<HTMLElement | null>(null)

function requestNewConversation() {
  if (chatStore.messageCount > 1) {
    confirmVisible.value = true
    return
  }
  startNewConversation()
}

function startNewConversation() {
  confirmVisible.value = false
  chatStore.newConversation(advisorStore.createHistorySnapshot())
  advisorStore.resetResults()
}

async function closeHistory() {
  historyVisible.value = false
  await nextTick()
  historyButton.value?.focus()
}

function handleConfirmKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    confirmVisible.value = false
    return
  }
  if (event.key !== 'Tab' || !confirmCard.value) return
  const focusable = Array.from(confirmCard.value.querySelectorAll<HTMLButtonElement>('button:not([disabled])'))
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

watch(confirmVisible, async (visible, wasVisible) => {
  await nextTick()
  if (visible) cancelNewButton.value?.focus()
  else if (wasVisible) newConversationButton.value?.focus()
})
</script>

<template>
  <div class="chat-toolbar">
    <button
      v-if="!mobileMode"
      class="tool-btn"
      :class="{ collapsed }"
      :aria-label="collapsed ? '展开对话栏' : '收起对话栏'"
      :aria-expanded="!collapsed"
      @click="emit('toggle')"
    >
      <el-icon aria-hidden="true">«</el-icon>
      <span class="btn-text">{{ collapsed ? '展开' : '收起' }}</span>
    </button>
    <div class="toolbar-actions">
      <button
        ref="historyButton"
        class="tool-btn"
        aria-label="查看本机会话历史"
        aria-haspopup="dialog"
        @click="historyVisible = true"
      >
        <el-icon aria-hidden="true">◷</el-icon>
        <span class="btn-text">历史</span>
      </button>
      <button ref="newConversationButton" class="tool-btn primary" aria-label="开启新对话" @click="requestNewConversation">
        <el-icon aria-hidden="true">＋</el-icon>
        <span class="btn-text">新对话</span>
      </button>
    </div>

    <div
      v-if="confirmVisible"
      class="confirm-layer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="new-chat-title"
      @keydown="handleConfirmKeydown"
    >
      <div ref="confirmCard" class="confirm-card">
        <strong id="new-chat-title">开启新对话？</strong>
        <p>当前访谈和匹配结果会先保存到本机历史，再开启空白会话。</p>
        <div class="confirm-actions">
          <button ref="cancelNewButton" class="confirm-btn" @click="confirmVisible = false">继续当前对话</button>
          <button class="confirm-btn danger" @click="startNewConversation">保存并新建</button>
        </div>
      </div>
    </div>

    <ChatHistoryPanel v-if="historyVisible" @close="closeHistory" />
  </div>
</template>

<style scoped lang="scss">
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: $panel-toolbar-height;
  padding: 0 $spacing-lg;
  background: $color-bg;
  border-bottom: 1px solid $color-border-light;
  flex-shrink: 0;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

.confirm-layer {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  padding: $spacing-lg;
  background: rgba(255, 255, 255, 0.76);
  backdrop-filter: blur(3px);
}

.confirm-card {
  width: min(320px, calc(100% - 24px));
  padding: $spacing-lg;
  border: 1px solid $color-border;
  border-radius: 12px;
  background: $color-bg-card;
  box-shadow: $shadow-card-hover;

  strong {
    color: $text-primary;
    font-size: 15px;
  }

  p {
    margin: $spacing-sm 0 $spacing-lg;
    color: $text-secondary;
    font-size: 13px;
    line-height: 1.5;
  }
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: $spacing-sm;
}

.confirm-btn {
  padding: 7px 10px;
  border-radius: 7px;
  color: $text-regular;
  font-size: 12px;
  background: $color-bg-hover;

  &.danger {
    color: #fff;
    background: $color-danger;
  }

  &:focus-visible {
    outline: 2px solid $color-primary;
    outline-offset: 2px;
  }
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: $card-radius;
  color: $text-regular;
  font-size: 13px;
  transition: $transition-fast;

  &:hover {
    color: $color-primary;
    background: $color-bg-hover;
  }

  &:active {
    transform: scale(0.95);
  }

  &:focus-visible {
    outline: 2px solid $color-primary;
    outline-offset: 2px;
  }

  &.primary {
    color: $color-primary;
    font-weight: 500;
  }

  &.collapsed .el-icon {
    transform: rotate(180deg);
  }
}

@media (max-width: $bp-tablet) {
  .chat-toolbar {
    height: 40px;
    padding: 0 $spacing-sm;
  }
}
</style>
