<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import { bootstrapSession } from '@/api/request'

const sessionState = ref<'loading' | 'ready' | 'error'>('loading')

async function initializeSession() {
  sessionState.value = 'loading'
  try {
    await bootstrapSession()
    sessionState.value = 'ready'
  } catch {
    sessionState.value = 'error'
  }
}

onMounted(initializeSession)
</script>

<template>
  <main v-if="sessionState === 'loading'" class="session-gate" aria-live="polite">
    正在建立私有会话…
  </main>
  <main v-else-if="sessionState === 'error'" class="session-gate" role="alert">
    <p>无法建立私有会话，已停止加载个人数据。</p>
    <el-button type="primary" @click="initializeSession">重试</el-button>
  </main>
  <RouterView v-else v-slot="{ Component }">
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

.session-gate {
  min-height: 100%;
  display: grid;
  place-content: center;
  gap: 16px;
  text-align: center;
}
</style>
