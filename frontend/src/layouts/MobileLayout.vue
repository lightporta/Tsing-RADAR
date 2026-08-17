<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppHeader from '@/components/common/AppHeader.vue'
import ChatPanel from '@/components/chat/ChatPanel.vue'
import AdvisorListPanel from '@/components/advisor/AdvisorListPanel.vue'
import MentorDistributionChart from '@/components/charts/MentorDistributionChart.vue'

// =====================================================================
// 移动端布局（文档 §4.1）
// Header 48px（汉堡菜单）+ 上部内容区 + 可拖动的底部对话区（fixed）
// 拖动可自由调整高度；点击拖动条可完全收起或展开
// =====================================================================

const CHAT_HANDLE_HEIGHT = 24
const MOBILE_HEADER_HEIGHT = 48
const INITIAL_CHAT_RATIO = 0.25
const DRAG_THRESHOLD = 6

const router = useRouter()
const route = useRoute()
const drawerVisible = ref(false)
const chatHeight = ref(0)
const maxChatHeight = ref(CHAT_HANDLE_HEIGHT)
const chatDragging = ref(false)

let activePointerId: number | null = null
let activeDragHandle: HTMLElement | null = null
let pointerStartY = 0
let pointerStartHeight = 0
let pointerMoved = false
let suppressClickUntil = 0

const chatExpanded = computed(
  () => chatHeight.value > 0 && Math.abs(chatHeight.value - maxChatHeight.value) <= 1,
)
const chatHeightStyle = computed(() =>
  chatHeight.value > 0 ? { height: `${chatHeight.value}px` } : undefined,
)
const contentPaddingStyle = computed(() =>
  chatHeight.value > 0 ? { paddingBottom: `${chatHeight.value}px` } : undefined,
)
const handleLabel = computed(() =>
  chatExpanded.value
    ? '点击收起对话区；上下拖动可自由调整高度'
    : '点击展开对话区；上下拖动可自由调整高度',
)

function clampChatHeight(height: number) {
  return Math.min(maxChatHeight.value, Math.max(CHAT_HANDLE_HEIGHT, height))
}

function syncChatHeightToViewport() {
  const wasExpanded = chatExpanded.value
  const wasCollapsed = chatHeight.value > 0 && chatHeight.value <= CHAT_HANDLE_HEIGHT + 1
  const viewportHeight = window.innerHeight

  maxChatHeight.value = Math.max(CHAT_HANDLE_HEIGHT, viewportHeight - MOBILE_HEADER_HEIGHT)

  if (chatHeight.value === 0) {
    chatHeight.value = clampChatHeight(Math.round(viewportHeight * INITIAL_CHAT_RATIO))
  } else if (wasExpanded) {
    chatHeight.value = maxChatHeight.value
  } else if (wasCollapsed) {
    chatHeight.value = CHAT_HANDLE_HEIGHT
  } else {
    chatHeight.value = clampChatHeight(chatHeight.value)
  }
}

function toggleChatHeight() {
  chatHeight.value = chatExpanded.value ? CHAT_HANDLE_HEIGHT : maxChatHeight.value
}

function addDragListeners() {
  window.addEventListener('pointermove', moveChatDrag, { passive: false })
  window.addEventListener('pointerup', finishChatDrag)
  window.addEventListener('pointercancel', cancelChatDrag)
}

function removeDragListeners() {
  window.removeEventListener('pointermove', moveChatDrag)
  window.removeEventListener('pointerup', finishChatDrag)
  window.removeEventListener('pointercancel', cancelChatDrag)
}

function startChatDrag(event: PointerEvent) {
  if (activePointerId !== null) return

  const handle = event.currentTarget as HTMLElement
  const chat = handle.closest<HTMLElement>('.mobile-chat')

  activePointerId = event.pointerId
  activeDragHandle = handle
  pointerStartY = event.clientY
  pointerStartHeight = chat?.getBoundingClientRect().height ?? chatHeight.value
  pointerMoved = false
  chatDragging.value = true
  chatHeight.value = clampChatHeight(pointerStartHeight)

  addDragListeners()
  handle.setPointerCapture(event.pointerId)
}

function moveChatDrag(event: PointerEvent) {
  if (event.pointerId !== activePointerId) return

  const delta = pointerStartY - event.clientY
  if (!pointerMoved && Math.abs(delta) < DRAG_THRESHOLD) return

  pointerMoved = true
  event.preventDefault()
  chatHeight.value = clampChatHeight(pointerStartHeight + delta)
}

function finishChatDrag(event: PointerEvent, cancelled = false) {
  if (event.pointerId !== activePointerId) return

  if (activeDragHandle?.hasPointerCapture(event.pointerId)) {
    activeDragHandle.releasePointerCapture(event.pointerId)
  }

  if (!cancelled) {
    suppressClickUntil = performance.now() + 500
    if (!pointerMoved) {
      toggleChatHeight()
    }
  }

  activePointerId = null
  activeDragHandle = null
  pointerMoved = false
  chatDragging.value = false
  removeDragListeners()
}

