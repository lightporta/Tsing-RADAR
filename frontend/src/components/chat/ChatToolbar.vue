<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
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

async function newConversation() {
  if (chatStore.messageCount > 1) {
    try {
      await ElMessageBox.confirm('确定要开启新对话吗？当前会话将被清空。', '新对话', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
  }
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
    <button class="tool-btn primary" aria-label="开启新对话" @click="newConversation">
      <el-icon aria-hidden="true">＋</el-icon>
      <span class="btn-text">新对话</span>
    </button>
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
