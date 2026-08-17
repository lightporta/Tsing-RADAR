import { ref } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { beginRoute, finishRoute } from '@/utils/performance'

// =====================================================================
// 路由设计（文档 §5.1）
// /            → 智能体首页（PC 三栏 / 移动端布局，根据视口自适应）
// /profile     → 个人信息与简历管理页（独立全屏二级页）
// /recruitment → 招募信息平台页（独立全屏二级页）
// /mentor/*    → 导师服务门户（邮箱验证码登录 → 认领 → 工作台）
// /admin/reviews → 导师服务管理审批端（X-Admin-Token）
// =====================================================================

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: 'Tsing-RADAR 清研寻师雷达' },
  },
  {
    path: '/mentors',
    name: 'mentors',
    component: () => import('@/views/MentorLibraryView.vue'),
    meta: { title: '导师资源库 · Tsing-RADAR' },
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/ProfileView.vue'),
    meta: { title: '个人信息 · Tsing-RADAR' },
  },
  {
    path: '/recruitment',
    name: 'recruitment',
    component: () => import('@/views/RecruitmentView.vue'),
    meta: { title: '信息平台 · Tsing-RADAR' },
  },
  {
    path: '/mentor/login',
    name: 'mentor-login',
    component: () => import('@/views/mentor/MentorLoginView.vue'),
    meta: { title: '导师登录 · Tsing-RADAR' },
  },
  {
    path: '/mentor/claim',
    name: 'mentor-claim',
    component: () => import('@/views/mentor/MentorClaimView.vue'),
    meta: { title: '档案认领 · Tsing-RADAR' },
  },
  {
    path: '/mentor/dashboard',
    name: 'mentor-dashboard',
    component: () => import('@/views/mentor/MentorDashboardView.vue'),
    meta: { title: '导师工作台 · Tsing-RADAR' },
  },
  {
    path: '/mentor/profile-edit',
    name: 'mentor-profile-edit',
    component: () => import('@/views/mentor/MentorProfileEditView.vue'),
    meta: { title: '档案编辑 · Tsing-RADAR' },
  },
  {
    path: '/mentor/intents',
    name: 'mentor-intents',
    component: () => import('@/views/mentor/MentorIntentsView.vue'),
    meta: { title: '意向中心 · Tsing-RADAR' },
  },
  {
    path: '/mentor/recruitment',
    name: 'mentor-recruitment',
    component: () => import('@/views/mentor/MentorRecruitmentView.vue'),
    meta: { title: '招募管理 · Tsing-RADAR' },
  },
  {
    path: '/mentor/privacy',
    name: 'mentor-privacy',
    component: () => import('@/views/mentor/MentorPrivacyView.vue'),
    meta: { title: '隐私控制 · Tsing-RADAR' },
  },
  {
    path: '/admin/reviews',
    name: 'admin-reviews',
    component: () => import('@/views/AdminReviewView.vue'),
    meta: { title: '导师服务审批 · Tsing-RADAR' },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

export const routePending = ref(false)

// 全局前置守卫设置标题；/mentor/* 校验导师会话绑定与认领状态，
// 主体身份仍由服务端 opaque 会话管理（登录态每次导航向 /api/mentor/auth/status 刷新）。
router.beforeEach(async (to, _from, next) => {
  routePending.value = true
  beginRoute(to.fullPath)
  const title = (to.meta.title as string) || 'Tsing-RADAR'
  document.title = title

  if (to.path.startsWith('/mentor/')) {
    const { useMentorStore } = await import('@/stores/useMentorStore')
    const mentorStore = useMentorStore()
    await mentorStore.refreshAuth()
    if (to.path === '/mentor/login') {
      if (mentorStore.isClaimed) {
        next('/mentor/dashboard')
        return
      }
      next()
      return
    }
    if (!mentorStore.isLoggedIn) {
      next('/mentor/login')
      return
    }
    if (to.path !== '/mentor/claim' && !mentorStore.isClaimed) {
      next('/mentor/claim')
      return
    }
    if (to.path === '/mentor/claim' && mentorStore.isClaimed) {
      next('/mentor/dashboard')
      return
    }
  }
  next()
})

router.afterEach((_to, _from, failure) => {
  routePending.value = false
  finishRoute(failure ? 'failed' : 'complete')
})

router.onError(() => {
  routePending.value = false
  finishRoute('error')
})

export default router
