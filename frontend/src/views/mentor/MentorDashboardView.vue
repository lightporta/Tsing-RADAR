<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import { fetchMentorProfile } from '@/api/mentor'
import type { MentorProfile } from '@/types/mentor'
import { useMentorStore } from '@/stores/useMentorStore'

// =====================================================================
// 导师工作台：档案概览 + 功能入口 + 退出登录。
// 自述字段本期仅导师端与管理端可见，学生侧合并在二期开放。
// =====================================================================

const router = useRouter()
const mentorStore = useMentorStore()

const profile = ref<MentorProfile | null>(null)
const loading = ref(false)

const entryCards = [
  { key: 'profile-edit', title: '档案编辑', desc: '提交研究方向亮点、招生要求等字段编辑', icon: '✎' },
  { key: 'intents', title: '意向中心', desc: '查看匹配意向、站内投递与反馈概览', icon: '➤' },
  { key: 'recruitment', title: '招募管理', desc: '发布与维护招生、实习招募信息', icon: '讯' },
  { key: 'privacy', title: '隐私控制', desc: '字段展示策略与档案下架申请', icon: '🔒' },
] as const

async function loadProfile() {
  loading.value = true
  try {
    profile.value = await fetchMentorProfile()
  } finally {
    loading.value = false
  }
}

function go(entry: (typeof entryCards)[number]) {
  router.push(`/mentor/${entry.key}`)
}

async function logout() {
  await mentorStore.logout()
  ElMessage.success('已退出导师登录')
  router.push('/mentor/login')
}

onMounted(loadProfile)
</script>

<template>
  <SubPageLayout title="导师工作台 · Tsing-RADAR">
    <div class="dashboard-view">
      <div class="container">
        <section v-loading="loading" class="profile-card" aria-labelledby="profile-title">
          <div class="profile-head">
            <div>
              <h2 id="profile-title">{{ profile?.name || '我的档案' }}</h2>
              <p class="profile-sub">{{ profile?.dept || '—' }}</p>
            </div>
            <div class="profile-status">
              <StatusChip label="已认领" tone="success" />
              <span class="profile-id">{{ profile?.advisor_id }}</span>
            </div>
          </div>
          <div v-if="profile?.takedown.active" class="takedown-banner">
            <strong>档案已下架</strong>
            <span>生效时间：{{ new Date(profile.takedown.effective_at || '').toLocaleString() }}</span>
          </div>
          <div v-else class="profile-note">
            公开档案来自已发布的治理数据；导师自述与编辑字段当前仅本人与管理员可见。
          </div>
        </section>

        <section class="entry-grid" aria-label="导师服务功能入口">
          <button
            v-for="entry in entryCards"
            :key="entry.key"
            type="button"
            class="entry-card"
            @click="go(entry)"
          >
            <span class="entry-icon" aria-hidden="true">{{ entry.icon }}</span>
            <strong>{{ entry.title }}</strong>
            <p>{{ entry.desc }}</p>
          </button>
        </section>

        <section class="account-card">
          <div class="account-info">
            <strong>当前账号</strong>
            <p>{{ mentorStore.status.email || '—' }}</p>
          </div>
          <el-button plain type="danger" @click="logout">退出登录</el-button>
        </section>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.dashboard-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
  display: grid;
  gap: $spacing-lg;
}
.profile-card,
.account-card {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.profile-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: $spacing-md;
}
.profile-head h2 {
  color: $text-primary;
  font-size: 18px;
}
.profile-sub {
  margin-top: 4px;
  color: $text-secondary;
  font-size: 12px;
}
.profile-status {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}
.profile-id {
  color: $text-placeholder;
  font-size: 11px;
}
.profile-note {
  margin-top: $spacing-md;
  padding: $spacing-sm $spacing-md;
  border-radius: 8px;
  background: $color-bg-hover;
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.6;
}
.takedown-banner {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: $spacing-md;
  padding: $spacing-sm $spacing-md;
  border-radius: 8px;
  background: #fdeeea;
  color: #b4442e;
  font-size: 12px;
}
.entry-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: $spacing-md;
}
.entry-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
  text-align: left;
  transition: $transition-fast;

  &:hover {
    box-shadow: 0 4px 14px rgba(32, 70, 120, 0.1);
    transform: translateY(-1px);
  }
}
.entry-icon {
  font-size: 18px;
}
.entry-card strong {
  color: $text-primary;
  font-size: 14px;
}
.entry-card p {
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.6;
}
.account-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-md;
}
.account-info strong {
  color: $text-primary;
  font-size: 13px;
}
.account-info p {
  margin-top: 3px;
  color: $text-secondary;
  font-size: 12px;
}

@media (max-width: $bp-tablet) {
  .entry-grid {
    grid-template-columns: 1fr;
  }
  .profile-head {
    flex-direction: column;
  }
}
</style>
