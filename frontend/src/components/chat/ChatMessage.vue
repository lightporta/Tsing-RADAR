<script setup lang="ts">
import { computed } from 'vue'
import { Paperclip } from '@element-plus/icons-vue'
import type { ChatMessage } from '@/types/chat'
import { renderMarkdown } from '@/utils/markdown'
import { useUserStore } from '@/stores/useUserStore'

// =====================================================================
// 单条对话消息（文档 §3.3）
// AI 消息靠左（浅灰背景），用户消息靠右（蓝色背景白字）
// 支持 Markdown 渲染 + 代码高亮
// =====================================================================

const props = defineProps<{ message: ChatMessage }>()
const userStore = useUserStore()

const isUser = computed(() => props.message.role === 'user')
const userAvatarUrl = computed(() => userStore.profile.avatarUrl?.trim() || '')
const userInitial = computed(() => {
  const name = userStore.profile.name.trim()
  return name ? Array.from(name)[0].toUpperCase() : '我'
})
const html = computed(() =>
  isUser.value ? props.message.content : renderMarkdown(props.message.content),
)
</script>

<template>
  <div class="chat-message" :class="{ user: isUser, assistant: !isUser }">
    <div v-if="!isUser" class="avatar ai-avatar" aria-hidden="true">
      <svg viewBox="0 0 32 32" width="28" height="28">
        <circle cx="16" cy="16" r="16" fill="#409EFF" />
        <polygon points="16,8 24,12 24,20 16,24 8,20 8,12" fill="none" stroke="#fff" stroke-width="1.5" />
        <circle cx="16" cy="16" r="2.5" fill="#FF9500" />
      </svg>
    </div>

    <div class="bubble-wrap">
      <div class="bubble" :class="{ streaming: message.streaming }">
        <div v-if="isUser" class="user-text">{{ message.content }}</div>
        <div v-else class="markdown-body" v-html="html" />
        <div v-if="isUser && message.attachments?.length" class="message-attachments">
          <span v-for="item in message.attachments" :key="item.documentId">
            <el-icon aria-hidden="true"><Paperclip /></el-icon>
            {{ item.name }}（已私有保存，未注入访谈）
          </span>
        </div>
        <span v-if="message.streaming" class="cursor" />
      </div>
    </div>

    <div v-if="isUser" class="avatar user-avatar" aria-hidden="true">
      <img v-if="userAvatarUrl" :src="userAvatarUrl" alt="" />
      <span v-else>{{ userInitial }}</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.chat-message {
  display: flex;
  gap: $spacing-sm;
  margin-bottom: $spacing-lg;

  &.user {
    justify-content: flex-end;
    .bubble {
      background: $color-primary;
      color: #fff;
      border-radius: 14px 14px 4px 14px;
    }
    .bubble-wrap {
      align-items: flex-end;
    }
  }
  &.assistant {
    .bubble {
      background: $color-bg-card;
      color: $text-primary;
      border: 1px solid $color-border-light;
      border-radius: 14px 14px 14px 4px;
    }
  }
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}
.ai-avatar {
  width: 28px;
  height: 28px;
}
.user-avatar {
  background: $color-accent;
  color: #fff;
  overflow: hidden;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  max-width: 80%;
}

.bubble {
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  position: relative;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);

  &.streaming {
    border-color: $color-primary-light;
  }

  .user-text {
    white-space: pre-wrap;
  }
}

.message-attachments {
  display: grid;
  gap: 3px;
  margin-top: 8px;
  font-size: 11px;
  opacity: 0.9;
}

// 流式光标
.cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  background: $color-primary;
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: blink 1s steps(2) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}

:deep(.markdown-body) {
  p:last-child {
    margin-bottom: 0;
  }
  // 用户气泡内的 code 颜色修正
  .user & code {
    background: rgba(255, 255, 255, 0.2);
    color: #fff;
  }
}
</style>
