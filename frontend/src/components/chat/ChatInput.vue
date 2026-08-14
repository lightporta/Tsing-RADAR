<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/useChatStore'
import { formatBytes } from '@/utils/format'
import { uploadDocument } from '@/api/actions'
import type { ChatAttachment } from '@/types/chat'

// =====================================================================
// 底部输入区（文档 §3.3）
// 多行文本输入框（高度自适应，最大 120px）
// 右侧发送按钮（纸飞机）+ 左侧附件上传（PDF/Word 简历）
// Enter 发送，Shift+Enter 换行
// =====================================================================

const chatStore = useChatStore()

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>()
const attachments = ref<ChatAttachment[]>([])
const uploading = ref(false)
const MAX_PRIVATE_FILE_BYTES = 8 * 1024 * 1024

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

  chatStore.send(content, [...attachments.value])
  text.value = ''
  attachments.value = []
  nextTick(autoResize)

}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// 附件立即进入当前主体的私有对象存储；不会把正文注入访谈。
async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files) return
  const selected = Array.from(input.files)
  input.value = ''
  uploading.value = true
  try {
    for (const file of selected) {
      if (!/\.(pdf|docx)$/i.test(file.name)) {
        ElMessage.warning(`${file.name} 格式不支持，仅支持 PDF / DOCX`)
        continue
      }
      if (file.size > MAX_PRIVATE_FILE_BYTES) {
        ElMessage.warning(`${file.name} 超过 8 MB，请压缩后重新上传`)
        continue
      }
      try {
        const stored = await uploadDocument(file)
        attachments.value.push({
          documentId: stored.document_id,
          name: stored.original_name,
          size: stored.size_bytes,
          type: stored.media_type,
          scanScope: stored.scan_scope,
        })
        ElMessage.success(`${stored.original_name} 已私有保存；内容未自动加入访谈`)
      } catch {
        // 统一错误文案由 API 拦截器给出；失败关闭，不保留附件占位。
      }
    }
  } finally {
    uploading.value = false
  }
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

function retry() {
  chatStore.retryLastSend()
}
</script>

<template>
  <div class="chat-input-area">
    <div class="assistant-mode">
      <span class="mode-dot" :class="chatStore.enhancementStatus" />
      结构化访谈 · GLM 措辞增强
    </div>

    <div v-if="chatStore.chatError" class="chat-error" role="alert">
      <span>{{ chatStore.chatError }}</span>
      <button type="button" :disabled="chatStore.streaming" @click="retry">重试</button>
    </div>

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
        <el-icon aria-hidden="true">📄</el-icon>
        <span class="att-name" :title="a.name">{{ a.name }}</span>
        <span class="att-size">{{ formatBytes(a.size) }}</span>
        <button
          class="att-remove"
          aria-label="从本条消息移除附件关联，不删除私有文件"
          @click="removeAttachment(i)"
        >
          ✕
        </button>
      </div>
    </div>

    <div class="input-row">
      <label class="input-btn" :class="{ disabled: uploading }" aria-label="私有上传 PDF 或 DOCX">
        <el-icon aria-hidden="true">📎</el-icon>
        <input
          type="file"
          multiple
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          hidden
          :disabled="uploading"
          @change="onFileChange"
        />
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
        <el-icon aria-hidden="true">⏸</el-icon>
      </button>
      <button
        v-else
        class="send-btn"
        aria-label="发送"
        :disabled="!text.trim() || uploading"
        @click="send"
      >
        <el-icon aria-hidden="true">➤</el-icon>
      </button>
    </div>

    <!-- 推荐就绪提示 -->
    <transition name="fade">
      <div v-if="chatStore.needsConfirmation" class="recommend-banner waiting">
        <span>画像信息已收集，请检查并确认后再进入匹配。</span>
      </div>
      <div v-else-if="chatStore.recommendReady" class="recommend-banner">
        <span>✅ 画像已确认，匹配前置条件已满足。</span>
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

.assistant-mode {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 6px;
  color: $text-placeholder;
  font-size: 10px;
}

.mode-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: $color-border;

  &.available { background: $color-success; }
  &.unavailable { background: $color-warning; }
}

.chat-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
  margin-bottom: $spacing-sm;
  padding: 8px 10px;
  border-radius: 8px;
  color: $color-danger;
  background: rgba(245, 108, 108, 0.08);
  font-size: 11px;

  button {
    flex-shrink: 0;
    color: $color-primary;
    font-weight: 600;
  }
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
  &.disabled {
    opacity: 0.55;
    cursor: wait;
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
.recommend-banner.waiting {
  background: rgba(230, 162, 60, 0.1);
  color: $color-warning;
}
</style>
