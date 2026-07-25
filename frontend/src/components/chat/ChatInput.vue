<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/useChatStore'
import { useUserStore } from '@/stores/useUserStore'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { formatBytes } from '@/utils/format'

// =====================================================================
// 底部输入区（文档 §3.3）
// 多行文本输入框（高度自适应，最大 120px）
// 右侧发送按钮（纸飞机）+ 左侧附件上传（PDF/Word 简历）
// Enter 发送，Shift+Enter 换行
// =====================================================================

const chatStore = useChatStore()
const userStore = useUserStore()
const advisorStore = useAdvisorStore()

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>()
const attachments = ref<Array<{ name: string; size: number; text: string }>>([])

// 自适应高度
function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(120, el.scrollHeight) + 'px'
}

function send() {
  const content = text.value.trim()
  if (!content) {
    ElMessage.warning('请输入内容')
    return
  }
  if (chatStore.streaming) return

  const attachTexts = attachments.value.map((a) => a.text)
  chatStore.send(content, attachTexts)
  text.value = ''
  attachments.value = []
  nextTick(autoResize)

  // 触发导师匹配（关键词触发）
  advisorStore.match(content, undefined, userStore.profile.weights)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// 附件上传（PDF/Word 简历，简单读取文件名与大小，文本提取交后端）
function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files) return
  Array.from(input.files).forEach((file) => {
    if (!/\.(pdf|docx?|txt)$/i.test(file.name)) {
      ElMessage.warning(`${file.name} 格式不支持，仅支持 PDF / Word / TXT`)
      return
    }
    // 简单读取 txt 内容；PDF/DOCX 实际由后端 /api/v1/llm/embeddings 提取
    if (file.size > 5 * 1024 * 1024) {
      ElMessage.warning(`${file.name} 超过 5MB`)
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      attachments.value.push({
        name: file.name,
        size: file.size,
        text: typeof reader.result === 'string' ? reader.result : file.name,
      })
    }
    reader.readAsText(file.slice(0, 1024 * 100)) // 仅读取前 100KB 作示意
  })
  input.value = ''
}

function removeAttachment(idx: number) {
  attachments.value.splice(idx, 1)
}

// 快捷引导问题
function useQuickQuestion(prompt: string) {
  text.value = prompt
  nextTick(() => {
    autoResize()
    send()
  })
}

function stopStream() {
  chatStore.abort()
}
</script>

<template>
  <div class="chat-input-area">
    <!-- 引导问题快捷按钮（仅在消息少时显示） -->
    <div v-if="chatStore.messageCount <= 2" class="quick-questions">
      <button
        v-for="q in chatStore.quickQuestions"
        :key="q.label"
        class="quick-btn"
        @click="useQuickQuestion(q.prompt)"
      >
        {{ q.label }}
      </button>
    </div>

    <!-- 已上传附件预览 -->
    <div v-if="attachments.length" class="attachments">
      <div v-for="(a, i) in attachments" :key="i" class="attachment-chip">
        <el-icon><Document /></el-icon>
        <span class="att-name" :title="a.name">{{ a.name }}</span>
        <span class="att-size">{{ formatBytes(a.size) }}</span>
        <button class="att-remove" aria-label="移除附件" @click="removeAttachment(i)">✕</button>
      </div>
    </div>

    <div class="input-row">
      <label class="input-btn" aria-label="上传简历">
        <el-icon><Paperclip /></el-icon>
        <input type="file" multiple accept=".pdf,.doc,.docx,.txt" hidden @change="onFileChange" />
      </label>

      <textarea
        ref="textareaRef"
        v-model="text"
        class="chat-textarea"
        rows="1"
        placeholder="输入你的研究兴趣或问题，Enter 发送，Shift+Enter 换行…"
        @input="autoResize"
        @keydown="onKeydown"
      />

      <button
        v-if="chatStore.streaming"
        class="send-btn stop"
        aria-label="停止生成"
        @click="stopStream"
      >
        <el-icon><VideoPause /></el-icon>
      </button>
      <button v-else class="send-btn" aria-label="发送" :disabled="!text.trim()" @click="send">
        <el-icon><Promotion /></el-icon>
      </button>
    </div>

    <!-- 推荐就绪提示 -->
    <transition name="fade">
      <div v-if="chatStore.recommendReady" class="recommend-banner">
        <span>✅ 画像收集完成，已为你匹配右侧推荐导师</span>
      </div>
    </transition>
  </div>
</template>

<style scoped lang="scss">
.chat-input-area {
  padding: $spacing-md $spacing-lg;
  background: $color-bg-card;
  border-top: 1px solid $color-border-light;
  flex-shrink: 0;
}

.quick-questions {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
  margin-bottom: $spacing-md;
}
.quick-btn {
  padding: 5px 12px;
  font-size: 12px;
  border: 1px solid $color-border;
  border-radius: 16px;
  color: $color-primary;
  background: $color-bg-card;
  transition: $transition-fast;

  &:hover {
    background: $color-bg-hover;
    border-color: $color-primary;
  }
}

.attachments {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
  margin-bottom: $spacing-sm;
}
.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(64, 158, 255, 0.08);
  border-radius: 6px;
  font-size: 12px;
  color: $color-primary-dark;
  .att-name {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .att-size {
    color: $text-placeholder;
    font-size: 11px;
  }
  .att-remove {
    color: $text-placeholder;
    &:hover {
      color: $color-danger;
    }
  }
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: $spacing-sm;
  background: $color-bg;
  border-radius: 10px;
  padding: 6px 8px;
  border: 1px solid $color-border;
  transition: border-color 0.2s;

  &:focus-within {
    border-color: $color-primary;
  }
}

.input-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  color: $text-secondary;
  cursor: pointer;
  transition: $transition-fast;
  flex-shrink: 0;

  &:hover {
    color: $color-primary;
    background: $color-bg-hover;
  }
}

.chat-textarea {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 14px;
  line-height: 1.5;
  max-height: 120px;
  min-height: 24px;
  padding: 4px 0;
  color: $text-primary;

  &::placeholder {
    color: $text-placeholder;
  }
}

.send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: $color-primary;
  color: #fff;
  font-size: 16px;
  flex-shrink: 0;
  transition: $transition-fast;

  &:hover:not(:disabled) {
    background: $color-primary-light;
  }
  &:active:not(:disabled) {
    transform: scale(0.95);
  }
  &:disabled {
    background: $color-border;
    cursor: not-allowed;
  }
  &.stop {
    background: $color-danger;
  }
}

.recommend-banner {
  margin-top: $spacing-sm;
  padding: 6px 12px;
  background: rgba(103, 194, 58, 0.1);
  color: $color-success;
  border-radius: 6px;
  font-size: 12px;
  text-align: center;
}
</style>