function cancelChatDrag(event: PointerEvent) {
  finishChatDrag(event, true)
}

function handleChatToggle() {
  if (performance.now() < suppressClickUntil) return
  toggleChatHeight()
}

onMounted(() => {
  syncChatHeightToViewport()
  window.addEventListener('resize', syncChatHeightToViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', syncChatHeightToViewport)
  removeDragListeners()
})

function navigate(path: '/mentors' | '/profile' | '/recruitment' | '/mentor/dashboard') {
  drawerVisible.value = false
  router.push(path)
}
</script>

<template>
  <div class="mobile-layout">
    <AppHeader @menu-click="drawerVisible = true">
      <template #mobile><span /></template>
    </AppHeader>

    <!-- 上部内容区 -->
    <main
      class="mobile-content"
      :class="{ dragging: chatDragging }"
      :style="contentPaddingStyle"
    >
      <section class="content-block advisor-block">
        <AdvisorListPanel :mobile-mode="true" />
      </section>
      <section class="content-block chart-block">
        <h3 class="block-title">📊 已发布导师资源分布</h3>
        <p class="axis-legend">
          按院系统计合并后的导师/导师组；不推断热度、经费或指导风格。
        </p>
        <MentorDistributionChart height="300px" />
      </section>
    </main>

    <!-- 底部对话区（fixed，可拖动并可点击完全收起/展开） -->
    <section
      id="mobile-chat-panel"
      class="mobile-chat"
      :class="{ dragging: chatDragging }"
      :style="chatHeightStyle"
    >
      <button
        type="button"
        class="drag-handle"
        :aria-label="handleLabel"
        aria-controls="mobile-chat-panel"
        :aria-expanded="chatExpanded"
        @click="handleChatToggle"
        @pointerdown="startChatDrag"
      >
        <span class="handle-bar" />
      </button>
      <ChatPanel :mobile-mode="true" />
    </section>

    <!-- 汉堡菜单抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      direction="ltr"
      size="min(80vw, 320px)"
      :with-header="false"
      append-to-body
      body-class="mobile-drawer-body"
      title="主菜单"
    >
      <nav class="drawer-menu" aria-label="移动端业务导航">
        <h3 class="drawer-title">Tsing-RADAR</h3>
        <button
          type="button"
          class="drawer-item"
          :aria-current="route.path === '/mentors' ? 'page' : undefined"
          @click="navigate('/mentors')"
        >
          <el-icon aria-hidden="true">师</el-icon>
          <span>导师数据</span>
        </button>
        <button
          type="button"
          class="drawer-item"
          :aria-current="route.path === '/profile' ? 'page' : undefined"
          @click="navigate('/profile')"
        >
          <el-icon aria-hidden="true">人</el-icon>
          <span>个人信息</span>
        </button>
        <button
          type="button"
          class="drawer-item"
          :aria-current="route.path === '/recruitment' ? 'page' : undefined"
          @click="navigate('/recruitment')"
        >
          <el-icon aria-hidden="true">讯</el-icon>
          <span>信息平台</span>
        </button>
        <button
          type="button"
          class="drawer-item"
          :aria-current="route.path.startsWith('/mentor/') ? 'page' : undefined"
          @click="navigate('/mentor/dashboard')"
        >
          <el-icon aria-hidden="true">门</el-icon>
          <span>导师门户</span>
        </button>
      </nav>
    </el-drawer>
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

  &.dragging {
    transition: none;
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

.axis-legend {
  margin-bottom: $spacing-sm;
  font-size: 11px;
  color: $text-secondary;
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
  overflow: hidden;
  transition: height 0.3s ease;
  z-index: $z-chat-drag;

  &.dragging {
    transition: none;
  }
}

.drag-handle {
  height: 24px;
  width: 100%;
  padding: 0;
  border: 0;
  background: $color-bg-card;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: ns-resize;
  flex-shrink: 0;
  border-bottom: 1px solid $color-border-light;
  touch-action: none;
  user-select: none;

  &:focus-visible {
    outline: none;
  }

  &:focus-visible .handle-bar {
    outline: 2px solid $color-primary;
    outline-offset: 2px;
  }

  .handle-bar {
    width: 36px;
    height: 4px;
    background: $color-border;
    border-radius: 2px;
    pointer-events: none;
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
    &:focus-visible {
      outline: 2px solid $color-primary;
      outline-offset: 2px;
    }
    &[aria-current='page'] {
      color: $color-primary;
      background: rgba(64, 158, 255, 0.1);
    }
    .el-icon {
      font-size: 18px;
      color: $color-primary;
    }
  }
}

:global(.mobile-drawer-body) {
  padding: 0;
}

</style>
