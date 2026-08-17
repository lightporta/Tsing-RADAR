<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import {
  fetchAdminMentorClaims,
  fetchAdminMentorEdits,
  fetchAdminMentorTakedowns,
  reviewMentorClaim,
  reviewMentorEdit,
  reviewMentorTakedown,
} from '@/api/admin'
import type {
  AdminMentorClaimItem,
  MentorEditRecord,
  MentorTakedownRecord,
} from '@/types/mentor'
import { REVIEW_STATUS_LABELS, SELF_CLAIM_FIELD_META } from '@/types/mentor'

// =====================================================================
// 导师服务管理审批端：认领 / 字段编辑 / 下架 三类审批流。
// 管理员令牌仅保存在当前会话（sessionStorage），可随时清除。
// =====================================================================

const ADMIN_TOKEN_KEY = 'mentor_admin_token'

const token = ref(sessionStorage.getItem(ADMIN_TOKEN_KEY) || '')
const activeTab = ref('claims')
const loading = ref(false)
const listError = ref('')

const claims = ref<AdminMentorClaimItem[]>([])
const edits = ref<MentorEditRecord[]>([])
const takedowns = ref<MentorTakedownRecord[]>([])

const claimsFilter = ref<'pending' | 'approved' | 'rejected' | ''>('pending')
const editsFilter = ref<'pending' | 'approved' | 'rejected' | ''>('pending')
const takedownsFilter = ref<'pending' | 'approved' | 'rejected' | ''>('pending')

const factorLabels: Record<string, string> = {
  auto_unique: '唯一候选自动绑定',
  manual: '人工审核',
}

function fieldLabel(fieldName: string) {
  return SELF_CLAIM_FIELD_META[fieldName]?.label || fieldName
}

function saveToken() {
  if (token.value.trim()) {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, token.value.trim())
  } else {
    sessionStorage.removeItem(ADMIN_TOKEN_KEY)
  }
}

function clearToken() {
  token.value = ''
  sessionStorage.removeItem(ADMIN_TOKEN_KEY)
  claims.value = []
  edits.value = []
  takedowns.value = []
  ElMessage.success('已清除管理员令牌')
}

async function loadActive() {
  const adminToken = token.value.trim()
  if (!adminToken) {
    ElMessage.warning('请先输入管理员令牌')
    return
  }
  saveToken()
  loading.value = true
  listError.value = ''
  try {
    if (activeTab.value === 'claims') {
      claims.value = (
        await fetchAdminMentorClaims(adminToken, claimsFilter.value || undefined)
      ).data
    } else if (activeTab.value === 'edits') {
      edits.value = (
        await fetchAdminMentorEdits(adminToken, editsFilter.value || undefined)
      ).data
    } else {
      takedowns.value = (
        await fetchAdminMentorTakedowns(adminToken, takedownsFilter.value || undefined)
      ).data
    }
  } catch {
    listError.value = '加载失败：令牌无效或服务暂不可用'
  } finally {
    loading.value = false
  }
}

async function reviewClaim(item: AdminMentorClaimItem, action: 'approve' | 'reject') {
  try {
    const { value } = await ElMessageBox.prompt(
      `对「${item.advisor_id}」的认领申请${action === 'approve' ? '通过' : '驳回'}？可填写审批备注。`,
      action === 'approve' ? '通过认领' : '驳回认领',
      { confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '审批备注（选填）' },
    )
    await reviewMentorClaim(token.value.trim(), item.claim_id, action, value?.trim() || undefined)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    throw error
  }
  ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
  await loadActive()
}

async function reviewEdit(item: MentorEditRecord, action: 'approve' | 'reject') {
  try {
    const { value } = await ElMessageBox.prompt(
      `对「${fieldLabel(item.field_name)}」的编辑申请${action === 'approve' ? '通过' : '驳回'}？可填写审批备注。`,
      action === 'approve' ? '通过编辑' : '驳回编辑',
      { confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '审批备注（选填）' },
    )
    await reviewMentorEdit(token.value.trim(), item.edit_id, action, value?.trim() || undefined)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    throw error
  }
  ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
  await loadActive()
}

