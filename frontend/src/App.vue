<script setup lang="ts">
import { RouterView } from 'vue-router'
import { useUserStore } from '@/stores/useUserStore'

// 启动时从 localStorage 恢复学生信息（会话级内存持有，不持久化敏感数据）
const userStore = useUserStore()
userStore.restore()
</script>

<template>
  <RouterView v-slot="{ Component }">
    <transition name="view-transition" mode="out-in">
      <component :is="Component" />
    </transition>
  </RouterView>
</template>

<style lang="scss">
// App.vue 仅承载路由出口，全部布局在 layouts 与 views 内
#app {
  height: 100%;
}
</style>
