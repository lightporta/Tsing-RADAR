<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores/useChatStore'
import { useAdvisorStore } from '@/stores/useAdvisorStore'

// =====================================================================
// 对话栏顶部工具栏（文档 §3.3）
// 左侧：收起按钮（双左箭头 <<）
// 右侧：新对话+ 按钮
// =====================================================================

defineProps<{ collapsed?: boolean }>()
const emit = defineEmits<{ (e: 'toggle'): void }>()

const chatStore = useChatStore()
const advisorStore = useAdvisorStore()
const confirmVisible = ref(false)

function requestNewConversation() {
  if (chatStore.messageCount > 1) {
    confirmVisible.value = true
    return
  }
  startNewConversation()
}

function startNewConversation() {
  confirmVisible.value = false
  chatStore.newConversation()
  advisorStore.resetResults()
}
</script>

<template>
  <div class="chat-toolbar">
    <button class="tool-btn" :class="{ collapsed }" aria-label="收起对话栏" @click="emit('toggle')">
      <el-icon aria-hidden="true">«</el-icon>
      <span class="btn-text">收起</span>
    </button>
    <button class="tool-btn primary" aria-label="开启新对话" @click="requestNewConversation">
      <el-icon aria-hidden="true">＋</el-icon>
      <span class="btn-text">新对话</span>
    </button>

    <div v-if="confirmVisible" class="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="new-chat-title">
      <div class="confirm-card">
        <strong id="new-chat-title">开启新对话？</strong>
        <p>当前访谈内容和匹配结果会被清空。</p>
        <div class="confirm-actions">
          <button class="confirm-btn" @click="confirmVisible = false">继续当前对话</button>
          <button class="confirm-btn danger" @click="startNewConversation">清空并新建</button>
        </div>
      </div>
    </div>
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
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: $card-radius;
  font-size: 13px;
  color: $text-regular;
  transition: $transition-fast;

  &:hover {
    background: $color-bg-hover;
    color: $color-primary;
  }
  &:active {
    transform: scale(0.95);
  }
  &.primary {
    color: $color-primary;
    font-weight: 500;
  }
  &.collapsed {
    .el-icon {
      transform: rotate(180deg);
    }
  }
}
</style>
