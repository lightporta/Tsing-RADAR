<script setup lang="ts">
import { onMounted } from 'vue'
import PCLayout from '@/layouts/PCLayout.vue'
import MobileLayout from '@/layouts/MobileLayout.vue'
import { useResponsive } from '@/composables/useResponsive'
import { useChatStore } from '@/stores/useChatStore'
import { useAdvisorStore } from '@/stores/useAdvisorStore'

// =====================================================================
// 首页：根据视口自适应 PC / 移动端布局
// =====================================================================

const viewport = useResponsive()
const chatStore = useChatStore()
const advisorStore = useAdvisorStore()

onMounted(async () => {
  chatStore.initWelcome()
  await advisorStore.loadAll()
})
</script>

<template>
  <PCLayout v-if="viewport.isPC" />
  <MobileLayout v-else />
</template>
