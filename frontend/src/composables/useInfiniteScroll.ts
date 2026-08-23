import { ref, type Ref } from 'vue'

// =====================================================================
// 无限滚动加载
// 监听容器滚动到底部时触发 loadMore
// =====================================================================

export function useInfiniteScroll(
  containerRef: Ref<HTMLElement | null>,
  onLoadMore: () => void | Promise<void>,
  options: { threshold?: number; enabled?: Ref<boolean> } = {},
) {
  const { threshold = 80, enabled } = options
  const loading = ref(false)

  const onScroll = async () => {
    if (!enabled || enabled.value === false) return
    const el = containerRef.value
    if (!el || loading.value) return
    const { scrollTop, scrollHeight, clientHeight } = el
    if (scrollHeight - scrollTop - clientHeight < threshold) {
      loading.value = true
      try {
        await onLoadMore()
      } finally {
        loading.value = false
      }
    }
  }

  return { loading, onScroll }
}