async function reviewTakedown(item: MentorTakedownRecord, action: 'approve' | 'reject') {
  try {
    const { value } = await ElMessageBox.prompt(
      `对${item.scope === 'full' ? '整体下架' : `字段「${fieldLabel(item.field_name || '')}」下架`}申请${action === 'approve' ? '通过' : '驳回'}？可填写审批备注。`,
      action === 'approve' ? '通过下架' : '驳回下架',
      { confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '审批备注（选填）' },
    )
    await reviewMentorTakedown(token.value.trim(), item.req_id, action, value?.trim() || undefined)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    throw error
  }
  ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
  await loadActive()
}

function displayTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

onMounted(() => {
  if (token.value.trim()) {
    void loadActive()
  }
})
</script>

<template>
  <SubPageLayout title="导师服务审批 · Tsing-RADAR">
    <div class="admin-view">
      <div class="container">
        <section class="token-panel">
          <div class="token-row">
            <el-input
              v-model="token"
              type="password"
              show-password
              placeholder="管理员令牌（X-Admin-Token）"
              style="max-width: 320px"
              @keyup.enter="loadActive"
            />
            <el-button type="primary" :loading="loading" @click="loadActive">
              加载待办
            </el-button>
            <el-button plain @click="clearToken">清除令牌</el-button>
          </div>
          <p class="token-note">令牌仅保存在当前浏览器会话；审计事件由服务端记录。</p>
        </section>

        <section class="review-panel">
          <el-tabs v-model="activeTab" @tab-change="loadActive">
            <el-tab-pane label="认领审批" name="claims">
              <div class="filter-row">
                <el-radio-group v-model="claimsFilter" @change="loadActive">
                  <el-radio-button value="pending">待处理</el-radio-button>
                  <el-radio-button value="approved">已通过</el-radio-button>
                  <el-radio-button value="rejected">已驳回</el-radio-button>
                </el-radio-group>
              </div>
              <div v-loading="loading" class="list-wrap">
                <p v-if="listError" class="list-error">{{ listError }}</p>
                <ul v-else-if="claims.length" class="review-list">
                  <li v-for="item in claims" :key="item.claim_id" class="review-item">
                    <div class="review-top">
                      <strong>{{ item.advisor_id }}</strong>
                      <StatusChip
                        :label="REVIEW_STATUS_LABELS[item.status] || item.status"
                        :tone="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'warning'"
                      />
                    </div>
                    <p class="review-meta">
                      {{ factorLabels[item.factor_used] || item.factor_used }} ·
                      提交 {{ displayTime(item.created_at) }}
                    </p>
                    <div v-if="item.status === 'pending'" class="review-actions">
                      <el-button size="small" type="primary" plain @click="reviewClaim(item, 'approve')">
                        通过
                      </el-button>
                      <el-button size="small" plain type="danger" @click="reviewClaim(item, 'reject')">
                        驳回
                      </el-button>
                    </div>
                  </li>
                </ul>
                <p v-else-if="!loading" class="list-empty">暂无记录</p>
              </div>
            </el-tab-pane>

            <el-tab-pane label="档案编辑审批" name="edits">
              <div class="filter-row">
                <el-radio-group v-model="editsFilter" @change="loadActive">
                  <el-radio-button value="pending">待处理</el-radio-button>
                  <el-radio-button value="approved">已通过</el-radio-button>
                  <el-radio-button value="rejected">已驳回</el-radio-button>
                </el-radio-group>
              </div>
              <div v-loading="loading" class="list-wrap">
                <p v-if="listError" class="list-error">{{ listError }}</p>
                <ul v-else-if="edits.length" class="review-list">
                  <li v-for="item in edits" :key="item.edit_id" class="review-item">
                    <div class="review-top">
                      <strong>{{ fieldLabel(item.field_name) }}</strong>
                      <StatusChip
                        :label="REVIEW_STATUS_LABELS[item.status] || item.status"
                        :tone="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'warning'"
                      />
                    </div>
                    <p class="review-edit-value">
                      <span class="review-edit-avatar">{{ item.advisor_id || '—' }}</span>
                      {{ item.new_value }}
                    </p>
                    <p class="review-meta">
                      提交 {{ displayTime(item.created_at) }} · 判定 {{ displayTime(item.decided_at) }}
                    </p>
                    <div v-if="item.status === 'pending'" class="review-actions">
                      <el-button size="small" type="primary" plain @click="reviewEdit(item, 'approve')">
                        通过
                      </el-button>
                      <el-button size="small" plain type="danger" @click="reviewEdit(item, 'reject')">
                        驳回
                      </el-button>
                    </div>
                  </li>
                </ul>
                <p v-else-if="!loading" class="list-empty">暂无记录</p>
              </div>
            </el-tab-pane>

            <el-tab-pane label="下架审批" name="takedowns">
              <div class="filter-row">
                <el-radio-group v-model="takedownsFilter" @change="loadActive">
                  <el-radio-button value="pending">待处理</el-radio-button>
                  <el-radio-button value="approved">已通过</el-radio-button>
                  <el-radio-button value="rejected">已驳回</el-radio-button>
                </el-radio-group>
              </div>
              <div v-loading="loading" class="list-wrap">
                <p v-if="listError" class="list-error">{{ listError }}</p>
                <ul v-else-if="takedowns.length" class="review-list">
                  <li v-for="item in takedowns" :key="item.req_id" class="review-item">
                    <div class="review-top">
                      <strong>
                        {{ item.scope === 'full' ? '整体下架' : `字段下架：${fieldLabel(item.field_name || '')}` }}
                      </strong>
                      <StatusChip
                        :label="REVIEW_STATUS_LABELS[item.status] || item.status"
                        :tone="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'warning'"
                      />
                    </div>
                    <p class="review-reason">{{ item.reason }}</p>
                    <p class="review-meta">
                      提交 {{ displayTime(item.created_at) }} · 判定 {{ displayTime(item.decided_at) }}
                    </p>
                    <div v-if="item.status === 'pending'" class="review-actions">
                      <el-button size="small" type="primary" plain @click="reviewTakedown(item, 'approve')">
                        通过
                      </el-button>
                      <el-button size="small" plain type="danger" @click="reviewTakedown(item, 'reject')">
                        驳回
                      </el-button>
                    </div>
                  </li>
                </ul>
                <p v-else-if="!loading" class="list-empty">暂无记录</p>
              </div>
            </el-tab-pane>
          </el-tabs>
        </section>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.admin-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
  display: grid;
  gap: $spacing-lg;
}
.token-panel,
.review-panel {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.token-row {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
}
.token-note {
  margin-top: $spacing-sm;
  color: $text-placeholder;
  font-size: 11px;
}
.filter-row {
  margin-bottom: $spacing-md;
}
.list-wrap {
  min-height: 80px;
}
.list-error {
  padding: $spacing-lg;
  text-align: center;
  color: #b4442e;
  font-size: 12px;
}
.list-empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
.review-list {
  display: grid;
  gap: $spacing-sm;
}
.review-item {
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.review-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}
.review-top strong {
  color: $text-primary;
  font-size: 13px;
}
.review-meta {
  margin-top: 4px;
  color: $text-placeholder;
  font-size: 10px;
}
.review-edit-value {
  margin-top: 6px;
  color: $text-regular;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.review-edit-avatar {
  color: $text-placeholder;
  font-size: 11px;
}
.review-reason {
  margin-top: 6px;
  color: $text-regular;
  font-size: 12px;
  line-height: 1.6;
}
.review-actions {
  display: flex;
  gap: $spacing-sm;
  margin-top: $spacing-sm;
}
</style>
