<script setup lang="ts">
import { ref, computed } from 'vue'
import FilterBar from './FilterBar.vue'
import AdvisorCard from './AdvisorCard.vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useInfiniteScroll } from '@/composables/useInfiniteScroll'

// =====================================================================
// 导师卡片列表容器（文档 §3.4）
// 顶部筛选栏 + 卡片纵向排列 + 无限滚动加载更多
// =====================================================================

withDefaults(defineProps<{ mobileMode?: boolean }>(), { mobileMode: false })

const advisorStore = useAdvisorStore()
const listRef = ref<HTMLElement | null>(null)

// 分页：每次展示 N 张，滚动到底部加载更多
const pageSize = 10
const visibleCount = ref(pageSize)

const visibleAdvisors = computed(() => advisorStore.matchedAdvisors.slice(0, visibleCount.value))
const hasMore = computed(() => visibleCount.value < advisorStore.matchedAdvisors.length)

// 列表变化时重置分页
import { watch } from 'vue'
watch(
  () => advisorStore.matchedAdvisors,
  () => {
    visibleCount.value = pageSize
  },
)

const { loading, onScroll } = useInfiniteScroll(listRef, async () => {
  if (!hasMore.value) return
  visibleCount.value = Math.min(visibleCount.value + pageSize, advisorStore.matchedAdvisors.length)
})
</script>

<template>
  <div class="advisor-list-panel">
    <FilterBar />

    <div ref="listRef" class="list-scroll" @scroll="onScroll">
      <!-- 空状态 -->
      <div v-if="!advisorStore.matchedAdvisors.length && !advisorStore.loading" class="empty-state">
        <el-icon class="empty-icon"><Search /></el-icon>
        <p>暂无匹配导师</p>
        <span class="empty-hint">在左侧对话栏输入你的研究兴趣开始匹配</span>
      </div>

      <!-- 加载中骨架 -->
      <div v-else-if="advisorStore.loading && !advisorStore.matchedAdvisors.length" class="skeleton-list">
        <div v-for="i in 5" :key="i" class="skeleton-card" />
      </div>

      <!-- 卡片列表 -->
      <template v-else>
        <div class="card-list">
          <AdvisorCard
            v-for="advisor in visibleAdvisors"
            :key="advisor.name"
            :advisor="advisor"
            :selected="advisorStore.selectedName === advisor.name"
          />
        </div>

        <!-- 加载更多 -->
        <div v-if="loading" class="load-more">
          <span class="loading-dot" /> 加载更多…
        </div>
        <div v-else-if="!hasMore && visibleAdvisors.length > pageSize" class="load-end">
          — 已加载全部 {{ advisorStore.matchedAdvisors.length }} 位导师 —
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
.advisor-list-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: $color-bg-card;
  overflow: hidden;
}

.list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: $spacing-md $spacing-lg;
  -webkit-overflow-scrolling: touch;
}

.card-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}

// 空状态
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: $text-placeholder;
  text-align: center;

  .empty-icon {
    font-size: 40px;
    margin-bottom: $spacing-md;
    color: $color-border;
  }
  p {
    font-size: 14px;
    color: $text-secondary;
    margin-bottom: 4px;
  }
  .empty-hint {
    font-size: 12px;
  }
}

// 骨架屏
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}
.skeleton-card {
  height: 100px;
  border-radius: $card-radius;
  background: linear-gradient(90deg, $color-bg 25%, $color-border-light 50%, $color-bg 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.load-more,
.load-end {
  text-align: center;
  padding: $spacing-lg;
  font-size: 12px;
  color: $text-placeholder;
}
.loading-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: $color-primary;
  margin-right: 4px;
  animation: pulse 1s infinite;
}
@keyframes pulse {
  0%, 100% {
    opacity: 0.3;
  }
  50% {
    opacity: 1;
  }
}
</style>
