<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import FieldEditForm from '@/components/mentor/FieldEditForm.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import { fetchMentorProfile, fetchMyMentorEdits } from '@/api/mentor'
import type { MentorEditRecord, MentorProfile } from '@/types/mentor'
import { SELF_CLAIM_FIELD_META, REVIEW_STATUS_LABELS } from '@/types/mentor'

// =====================================================================
// 档案编辑页：查看公开字段与过审自述；提交字段级编辑申请（审批流）。
// =====================================================================

const profile = ref<MentorProfile | null>(null)
const edits = ref<MentorEditRecord[]>([])
const profileLoading = ref(false)
const editsLoading = ref(false)

const profileEntries = computed(() => {
  if (!profile.value) return []
  return Object.entries(profile.value.public_fields).filter(
    ([key]) => key !== 'name' && key !== 'dept',
  )
})

const selfClaimEntries = computed(() => {
  if (!profile.value) return []
  return Object.entries(profile.value.self_claims)
})

function fieldLabel(fieldName: string) {
  return SELF_CLAIM_FIELD_META[fieldName]?.label || fieldName
}

async function loadProfile() {
  profileLoading.value = true
  try {
    profile.value = await fetchMentorProfile()
  } finally {
    profileLoading.value = false
  }
}

async function loadEdits() {
  editsLoading.value = true
  try {
    edits.value = (await fetchMyMentorEdits()).data
  } finally {
    editsLoading.value = false
  }
}

function handleSaved() {
  void loadEdits()
  void loadProfile()
}

function displayTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

onMounted(() => {
  void loadProfile()
  void loadEdits()
})
</script>

<template>
  <SubPageLayout title="档案编辑 · Tsing-RADAR">
    <div class="edit-view">
      <div class="container">
        <section class="form-panel" aria-labelledby="form-title">
          <h2 id="form-title">提交字段编辑申请</h2>
          <p class="form-desc">
            修改的内容需管理员审批；通过前仅保存为草稿申请，不影响已公开档案。
          </p>
          <FieldEditForm @saved="handleSaved" />
        </section>

        <section v-loading="profileLoading" class="profile-panel" aria-labelledby="profile-title">
          <h2 id="profile-title">当前档案</h2>
          <div v-if="profile" class="profile-fields">
            <div class="profile-hero">
              <strong>{{ profile.name }}</strong>
              <span>{{ profile.dept }}</span>
            </div>
            <dl v-if="profileEntries.length" class="field-list">
              <div v-for="[key, value] in profileEntries" :key="key">
                <dt>{{ fieldLabel(key) }}</dt>
                <dd>{{ String(value) }}</dd>
              </div>
            </dl>
            <p v-if="!profileEntries.length" class="field-empty">公开档案暂无其他字段</p>
            <h3 class="claims-title">已过审的自述内容</h3>
            <dl v-if="selfClaimEntries.length" class="field-list">
              <div v-for="[key, value] in selfClaimEntries" :key="key">
                <dt>{{ fieldLabel(key) }}</dt>
                <dd>{{ value }}</dd>
              </div>
            </dl>
            <p v-else class="field-empty">暂无自述内容</p>
          </div>
        </section>

        <section v-loading="editsLoading" class="history-panel" aria-labelledby="history-title">
          <h2 id="history-title">编辑申请历史</h2>
          <ul v-if="edits.length" class="edit-list">
            <li v-for="item in edits" :key="item.edit_id" class="edit-item">
              <div class="edit-top">
                <strong>{{ fieldLabel(item.field_name) }}</strong>
                <StatusChip
                  :label="REVIEW_STATUS_LABELS[item.status] || item.status"
                  :tone="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'warning'"
                />
              </div>
              <p class="edit-meta">
                提交 {{ displayTime(item.created_at) }} · 判定 {{ displayTime(item.decided_at) }}
              </p>
              <div class="edit-values">
                <span v-if="item.new_value" class="edit-new">{{ item.new_value }}</span>
              </div>
              <p v-if="item.admin_note" class="edit-note">{{ item.admin_note }}</p>
            </li>
          </ul>
          <p v-else-if="!editsLoading" class="edit-empty">暂无编辑申请</p>
        </section>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.edit-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
  display: grid;
  gap: $spacing-lg;
}
.form-panel,
.profile-panel,
.history-panel {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.form-panel h2,
.profile-panel h2,
.history-panel h2 {
  color: $text-primary;
  font-size: 15px;
  margin-bottom: $spacing-md;
}
.form-desc {
  margin-bottom: $spacing-md;
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.6;
}
.profile-hero {
  display: flex;
  align-items: baseline;
  gap: $spacing-sm;
  margin-bottom: $spacing-md;
}
.profile-hero strong {
  color: $text-primary;
  font-size: 16px;
}
.profile-hero span {
  color: $text-secondary;
  font-size: 12px;
}
.claims-title {
  margin: $spacing-md 0 $spacing-sm;
  color: $text-primary;
  font-size: 13px;
}
.field-list {
  display: grid;
  gap: $spacing-sm;
}
.field-list div {
  padding: $spacing-sm;
  border-radius: 8px;
  background: $color-bg;
}
.field-list dt {
  color: $text-placeholder;
  font-size: 10px;
}
.field-list dd {
  margin-top: 4px;
  color: $text-regular;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.field-empty,
.edit-empty {
  padding: $spacing-md;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
.edit-list {
  display: grid;
  gap: $spacing-sm;
}
.edit-item {
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.edit-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}
.edit-top strong {
  color: $text-primary;
  font-size: 13px;
}
.edit-meta {
  margin-top: 4px;
  color: $text-placeholder;
  font-size: 10px;
}
.edit-values {
  margin-top: 6px;
}
.edit-new {
  display: block;
  color: $text-regular;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.edit-note {
  margin-top: 6px;
  color: #8a5a14;
  font-size: 12px;
}
</style>
