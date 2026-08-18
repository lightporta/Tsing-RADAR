<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchRecruitments } from '@/api/recruitment'
import {
  createApplication,
  fetchDocuments,
  type PrivateDocument,
} from '@/api/actions'
import type { RecruitmentItem } from '@/types/api'
import { newIdempotencyKey } from '@/api/request'
import { useUserStore } from '@/stores/useUserStore'

// =====================================================================
// 招募信息列表（分层卡片版，差异化方案 §3.2）
// 类型色带 / 急招标签 / 标签行 / 倒计时胶囊 / 发布者徽章 / 匹配角标
// 已截止帖整卡降饱和并下沉「已截止」分组（数据诚实留存，不删除）
// =====================================================================

const router = useRouter()
const userStore = useUserStore()

const allItems = ref<RecruitmentItem[]>([])
const loading = ref(false)
const loadError = ref('')
const filterUrgent = ref(false)
const submitDialogVisible = ref(false)
const submittingItem = ref<RecruitmentItem | null>(null)
const documents = ref<PrivateDocument[]>([])
const selectedDocumentId = ref('')
const submitting = ref(false)
const pendingApplication = ref<{
  fingerprint: string
  key: string
} | null>(null)

const typeColors: Record<string, string> = {
  招生: '#409eff',
  实习: '#67c23a',
  科研助理: '#e6a23c',
}

function typeColor(type: string) {
  return typeColors[type] || '#909399'
}

/** 截止倒计时：返回剩余天数（负数表示已截止） */
function daysLeft(item: RecruitmentItem): number | null {
  if (!item.deadline) return null
  const deadline = new Date(`${item.deadline}T23:59:59`)
  if (Number.isNaN(deadline.getTime())) return null
  return Math.ceil((deadline.getTime() - Date.now()) / 86_400_000)
}

function isExpired(item: RecruitmentItem) {
  const left = daysLeft(item)
  return left !== null && left < 0
}

/** 倒计时胶囊：<7 天橙、<3 天红；其余中性 */
function countdownClass(item: RecruitmentItem) {
  const left = daysLeft(item)
  if (left === null) return 'neutral'
  if (left < 3) return 'danger'
  if (left < 7) return 'warning'
  return 'neutral'
}

function countdownText(item: RecruitmentItem) {
  const left = daysLeft(item)
  if (left === null) return `截止：${item.deadline}`
  if (left < 0) return '已截止'
  if (left === 0) return '今日截止'
  return `剩 ${left} 天`
}

/** 发布者徽章：认证导师 / 学长学姐 / 学生（服务端 publisher_type 驱动） */
function publisherBadge(item: RecruitmentItem) {
  if (item.publisher_type === 'advisor') return '✓ 认证导师'
  if (item.publisher_type === 'senior') return '学长学姐'
  return '学生'
}

/** 匹配角标：画像兴趣标签与招募 tags/major 概念重合，纯前端计算 */
function matchedTags(item: RecruitmentItem): string[] {
  const interests = userStore.profile.interest_tags || []
  if (!interests.length) return []
  const haystack = [...(item.tags || []), item.major || '', item.title || '']
  return interests.filter((tag) =>
    haystack.some((field) => field && field.includes(tag)),
  )
}

const activeItems = computed(() => {
  const sorted = [...allItems.value].sort((a, b) => {
    if (a.is_urgent !== b.is_urgent) return a.is_urgent ? -1 : 1
    return 0
  })
  const visible = filterUrgent.value
    ? sorted.filter((i) => i.is_urgent)
    : sorted
  return visible.filter((item) => !isExpired(item))
})

const expiredItems = computed(() =>
  (filterUrgent.value
    ? allItems.value.filter((i) => i.is_urgent)
    : allItems.value
  ).filter((item) => isExpired(item)),
)

const urgentCount = computed(() => allItems.value.filter((i) => i.is_urgent).length)

async function loadList() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchRecruitments()
    allItems.value = res.data
  } catch {
    loadError.value = '招募列表加载失败'
  } finally {
    loading.value = false
  }
}

function openDetail(item: RecruitmentItem) {
  router.push(`/recruitment/${item.recruit_id}`)
}

async function openSubmit(item: RecruitmentItem) {
  submittingItem.value = item
  documents.value = await fetchDocuments()
  selectedDocumentId.value = documents.value[0]?.document_id || ''
  submitDialogVisible.value = true
}

