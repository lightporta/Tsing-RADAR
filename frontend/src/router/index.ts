import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

// =====================================================================
// 路由设计（文档 §5.1）
// /            → 智能体首页（PC 三栏 / 移动端布局，根据视口自适应）
// /profile     → 个人信息与简历管理页（独立全屏二级页）
// /recruitment → 招募信息平台页（独立全屏二级页）
// =====================================================================

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: 'Tsing-RADAR 清研寻师雷达' },
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

// 全局前置守卫只设置标题；主体由服务端 opaque 会话管理。
router.beforeEach((to, _from, next) => {
  const title = (to.meta.title as string) || 'Tsing-RADAR'
  document.title = title
  next()
})

export default router
