<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'
import { bootstrapSession } from '@/api/request'
import { useRuntimeStore } from '@/stores/useRuntimeStore'

const sessionState = ref<'loading' | 'ready' | 'error'>('loading')
const runtimeStore = useRuntimeStore()

const banners = computed(() => {
  const items: string[] = []
  if (runtimeStore.isFrontendMock) {
    items.push('前端独立 Mock：仅演示页面和规则对话；持久化、匹配与私有文件需连接后端。')
  }
  if (runtimeStore.isLocalRules) {
    items.push('本地规则模式，非真实大模型')
  }
  if (runtimeStore.isSimulationMentors) {
    items.push('当前为本地模拟导师数据，非真实发布数据')
  }
  return items
})

async function initializeSession() {
  sessionState.value = 'loading'
  if (runtimeStore.isFrontendMock) {
    runtimeStore.applySessionMeta({
      llm_mode: 'frontend_mock',
      mentor_policy: 'frontend_mock_empty',
      simulation_mentors: false,
    })
    sessionState.value = 'ready'
    return
  }
  try {
    const session = await bootstrapSession()
    runtimeStore.applySessionMeta(session)
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
  <div v-else class="app-shell">
    <div v-if="banners.length" class="runtime-banners" role="status">
      <p v-for="banner in banners" :key="banner">{{ banner }}</p>
    </div>
    <RouterView v-slot="{ Component }">
      <transition name="view-transition" mode="out-in">
        <component :is="Component" />
      </transition>
    </RouterView>
  </div>
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

.app-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.runtime-banners {
  flex-shrink: 0;
  display: grid;
  gap: 4px;
  padding: 8px 16px;
  background: #fff7e6;
  border-bottom: 1px solid #ffd591;
  color: #8a5a00;
  font-size: 12px;
  line-height: 1.4;
}

.app-shell > :last-child {
  flex: 1;
  min-height: 0;
  height: auto;
}
</style>