async function confirmSubmit() {
  if (submitting.value) return
  if (!submittingItem.value || !selectedDocumentId.value) {
    ElMessage.warning('请先在个人信息页上传私有 PDF/DOCX')
    return
  }
  submitting.value = true
  try {
    const fingerprint = JSON.stringify({
      recruit_id: submittingItem.value.recruit_id,
      document_id: selectedDocumentId.value,
      confirm_in_app_only: true,
    })
    if (pendingApplication.value?.fingerprint !== fingerprint) {
      pendingApplication.value = {
        fingerprint,
        key: newIdempotencyKey('create-application'),
      }
    }
    await createApplication(
      submittingItem.value.recruit_id,
      selectedDocumentId.value,
      pendingApplication.value.key,
    )
    pendingApplication.value = null
    ElMessage.success('已创建站内投递记录；未向第三方发送文件')
    submitDialogVisible.value = false
  } finally {
    submitting.value = false
  }
}

onMounted(loadList)
</script>

<template>
  <div class="recruitment-list">
    <!-- 急需榜横幅 -->
    <div v-if="urgentCount > 0" class="urgent-banner">
      <span class="urgent-icon">🔥</span>
      <span>急需榜：当前有 <strong>{{ urgentCount }}</strong> 条紧急招募</span>
      <el-switch v-model="filterUrgent" active-text="仅看急招" />
    </div>

    <!-- 列表 -->
    <div v-loading="loading" class="list-body">
      <div
        v-for="item in activeItems"
        :key="item.recruit_id"
        class="recruit-card"
        :style="{ borderLeftColor: typeColor(item.type) }"
        role="link"
        tabindex="0"
        @click="openDetail(item)"
        @keyup.enter="openDetail(item)"
      >
        <div class="card-head">
          <span
            class="recruit-type"
            :style="{ background: typeColor(item.type) + '22', color: typeColor(item.type) }"
          >
            {{ item.type }}
          </span>
          <span v-if="item.is_urgent" class="urgent-tag">🔥 急招</span>
          <span class="publisher-badge">{{ publisherBadge(item) }}</span>
          <span class="countdown" :class="countdownClass(item)">
            {{ countdownText(item) }}
          </span>
        </div>
        <h3 class="recruit-title">{{ item.title }}</h3>
        <div v-if="item.tags?.length" class="tag-row">
          <span v-for="tag in item.tags" :key="tag" class="tag-chip"># {{ tag }}</span>
        </div>
        <p class="recruit-req">{{ item.req }}</p>
        <div class="card-foot">
          <span class="major">📍 {{ item.major }}</span>
          <span
            v-if="matchedTags(item).length"
            class="match-badge"
            :title="`与你的兴趣重合：${matchedTags(item).join('、')}`"
          >
            匹配 {{ matchedTags(item).length }} 项
          </span>
          <span v-else-if="!userStore.isProfileComplete" class="match-hint">
            完成访谈查看匹配度
          </span>
          <el-button size="small" type="primary" @click.stop="openSubmit(item)">
            投递简历
          </el-button>
        </div>
      </div>

      <!-- 已截止分组：整卡降饱和，诚实留存 -->
      <template v-if="expiredItems.length">
        <div class="expired-divider">已截止</div>
        <div
          v-for="item in expiredItems"
          :key="item.recruit_id"
          class="recruit-card expired"
          :style="{ borderLeftColor: typeColor(item.type) }"
          role="link"
          tabindex="0"
          @click="openDetail(item)"
          @keyup.enter="openDetail(item)"
        >
          <div class="card-head">
            <span
              class="recruit-type"
              :style="{ background: typeColor(item.type) + '22', color: typeColor(item.type) }"
            >
              {{ item.type }}
            </span>
            <span class="publisher-badge">{{ publisherBadge(item) }}</span>
            <span class="countdown neutral">已截止</span>
          </div>
          <h3 class="recruit-title">{{ item.title }}</h3>
          <div v-if="item.tags?.length" class="tag-row">
            <span v-for="tag in item.tags" :key="tag" class="tag-chip"># {{ tag }}</span>
          </div>
          <p class="recruit-req">{{ item.req }}</p>
          <div class="card-foot">
            <span class="major">📍 {{ item.major }}</span>
          </div>
        </div>
      </template>

      <div v-if="loadError" class="empty">
        <p>{{ loadError }}</p>
        <el-button size="small" @click="loadList">重试</el-button>
      </div>
      <div v-else-if="!loading && !activeItems.length && !expiredItems.length" class="empty">
        <p>暂无通过审核且仍有效的招募信息</p>
        <span>用户投稿在审核前不会出现在这里。</span>
      </div>
    </div>

    <!-- 投递确认弹窗 -->
    <el-dialog v-model="submitDialogVisible" title="投递简历" width="min(460px, 92vw)">
      <p v-if="submittingItem">确定将你的简历投递至「<strong>{{ submittingItem.title }}</strong>」？</p>
      <el-select
        v-model="selectedDocumentId"
        class="document-select"
        placeholder="选择私有简历"
        aria-label="选择私有简历"
      >
        <el-option
          v-for="item in documents"
          :key="item.document_id"
          :label="item.original_name"
          :value="item.document_id"
        />
      </el-select>
      <p v-if="!documents.length" class="dialog-hint">
        暂无私有简历，请先前往个人信息页上传。
      </p>
      <p class="dialog-hint">
        确认后只创建站内状态记录，当前版本不会联系第三方或实际发送文件。
      </p>
      <template #footer>
        <el-button @click="submitDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!selectedDocumentId"
          @click="confirmSubmit"
        >
          确认仅站内记录
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.urgent-banner {
  display: flex;
  align-items: center;
  gap: $spacing-md;
  padding: $spacing-md $spacing-lg;
  background: linear-gradient(90deg, rgba(245, 108, 108, 0.08), rgba(230, 162, 60, 0.08));
  border-radius: 10px;
  margin-bottom: $spacing-lg;
  font-size: 13px;
  color: $text-regular;

  .urgent-icon {
    font-size: 18px;
  }
  strong {
    color: $color-danger;
  }
  .el-switch {
    margin-left: auto;
  }
}

