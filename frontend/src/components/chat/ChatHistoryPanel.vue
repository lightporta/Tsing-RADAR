<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useChatStore } from '@/stores/useChatStore'
import { displayTime } from '@/utils/format'

const emit = defineEmits<{ (event: 'close'): void }>()

const chatStore = useChatStore()
const advisorStore = useAdvisorStore()
const closeButton = ref<HTMLButtonElement | null>(null)
const historyCard = ref<HTMLElement | null>(null)
const confirmingClear = ref(false)

function restore(id: string) {
  const advisor = chatStore.restoreSession(id, advisorStore.createHistorySnapshot())
  if (!advisor) {
    ElMessage.error('该本机会话已不存在')
    return
  }
  advisorStore.restoreHistorySnapshot(advisor)
  ElMessage.success('已恢复本机会话和匹配结果')
  emit('close')
}

function remove(id: string) {
  chatStore.deleteSavedSession(id)
  nextTick(() => closeButton.value?.focus())
  ElMessage.success('已删除本机会话')
}

function clearAll() {
  chatStore.clearSavedSessions()
  confirmingClear.value = false
  nextTick(() => closeButton.value?.focus())
  ElMessage.success('已清空全部本机会话')
}

function handleDialogKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !historyCard.value) return
  const focusable = Array.from(
    historyCard.value.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'),
  )
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

function handleEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.preventDefault()
  event.stopPropagation()
  emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', handleEscape, true)
  nextTick(() => closeButton.value?.focus())
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleEscape, true)
})
</script>

<template>
  <div
    class="history-layer"
    role="dialog"
    aria-modal="true"
    aria-labelledby="chat-history-title"
    @keydown="handleDialogKeydown"
  >
    <section ref="historyCard" class="history-card">
      <header>
        <div>
          <h2 id="chat-history-title">最近会话</h2>
          <p>最多保存 20 段对话、访谈画像和匹配结果，仅存于当前浏览器。</p>
        </div>
        <button ref="closeButton" type="button" class="icon-button" aria-label="关闭会话历史" @click="emit('close')">
          ×
        </button>
      </header>

      <p v-if="chatStore.historyStorageError" class="storage-error" role="alert">
        {{ chatStore.historyStorageError }}
      </p>

      <div v-if="chatStore.savedSessions.length" class="history-list" role="list">
        <article v-for="session in chatStore.savedSessions" :key="session.id" class="history-item" role="listitem">
          <button
            type="button"
            class="restore-button"
            :aria-label="`恢复会话：${session.title}`"
            @click="restore(session.id)"
          >
            <strong>{{ session.title }}</strong>
            <span>
              <time :datetime="new Date(session.updatedAt).toISOString()">{{ displayTime(session.updatedAt) }}</time>
              · {{ session.messages.length }} 条消息
              · {{ session.advisor.matchedAdvisors.length }} 条匹配
            </span>
          </button>
          <button
            type="button"
            class="delete-button"
            :aria-label="`删除会话：${session.title}`"
            @click="remove(session.id)"
          >
            删除
          </button>
        </article>
      </div>
      <p v-else class="empty-history">还没有保存的会话。发送消息后会自动保存在本机。</p>

      <footer v-if="chatStore.savedSessions.length">
        <template v-if="confirmingClear">
          <span role="alert">确定清空全部本机会话？</span>
          <button type="button" class="footer-button" @click="confirmingClear = false">取消</button>
          <button type="button" class="footer-button danger" @click="clearAll">确认清空</button>
        </template>
        <button v-else type="button" class="footer-button" @click="confirmingClear = true">
          清空全部
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped lang="scss">
.history-layer {
  position: absolute;
  inset: 0;
  z-index: 22;
  display: grid;
  place-items: center;
  padding: $spacing-md;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(3px);
}

.history-card {
  display: flex;
  flex-direction: column;
  width: min(520px, 100%);
  max-height: min(620px, calc(100% - 16px));
  padding: $spacing-lg;
  overflow: hidden;
  border: 1px solid $color-border;
  border-radius: 12px;
  background: $color-bg-card;
  box-shadow: $shadow-card-hover;

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: $spacing-md;
  }

  h2 {
    color: $text-primary;
    font-size: 16px;
  }

  header p,
  .empty-history {
    margin-top: 4px;
    color: $text-secondary;
    font-size: 12px;
    line-height: 1.5;
  }

  footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: $spacing-sm;
    margin-top: $spacing-md;
    color: $color-danger;
    font-size: 12px;
  }
}

.icon-button,
.delete-button,
.footer-button {
  border-radius: 7px;
  color: $text-secondary;

  &:focus-visible {
    outline: 2px solid $color-primary;
    outline-offset: 2px;
  }
}

.icon-button {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  font-size: 22px;
}

.storage-error {
  margin-top: $spacing-sm;
  padding: $spacing-sm;
  border-radius: 6px;
  color: $color-danger;
  background: rgba(245, 108, 108, 0.08);
  font-size: 12px;
}

.history-list {
  display: grid;
  gap: 8px;
  margin-top: $spacing-md;
  overflow-y: auto;
}

.history-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: $spacing-sm;
  padding: 9px 10px;
  border: 1px solid $color-border-light;
  border-radius: 9px;

  &:hover {
    border-color: rgba(64, 158, 255, 0.35);
    background: $color-bg-hover;
  }
}

.restore-button {
  min-width: 0;
  text-align: left;

  strong,
  span {
    display: block;
  }

  strong {
    overflow: hidden;
    color: $text-primary;
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span {
    margin-top: 3px;
    color: $text-placeholder;
    font-size: 11px;
  }

  &:focus-visible {
    outline: 2px solid $color-primary;
    outline-offset: 3px;
  }
}

.delete-button,
.footer-button {
  padding: 6px 9px;
  font-size: 12px;
  background: $color-bg-hover;

  &.danger {
    color: #fff;
    background: $color-danger;
  }
}

.empty-history {
  padding: $spacing-xl 0;
  text-align: center;
}

@media (max-width: $bp-tablet) {
  .history-layer {
    align-items: end;
    padding: 0;
  }

  .history-card {
    width: 100%;
    max-height: 100%;
    border-radius: 12px 12px 0 0;
  }
}
</style>
