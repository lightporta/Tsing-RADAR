<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElDrawer as Drawer } from 'element-plus'
import AppHeader from '@/components/common/AppHeader.vue'
import ChatPanel from '@/components/chat/ChatPanel.vue'
import AdvisorListPanel from '@/components/advisor/AdvisorListPanel.vue'
import ScatterChart from '@/components/charts/ScatterChart.vue'

// =====================================================================
// 移动端布局（文档 §4.1）
// Header 48px（汉堡菜单）+ 上部内容区 75%（卡片 + 散点）+ 底部对话区 25%（fixed）
// 对话区支持上滑展开全屏
// =====================================================================

const router = useRouter()
const drawerVisible = ref(false)
const chatExpanded = ref(false)

function goProfile() {
  drawerVisible.value = false
  router.push('/profile')
}
function goRecruitment() {
  drawerVisible.value = false
  router.push('/recruitment')
}
</script>

<template>
  <div class="mobile-layout">
    <AppHeader @menu-click="drawerVisible = true">
      <template #mobile><span /></template>
    </AppHeader>

    <!-- 上部内容区 75% -->
    <main class="mobile-content" :class="{ shrunk: chatExpanded }">
      <section class="content-block advisor-block">
        <AdvisorListPanel :mobile-mode="true" />
      </section>
      <section class="content-block chart-block">
        <h3 class="block-title">📊 四象限散点图</h3>
        <ScatterChart height="240px" />
      </section>
    </main>

    <!-- 底部对话区 25%（fixed，可上滑全屏） -->
    <section class="mobile-chat" :class="{ expanded: chatExpanded }">
      <div class="drag-handle" @click="chatExpanded = !chatExpanded">
        <span class="handle-bar" />
      </div>
      <ChatPanel :mobile-mode="true" :hide-toolbar="true" />
    </section>

    <!-- 汉堡菜单抽屉 -->
    <Drawer v-model="drawerVisible" direction="ltr" size="70%" :with-header="false">
      <div class="drawer-menu">
        <h3 class="drawer-title">Tsing-RADAR</h3>
        <button class="drawer-item" @click="goProfile">
          <el-icon><User /></el-icon>
          <span>个人信息</span>
        </button>
        <button class="drawer-item" @click="goRecruitment">
          <el-icon><ChatDotRound /></el-icon>
          <span>信息平台</span>
        </button>
      </div>
    </Drawer>
  </div>
</template>

<style scoped lang="scss">
.mobile-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: $color-bg;
  overflow: hidden;
}

.mobile-content {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 25vh; // 给底部对话区留位
  transition: padding-bottom 0.3s ease;

  &.shrunk {
    padding-bottom: 0;
  }
}

.content-block {
  padding: $spacing-lg;
  background: $color-bg-card;
  margin-bottom: $spacing-sm;
}
.block-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: $spacing-md;
  color: $text-primary;
}

// 底部对话区
.mobile-chat {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 25vh;
  background: $color-bg-card;
  border-top: 1px solid $color-border;
  box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  transition: height 0.3s ease;
  z-index: $z-chat-drag;

  &.expanded {
    height: calc(100vh - var(--header-height-mobile));
  }
}

.drag-handle {
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  border-bottom: 1px solid $color-border-light;

  .handle-bar {
    width: 36px;
    height: 4px;
    background: $color-border;
    border-radius: 2px;
  }
}

// 抽屉
.drawer-menu {
  padding: $spacing-xl $spacing-lg;

  .drawer-title {
    font-size: 18px;
    font-weight: 700;
    color: $color-primary;
    margin-bottom: $spacing-xl;
  }
  .drawer-item {
    display: flex;
    align-items: center;
    gap: $spacing-md;
    width: 100%;
    padding: $spacing-lg;
    border-radius: $card-radius;
    color: $text-primary;
    font-size: 15px;
    transition: $transition-fast;

    &:hover {
      background: $color-bg-hover;
    }
    .el-icon {
      font-size: 18px;
      color: $color-primary;
    }
  }
}

@media (min-width: $bp-tablet) {
  .mobile-layout {
    display: none;
  }
}
</style>
