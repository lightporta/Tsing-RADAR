import { ref, onMounted, onUnmounted } from 'vue'

// =====================================================================
// 响应式断点检测
// 对齐文档 §8.3：≥1200 三栏 / 1024-1200 压缩 / 768-1024 双栏 / <768 移动端
// =====================================================================

export interface ViewportState {
  width: number
  height: number
  /** 是否移动端 (<768) */
  isMobile: boolean
  /** 是否平板 (768-1024) */
  isTablet: boolean
  /** 是否 PC (≥1024) */
  isPC: boolean
  /** 是否宽屏 PC (≥1200) */
  isWidePC: boolean
}

export function useResponsive() {
  const state = ref<ViewportState>({
    width: window.innerWidth,
    height: window.innerHeight,
    isMobile: false,
    isTablet: false,
    isPC: false,
    isWidePC: false,
  })

  const update = () => {
    const w = window.innerWidth
    state.value = {
      width: w,
      height: window.innerHeight,
      isMobile: w < 768,
      isTablet: w >= 768 && w < 1024,
      isPC: w >= 1024,
      isWidePC: w >= 1200,
    }
  }

  onMounted(() => {
    update()
    window.addEventListener('resize', update, { passive: true })
  })
  onUnmounted(() => {
    window.removeEventListener('resize', update)
  })

  return state
}