.list-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: $spacing-lg;
}

.recruit-card {
  position: relative;
  background: $color-bg-card;
  border-radius: 10px;
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-left: 4px solid $color-primary;
  transition: $transition-base;
  cursor: pointer;

  &:hover {
    box-shadow: $shadow-card-hover;
    transform: translateY(-2px);
  }
  &.expired {
    opacity: 0.55;
    filter: saturate(0.4);
    cursor: default;

    &:hover {
      transform: none;
      box-shadow: none;
    }
  }
}

.card-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $spacing-sm;
  font-size: 11px;
  margin-bottom: $spacing-sm;
  .recruit-type {
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
  }
  .urgent-tag {
    color: $color-danger;
    animation: urgent-breath 1.6s ease-in-out infinite;
  }
  .publisher-badge {
    color: $text-secondary;
    padding: 2px 8px;
    border-radius: 999px;
    background: $color-bg-hover;
  }
  .countdown {
    margin-left: auto;
    padding: 2px 10px;
    border-radius: 999px;
    font-weight: 500;

    &.neutral {
      color: $text-secondary;
      background: $color-bg-hover;
    }
    &.warning {
      color: #b26a00;
      background: #fdf0d5;
    }
    &.danger {
      color: $color-danger;
      background: #fde2e2;
    }
  }
}

// 急招呼吸动效；prefers-reduced-motion 时静态高亮
@keyframes urgent-breath {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

@media (prefers-reduced-motion: reduce) {
  .urgent-tag {
    animation: none;
    font-weight: 600;
  }
}

.recruit-title {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: $spacing-sm;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: $spacing-sm;
  .tag-chip {
    font-size: 11px;
    color: $color-primary;
    background: rgba($color-primary, 0.08);
    padding: 1px 8px;
    border-radius: 999px;
  }
}

.recruit-req {
  font-size: 12px;
  color: $text-regular;
  line-height: 1.6;
  margin-bottom: $spacing-md;
  min-height: 36px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  .major {
    font-size: 11px;
    color: $text-placeholder;
  }
  .match-badge {
    font-size: 10px;
    color: #b26a00;
    background: #fdf0d5;
    border-radius: 4px;
    padding: 2px 6px;
  }
  .match-hint {
    font-size: 10px;
    color: $text-placeholder;
  }
  .el-button {
    margin-left: auto;
  }
}

.expired-divider {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: $spacing-md;
  color: $text-placeholder;
  font-size: 12px;

  &::before,
  &::after {
    content: '';
    flex: 1;
    border-top: 1px dashed $color-border-light;
  }
}

.empty {
  grid-column: 1 / -1;
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: $spacing-sm;
  text-align: center;
  padding: 60px 20px;
  color: $text-placeholder;
}

.dialog-hint {
  font-size: 12px;
  color: $text-placeholder;
  margin-top: $spacing-sm;
}

.document-select {
  width: 100%;
  margin-top: $spacing-md;
}
</style>
