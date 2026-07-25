<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppLogo from './AppLogo.vue'
import { useUserStore } from '@/stores/useUserStore'

// =====================================================================
// 全局 Header（文档 §3.2 / §4.4）
// - 左侧：Logo
// - 右侧：学生信息（人形图标）+ 信息平台（消息图标）
// - 取消全局退出/重置按钮（重置移入对话栏内部）
// - 移动端：左侧汉堡菜单收纳入口
// =====================================================================

withDefaults(defineProps<{ showBack?: boolean; title?: string }>(), {
  showBack: false,
  title: '',
})

const emit = defineEmits<{ (e: 'menu-click'): void }>()

const router = useRouter()
const userStore = useUserStore()

function goProfile() {
  router.push('/profile')
}
function goRecruitment() {
  router.push('/recruitment')
}
function goBack() {
  // 保留首页会话状态
  router.push('/')
}

function handleProfileClick() {
  // 占位：清小搭 SSO 校验
  if (!userStore.isLoggedIn) {
    userStore.login('同学', '2023000000')
    ElMessage.success('已登录（SSO 占位）')
  }
  goProfile()
}
</script>

<template>
  <header class="app-header" :class="{ 'is-mobile-bar': $slots.mobile }">
    <!-- 左侧：返回按钮（二级页）或 汉堡菜单（移动端）或 Logo -->
    <div class="header-left">
      <button
        v-if="showBack"
        class="icon-btn back-btn"
        aria-label="返回首页"
        @click="goBack"
      >
        <el-icon><ArrowLeft /></el-icon>
        <span class="back-text">返回</span>
      </button>
      <button
        v-else-if="$slots.mobile"
        class="icon-btn"
        aria-label="打开菜单"
        @click="emit('menu-click')"
      >
        <el-icon><Menu /></el-icon>
      </button>
      <AppLogo v-else />
    </div>

    <!-- 中部标题（二级页） -->
    <h1 v-if="title" class="header-title">{{ title }}</h1>

    <!-- 右侧：学生信息 + 信息平台 -->
    <div class="header-right">
      <slot name="right" />
      <button class="icon-btn" aria-label="个人信息" @click="handleProfileClick">
        <el-icon><User /></el-icon>
      </button>
      <button class="icon-btn" aria-label="信息平台" @click="goRecruitment">
        <el-icon><ChatDotRound /></el-icon>
      </button>
    </div>
  </header>
</template>

<style scoped lang="scss">
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--header-height);
  padding: 0 $spacing-xl;
  background: $color-bg-card;
  border-bottom: 1px solid $color-border;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: $z-header;

  &.is-mobile-bar {
    height: var(--header-height-mobile);
    padding: 0 $spacing-lg;
  }
}

.header-left {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  min-width: 0;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: $text-primary;
  margin: 0 auto;
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.header-right {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  color: $text-regular;
  font-size: 18px;
  transition: $transition-fast;

  &:hover {
    background: $color-bg-hover;
    color: $color-primary;
  }
  &:active {
    transform: scale(0.95);
  }
}

.back-btn {
  width: auto;
  padding: 0 12px;
  gap: 4px;
  .back-text {
    font-size: 14px;
  }
}

@media (max-width: $bp-tablet) {
  .header-title {
    position: static;
    transform: none;
    font-size: 15px;
  }
  .back-text {
    display: none;
  }
  .back-btn {
    width: 36px;
    padding: 0;
  }
}
</style>
