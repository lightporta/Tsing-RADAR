<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import ClaimCandidateCard from '@/components/mentor/ClaimCandidateCard.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import {
  fetchCampusCardStatus,
  fetchMentorClaimEligible,
  fetchMentorClaimHistory,
  uploadCampusCard,
} from '@/api/mentor'
import type { MentorCandidate, MentorClaimRecord } from '@/types/mentor'
import { CAMPUS_CARD_STATUS_LABELS, REVIEW_STATUS_LABELS } from '@/types/mentor'
import { displayTime } from '@/utils/format'

// =====================================================================
// 档案认领页：校园卡人工审核（前置）→ 搜索公开候选 → 认领。
// 唯一候选自动绑定；重名候选进入管理员人工审核。
// =====================================================================

const ALLOWED_CARD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'pdf']
const MAX_CARD_BYTES = 8 * 1024 * 1024

const router = useRouter()
const name = ref('')
const department = ref('')
const searching = ref(false)
const searched = ref(false)
const candidates = ref<MentorCandidate[]>([])
const claims = ref<MentorClaimRecord[]>([])
const claimsLoading = ref(false)
const searchError = ref('')

const cardStatus = ref<'loading' | 'none' | 'pending' | 'approved' | 'rejected'>('loading')
const cardNote = ref<string | null>(null)
const cardUploadedAt = ref<string | null>(null)
const uploadingCard = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const claimBlocked = computed(() => cardStatus.value !== 'approved')
const cardStatusLabel = computed(() => CAMPUS_CARD_STATUS_LABELS[cardStatus.value] || cardStatus.value)

async function loadCardStatus() {
  try {
    const result = await fetchCampusCardStatus()
    cardStatus.value = result.status
    cardNote.value = result.card?.review_note ?? null
    cardUploadedAt.value = result.card?.uploaded_at ?? null
  } catch {
    // 未登录等场景由路由守卫处理；这里保持 loading 即可
    cardStatus.value = 'loading'
  }
}

function triggerFilePick() {
  fileInput.value?.click()
}

function validateCardFile(file: File) {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  if (!ALLOWED_CARD_EXTENSIONS.includes(extension)) {
    return '校园卡仅支持 JPG、PNG、WebP 或 PDF'
  }
  if (file.size > MAX_CARD_BYTES) {
    return '校园卡文件不能超过 8 MB'
  }
  return ''
}

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const error = validateCardFile(file)
  if (error) {
    ElMessage.warning(error)
    return
  }
  uploadingCard.value = true
  try {
    await uploadCampusCard(file)
    ElMessage.success('校园卡已提交，等待管理员人工审核')
    cardStatus.value = 'pending'
    await loadCardStatus()
  } catch {
    // 错误提示由拦截器统一弹出
  } finally {
    uploadingCard.value = false
  }
}

function validateSearch() {
  if (!name.value.trim()) return '请输入导师姓名'
  return ''
}

async function search() {
  const error = validateSearch()
  if (error) {
    ElMessage.warning(error)
    return
  }
  searching.value = true
  searchError.value = ''
  try {
    const result = await fetchMentorClaimEligible(name.value.trim(), department.value.trim())
    candidates.value = result.data
    searched.value = true
  } catch {
    searchError.value = '查询失败，请稍后重试'
  } finally {
    searching.value = false
  }
}

function handleClaimed() {
  void loadClaims()
  router.push('/mentor/dashboard')
}

function handlePending() {
  void loadClaims()
}

async function loadClaims() {
  claimsLoading.value = true
  try {
    claims.value = (await fetchMentorClaimHistory()).data
  } finally {
    claimsLoading.value = false
  }
}

onMounted(() => {
  void loadCardStatus()
  void loadClaims()
})
</script>

