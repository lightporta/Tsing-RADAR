<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import ChatToolbar from './ChatToolbar.vue'
import ChatMessage from './ChatMessage.vue'
import ChatInput from './ChatInput.vue'
import { useChatStore } from '@/stores/useChatStore'

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
const messagesRef = ref<HTMLElement | null>(null)

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
</script>

<template>
  <div class="chat-panel" :class="{ mobile: mobileMode }">
    <ChatToolbar v-if="!hideToolbar" :collapsed="collapsed" @toggle="emit('toggle')" />

    <!-- 消息区 -->
    <div ref="messagesRef" class="messages-area">
      <ChatMessage
        v-for="msg in chatStore.messages"
        :key="msg.id"
        :message="msg"
      />
    </div>

    <!-- 底部输入区 -->
    <ChatInput />
  </div>
</template>

<style scoped lang="scss">
.chat-panel {
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
