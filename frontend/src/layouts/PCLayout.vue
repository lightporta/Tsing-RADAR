<script setup lang="ts">
import { ref } from 'vue'
import AppHeader from '@/components/common/AppHeader.vue'
import ChatPanel from '@/components/chat/ChatPanel.vue'
import AdvisorListPanel from '@/components/advisor/AdvisorListPanel.vue'
import ChartPanel from '@/components/charts/ChartPanel.vue'

// =====================================================================
// PC 端三栏布局（文档 §3.1）
// 25% 对话栏 | 45% 卡片列表 | 30% 可视化看板
// Header 60px + 主体三栏，每栏独立滚动，1px 分割线
// 对话栏支持收起（宽度过渡 0px ↔ 25%）
// =====================================================================

const chatCollapsed = ref(false)

function toggleChat() {
  chatCollapsed.value = !chatCollapsed.value
}
</script>

<template>
  <div class="pc-layout">
    <AppHeader />

    <main class="pc-main">
      <!-- 左栏：对话分析区（可收起） -->
      <section class="panel-col chat-col" :class="{ collapsed: chatCollapsed }">
        <ChatPanel :collapsed="chatCollapsed" @toggle="toggleChat" />
      </section>

      <!-- 收起后的悬浮展开按钮 -->
      <button
        v-if="chatCollapsed"
        class="float-expand"
        aria-label="展开对话栏"
        @click="toggleChat"
      >
        <el-icon aria-hidden="true">»</el-icon>
      </button>

      <!-- 中栏：导师卡片列表 -->
      <section class="panel-col advisor-col">
        <AdvisorListPanel />
      </section>

      <!-- 右栏：可视化看板 -->
      <section class="panel-col chart-col">
        <ChartPanel />
      </section>
    </main>
  </div>
</template>

<style scoped lang="scss">
.pc-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: $color-bg;
  overflow: hidden;
}

.pc-main {
  display: flex;
  flex: 1;
  min-height: 0;
  // 三栏比例 25 : 45 : 30
  .chat-col {
    flex: 25;
    border-right: 1px solid $color-border;
    transition: flex 0.3s ease, min-width 0.3s ease, opacity 0.3s ease;
    min-width: 0;
    overflow: hidden;

    &.collapsed {
      flex: 0;
      min-width: 0;
      opacity: 0;
      border-right: none;
    }
  }
  .advisor-col {
    flex: 45;
    border-right: 1px solid $color-border;
    min-width: 0;
  }
  .chart-col {
    flex: 30;
    min-width: 0;
  }
}

// 收起后悬浮展开按钮
.float-expand {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 22px;
  height: 64px;
  background: $color-bg-card;
  border: 1px solid $color-border;
  border-left: none;
  border-radius: 0 8px 8px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: $color-primary;
  z-index: $z-chat-drag;
  box-shadow: $shadow-card;
  transition: $transition-fast;

  &:hover {
    background: $color-bg-hover;
    width: 26px;
  }
}

</style>
