<script setup lang="ts">
import AppHeader from '@/components/common/AppHeader.vue'

// =====================================================================
// 二级页面布局（文档 §5.2）
// - 顶部 Header：左上角「← 返回」按钮 + 页面标题
// - 内容区全屏独立滚动
// - 支持浏览器前进/后退
// =====================================================================

defineProps<{ title: string }>()
</script>

<template>
  <div class="subpage-layout">
    <AppHeader :show-back="true" :title="title" />
    <main class="subpage-content">
      <slot />
    </main>
  </div>
</template>

<style scoped lang="scss">
.subpage-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: $color-bg;
  overflow: hidden;
}

.subpage-content {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
</style>
