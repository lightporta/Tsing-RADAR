// =====================================================================
// 导师服务会话 Store
// 登录态由后端 opaque 会话 Cookie + mentor_accounts.bound_session_id 决定；
// 此处仅缓存 GET /api/mentor/auth/status 结果，不落任何本地存储。
// =====================================================================

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { fetchMentorAuthStatus, mentorLogout } from '@/api/mentor'
import type { MentorAuthStatus } from '@/types/mentor'

export const useMentorStore = defineStore('mentor', () => {
  const status = ref<MentorAuthStatus>({ logged_in: false })
  const loading = ref(false)

  const isLoggedIn = computed(() => status.value.logged_in === true)
  const isClaimed = computed(
    () => isLoggedIn.value && status.value.status === 'claimed',
  )
  const accountStatus = computed(() => status.value.status || 'unclaimed')

  /** 刷新登录状态；失败按未登录处理（守卫据此重定向）。 */
  async function refreshAuth() {
    loading.value = true
    try {
      status.value = await fetchMentorAuthStatus()
    } catch {
      status.value = { logged_in: false }
    } finally {
      loading.value = false
    }
  }

  /** 解除当前会话与导师账号的绑定。 */
  async function logout() {
    try {
      await mentorLogout()
    } finally {
      status.value = { logged_in: false }
    }
  }

  return {
    status,
    loading,
    isLoggedIn,
    isClaimed,
    accountStatus,
    refreshAuth,
    logout,
  }
})
