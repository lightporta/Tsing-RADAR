<script setup lang="ts">
import { onMounted, ref } from 'vue'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import InboundList from '@/components/mentor/InboundList.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import {
  fetchMentorInboundApplications,
  fetchMentorInboundFeedback,
  fetchMentorInboundMatches,
} from '@/api/mentor'
import type {
  MentorFeedbackSummary,
  MentorInboundApplications,
  MentorInboundMatches,
} from '@/types/mentor'
import { displayTime, formatBytes } from '@/utils/format'

// =====================================================================
// 意向中心：匹配意向、站内投递与反馈概览。
// 学生身份与联系方式不下发，仅提供匿名化摘要。
// =====================================================================

const matches = ref<MentorInboundMatches>({ total: 0, recent: [] })
const applications = ref<MentorInboundApplications>({ total: 0, data: [] })
const feedback = ref<MentorFeedbackSummary>({ total: 0, positive: 0, negative: 0 })
const matchesLoading = ref(false)
const applicationsLoading = ref(false)
const feedbackLoading = ref(false)

const applicationStatusLabels: Record<string, string> = {
  submitted: '已投递',
  accepted: '已接受',
  rejected: '未通过',
}

async function loadMatches() {
  matchesLoading.value = true
  try {
    matches.value = await fetchMentorInboundMatches()
  } finally {
    matchesLoading.value = false
  }
}

async function loadApplications() {
  applicationsLoading.value = true
  try {
    applications.value = await fetchMentorInboundApplications()
  } finally {
    applicationsLoading.value = false
  }
}

async function loadFeedback() {
  feedbackLoading.value = true
  try {
    feedback.value = await fetchMentorInboundFeedback()
  } finally {
    feedbackLoading.value = false
  }
}

function displaySize(bytes?: number | null) {
  return bytes == null ? '—' : formatBytes(bytes)
}

onMounted(() => {
  void loadMatches()
  void loadApplications()
  void loadFeedback()
})
</script>

<template>
  <SubPageLayout title="意向中心 · Tsing-RADAR">
    <div class="intents-view">
      <div class="container">
        <section class="feedback-panel" aria-label="反馈概览">
          <h2>学生反馈概览</h2>
          <div v-loading="feedbackLoading" class="feedback-stats">
            <div class="stat-card">
              <strong>{{ feedback.positive }}</strong>
              <span>正面反馈</span>
            </div>
            <div class="stat-card">
              <strong>{{ feedback.negative }}</strong>
              <span>负面反馈</span>
            </div>
            <div class="stat-card">
              <strong>{{ feedback.total }}</strong>
              <span>累计反馈</span>
            </div>
          </div>
          <p class="feedback-note">仅提供计数概览；评论正文不下发，以保护反馈者身份。</p>
        </section>

        <InboundList :matches="matches" :loading="matchesLoading" />

        <section class="apps-panel" aria-labelledby="apps-title">
          <div class="apps-head">
            <h2 id="apps-title">站内投递</h2>
            <span class="apps-count">共 {{ applications.total }} 份</span>
          </div>
          <div v-loading="applicationsLoading" class="apps-body">
            <ul v-if="applications.data.length" class="apps-list">
              <li v-for="app in applications.data" :key="app.app_id" class="app-item">
                <div class="app-top">
                  <span class="app-recruit">{{ app.recruit_id }}</span>
                  <StatusChip
                    :label="applicationStatusLabels[app.status] || app.status"
                    :tone="app.status === 'accepted' ? 'success' : app.status === 'rejected' ? 'danger' : 'default'"
                  />
                </div>
                <p class="app-meta">
                  投递时间 {{ displayTime(app.created_at) }} ·
                  简历 {{ app.resume.present ? `已附（${app.resume.extension || ''}，${displaySize(app.resume.size_bytes)}）` : '未附' }}
                </p>
              </li>
            </ul>
            <p v-else-if="!applicationsLoading" class="apps-empty">暂无投递</p>
          </div>
        </section>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.intents-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
  display: grid;
  gap: $spacing-lg;
}
.feedback-panel,
.apps-panel {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.feedback-panel h2,
.apps-head h2 {
  color: $text-primary;
  font-size: 14px;
  margin-bottom: $spacing-md;
}
.feedback-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: $spacing-md;
}
.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: $spacing-md;
  border-radius: 10px;
  background: $color-bg;
}
.stat-card strong {
  color: $color-primary;
  font-size: 24px;
}
.stat-card span {
  color: $text-secondary;
  font-size: 11px;
}
.feedback-note {
  margin-top: $spacing-md;
  color: $text-placeholder;
  font-size: 11px;
}
.apps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.apps-count {
  color: $text-placeholder;
  font-size: 11px;
}
.apps-list {
  display: grid;
  gap: $spacing-sm;
}
.app-item {
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.app-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}
.app-recruit {
  color: $text-primary;
  font-size: 12px;
  font-weight: 600;
}
.app-meta {
  margin-top: 6px;
  color: $text-regular;
  font-size: 11px;
}
.apps-empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
</style>
