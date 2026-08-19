<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Menu } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/useUserStore'
import { fetchWebTestMode, type WebTestModeStatus } from '@/api/request'
import AppLogo from './AppLogo.vue'

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
const avatarUrl = computed(() => userStore.profile.avatarUrl?.trim() || '')
const avatarInitial = computed(() => {
  const name = userStore.profile.name.trim()
  return name ? Array.from(name)[0].toUpperCase() : '我'
})

// —— 网页免认证测试模式标注（模块级缓存，避免多个 Header 实例重复请求）——
const testMode = ref<WebTestModeStatus | null>(null)
let testModeLoaded = false

onMounted(async () => {
  if (testModeLoaded) return
  testModeLoaded = true
  try {
    testMode.value = await fetchWebTestMode()
  } catch {
    // 状态端点不可用时不阻塞页面，仅不显示标注
  }
})

const testModeText = computed(() => {
  if (!testMode.value || !testMode.value.enabled) return ''
  return testMode.value.active ? testMode.value.label : '网页测试模式已到期'
})

function goProfile() {
  router.push('/profile')
}
function goMentors() {
  router.push('/mentors')
}
function goRecruitment() {
  router.push('/recruitment')
}
function goMentorPortal() {
  router.push('/mentor/dashboard')
}
function goBack() {
  // 保留首页会话状态
  router.push('/')
}

function handleProfileClick() {
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
        <el-icon aria-hidden="true"><ArrowLeft /></el-icon>
        <span class="back-text">返回</span>
      </button>
      <button
        v-else-if="$slots.mobile"
        class="icon-btn"
        aria-label="打开菜单"
        @click="emit('menu-click')"
      >
        <el-icon aria-hidden="true"><Menu /></el-icon>
      </button>
      <AppLogo v-else />
    </div>

    <!-- 中部标题（二级页） -->
    <h1 v-if="title" class="header-title">{{ title }}</h1>

    <!-- 右侧：清晰的文字入口 + 当前用户头像 -->
    <div class="header-right">
      <span
        v-if="testModeText"
        class="test-mode-badge"
        :class="{ expired: testMode && !testMode.active }"
      >{{ testModeText }}</span>
      <slot name="right" />
      <button class="nav-btn mentors" aria-label="导师数据" @click="goMentors">
        导师数据
      </button>
      <button class="nav-btn profile" aria-label="个人信息" @click="handleProfileClick">
        个人信息
      </button>
      <button class="nav-btn recruitment" aria-label="招募信息" @click="goRecruitment">
        招募信息
      </button>
      <button class="nav-btn mentor" aria-label="导师门户" @click="goMentorPortal">
        导师门户
      </button>
      <button class="user-avatar" aria-label="进入个人信息" @click="handleProfileClick">
        <img v-if="avatarUrl" :src="avatarUrl" alt="当前用户头像" />
        <span v-else>{{ avatarInitial }}</span>
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

.test-mode-badge {
  flex-shrink: 0;
  padding: 2px 8px;
  font-size: 12px;
  line-height: 18px;
  border-radius: 4px;
  color: #b45309;
  background: rgba(230, 162, 60, 0.12);
  border: 1px solid rgba(230, 162, 60, 0.45);
  white-space: nowrap;

  &.expired {
    color: #b91c1c;
    background: rgba(245, 108, 108, 0.1);
    border-color: rgba(245, 108, 108, 0.45);
  }
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

.nav-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  padding: 0 12px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 500;
  transition: $transition-fast;

  &.mentors {
    color: #1769aa;
    background: #eaf4ff;
  }

  &.profile {
    color: #287a4d;
    background: #edf8f1;
  }

  &.recruitment {
    color: #9a5b13;
    background: #fff5e6;
  }

  &.mentor {
    color: #6a3d9a;
    background: #f3edfb;
  }

  &:hover {
    filter: brightness(0.97);
    box-shadow: 0 2px 8px rgba(32, 70, 120, 0.12);
  }

  &:active {
    transform: scale(0.97);
  }
}

.user-avatar {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  overflow: hidden;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: $color-accent;
  font-size: 14px;
  font-weight: 600;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
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
  .app-header {
    padding: 0 $spacing-md;
  }
  .header-right {
    gap: 4px;
  }
  .nav-btn {
    display: none;
  }
  .user-avatar {
    width: 32px;
    height: 32px;
  }
}
</style>