<template>
  <SubPageLayout title="档案认领 · Tsing-RADAR">
    <div class="claim-view">
      <div class="container">
        <section class="card-panel" aria-labelledby="card-title">
          <h2 id="card-title">校园卡身份审核</h2>
          <p class="card-desc">
            邮箱验证码仅用于登录；认领导师档案前，需上传校园卡材料
            （JPG / PNG / WebP / PDF，不超过 8 MB）并通过管理员人工审核。
            材料仅在审核期间留存，审核结束后立即清理。
          </p>
          <div v-if="cardStatus === 'loading'" v-loading="true" class="card-status" />
          <template v-else>
            <div class="card-status-row">
              <span class="card-status-label">当前状态</span>
              <StatusChip
                :label="cardStatusLabel"
                :tone="cardStatus === 'approved' ? 'success' : cardStatus === 'rejected' ? 'danger' : cardStatus === 'pending' ? 'warning' : 'muted'"
              />
              <span v-if="cardUploadedAt" class="card-meta">
                提交于 {{ displayTime(cardUploadedAt) }}
              </span>
            </div>
            <p v-if="cardNote" class="card-note">审核意见：{{ cardNote }}</p>
            <div v-if="cardStatus !== 'approved'" class="card-actions">
              <input
                ref="fileInput"
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.pdf"
                class="card-file-input"
                @change="handleFileChange"
              />
              <el-button
                type="primary"
                :loading="uploadingCard"
                @click="triggerFilePick"
              >
                {{ cardStatus === 'pending' ? '重新上传材料' : '上传校园卡' }}
              </el-button>
            </div>
            <p v-else class="card-passed">身份审核已通过，可在下方认领档案。</p>
          </template>
        </section>

        <section
          class="claim-panel"
          :class="{ 'claim-disabled': claimBlocked }"
          aria-labelledby="claim-title"
        >
          <h2 id="claim-title">认领我的公开档案</h2>
          <p class="claim-desc">
            按姓名搜索已发布的导师公开档案；如仅有一个匹配将直接绑定，
            重名等情况会进入管理员人工审核。
          </p>
          <p v-if="claimBlocked" class="claim-gate">
            需先完成校园卡身份审核，才能提交档案认领。
          </p>
          <div class="search-row">
            <el-input
              v-model="name"
              placeholder="导师姓名（必填）"
              clearable
              style="max-width: 220px"
              :disabled="claimBlocked"
              @keyup.enter="search"
            />
            <el-input
              v-model="department"
              placeholder="院系（选填）"
              clearable
              style="max-width: 260px"
              :disabled="claimBlocked"
              @keyup.enter="search"
            />
            <el-button
              type="primary"
              :loading="searching"
              :disabled="claimBlocked"
              @click="search"
            >
              搜索候选
            </el-button>
          </div>
          <p v-if="searchError" class="search-error">{{ searchError }}</p>

          <div v-if="searched && !searching" class="candidate-list">
            <p v-if="!candidates.length" class="search-empty">
              未找到匹配的公开档案，请核对姓名或院系后重试。
            </p>
            <ClaimCandidateCard
              v-for="candidate in candidates"
              :key="candidate.advisor_id"
              :candidate="candidate"
              @claimed="handleClaimed"
              @pending="handlePending"
            />
            <p v-if="candidates.length > 1" class="search-note">
              检测到多个同名候选，需管理员人工审核后完成绑定。
            </p>
          </div>
        </section>

        <section v-loading="claimsLoading" class="history-panel" aria-labelledby="history-title">
          <div class="history-head">
            <h2 id="history-title">认领记录</h2>
            <button type="button" class="refresh-btn" :disabled="claimsLoading" @click="loadClaims">
              刷新
            </button>
          </div>
          <ul v-if="claims.length" class="history-list">
            <li v-for="item in claims" :key="item.claim_id" class="history-item">
              <div class="history-top">
                <strong>{{ item.advisor_id }}</strong>
                <StatusChip
                  :label="REVIEW_STATUS_LABELS[item.status] || item.status"
                  :tone="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'warning'"
                />
              </div>
              <p class="history-meta">
                提交 {{ displayTime(item.created_at) }} · 判定 {{ displayTime(item.decided_at) }}
              </p>
              <p v-if="item.admin_note" class="history-note">{{ item.admin_note }}</p>
            </li>
          </ul>
          <p v-else-if="!claimsLoading" class="history-empty">暂无认领记录</p>
        </section>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.claim-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
  display: grid;
  gap: $spacing-lg;
}
.card-panel,
.claim-panel,
.history-panel {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.card-panel h2,
.claim-panel h2,
.history-head h2 {
  color: $text-primary;
  font-size: 15px;
}
.card-desc,
.claim-desc {
  margin: $spacing-sm 0 $spacing-md;
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.6;
}
.card-status {
  min-height: 48px;
}
.card-status-row {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  flex-wrap: wrap;
}
.card-status-label {
  color: $text-regular;
  font-size: 12px;
}
.card-meta {
  color: $text-placeholder;
  font-size: 11px;
}
.card-note {
  margin-top: $spacing-sm;
  color: #8a5a14;
  font-size: 12px;
}
.card-actions {
  margin-top: $spacing-md;
}
.card-file-input {
  display: none;
}
.card-passed {
  margin-top: $spacing-sm;
  color: #25663f;
  font-size: 12px;
}
.claim-disabled {
  opacity: 0.7;
}
.claim-gate {
  margin-bottom: $spacing-sm;
  color: #8a5a14;
  font-size: 12px;
}
.search-row {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
}
.search-error {
  margin-top: $spacing-sm;
  color: #b4442e;
  font-size: 12px;
}
.candidate-list {
  display: grid;
  gap: $spacing-sm;
  margin-top: $spacing-md;
}
.search-empty,
.history-empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
.search-note {
  color: #8a5a14;
  font-size: 12px;
}
.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;
}
.refresh-btn {
  color: $color-primary;
  font-size: 12px;
}
.refresh-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}
.history-list {
  display: grid;
  gap: $spacing-sm;
}
.history-item {
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.history-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}
.history-top strong {
  color: $text-primary;
  font-size: 13px;
}
.history-meta {
  margin-top: 4px;
  color: $text-placeholder;
  font-size: 10px;
}
.history-note {
  margin-top: 6px;
  color: $text-regular;
  font-size: 12px;
}
</style>
