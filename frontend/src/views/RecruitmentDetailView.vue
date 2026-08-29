<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import CommentSection from '@/components/recruitment/CommentSection.vue'
import {
  fetchRecruitmentDetail,
  type RecruitmentDetail,
} from '@/api/recruitment'
import {
  createApplication,
  fetchDocuments,
  type PrivateDocument,
} from '@/api/actions'
import type { RecruitmentItem } from '@/types/api'
import { newIdempotencyKey } from '@/api/request'
import { deptColor, displayTime } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'
import { readVersionedLocalData, writeVersionedLocalData } from '@/utils/browserStorage'

// =====================================================================
// 招募详情页（差异化方案 §3.3）：院系色 hero / 状态时间线 / 要求 markdown /
// 快速信息卡 / 发布者卡 / 相关招募 / 评论区（含评价体系导流条）/ 投递收藏
// 深链可分享：/recruitment/:id；未公开/下架/过期一律 404 诚实提示
// =====================================================================

const route = useRoute()
const router = useRouter()
const recruitId = String(route.params.id || '')

const detail = ref<RecruitmentDetail | null>(null)
const loading = ref(false)
const loadError = ref('')
const notFound = ref(false)

// —— 投递 ——
const submitDialogVisible = ref(false)
const documents = ref<PrivateDocument[]>([])
const selectedDocumentId = ref('')
const submitting = ref(false)
const pendingApplication = ref<{ fingerprint: string; key: string } | null>(null)

// —— 收藏（本机存储，统一走 versioned browserStorage 纪律）——
const FAVORITES_KEY = 'tsing-radar:recruitment-favorites'
const favorite = ref(false)

function isFavoriteList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((id) => typeof id === 'string')
}

function loadFavorite() {
  const stored = readVersionedLocalData(FAVORITES_KEY, isFavoriteList)
  favorite.value = Boolean(stored?.includes(recruitId))
}

function toggleFavorite() {
  const stored = readVersionedLocalData(FAVORITES_KEY, isFavoriteList) ?? []
  const next = favorite.value
    ? stored.filter((id) => id !== recruitId)
    : [...stored, recruitId]
  const result = writeVersionedLocalData(FAVORITES_KEY, next)
  if (!result.ok) {
    ElMessage.warning('浏览器本机存储不可用，收藏仅在当前页面有效')
  }
  favorite.value = !favorite.value
  ElMessage.success(favorite.value ? '已收藏（仅保存在本机）' : '已取消收藏')
}

const heroColor = computed(() => deptColor(detail.value?.major || ''))
const heroStyle = computed(() => ({
  background: `linear-gradient(135deg, ${heroColor.value}1f 0%, ${heroColor.value}0a 55%, #ffffff 100%)`,
}))

const typeColors: Record<string, string> = {
  招生: '#409eff',
  实习: '#67c23a',
  科研助理: '#e6a23c',
}

function typeColor(type: string) {
  return typeColors[type] || '#909399'
}

/** 倒计时（环形 SVG 用）：按 30 天窗口估算进度 */
const daysLeft = computed(() => {
  const deadline = detail.value?.deadline
  if (!deadline) return null
  const end = new Date(`${deadline}T23:59:59`)
  if (Number.isNaN(end.getTime())) return null
  return Math.ceil((end.getTime() - Date.now()) / 86_400_000)
})

const countdownText = computed(() => {
  if (daysLeft.value === null) return '长期有效'
  if (daysLeft.value < 0) return '已截止'
  if (daysLeft.value === 0) return '今日截止'
  return `剩 ${daysLeft.value} 天`
})

const countdownHours = computed(() => {
  const deadline = detail.value?.deadline
  if (!deadline) return ''
  const end = new Date(`${deadline}T23:59:59`)
  const hours = Math.max(0, Math.round((end.getTime() - Date.now()) / 3_600_000))
  return `距截止约 ${hours} 小时`
})

/** 环形进度：剩余越少弧越短 */
const ringDash = computed(() => {
  const circumference = 2 * Math.PI * 15.5
  if (daysLeft.value === null || daysLeft.value < 0) return `0 ${circumference}`
  const ratio = Math.min(1, daysLeft.value / 30)
  return `${(circumference * ratio).toFixed(1)} ${circumference}`
})

const ringColor = computed(() => {
  if (daysLeft.value === null) return '#909399'
  if (daysLeft.value < 3) return '#f56c6c'
  if (daysLeft.value < 7) return '#e6a23c'
  return '#409eff'
})

const renderedReq = computed(() => renderMarkdown(detail.value?.req || ''))

/** 快速信息卡：仅展示非空字段（诚实空态） */
const quickFacts = computed(() => {
  const item = detail.value
  if (!item) return []
  return [
    { label: '地点', value: item.location },
    { label: '名额', value: item.quota },
    { label: '待遇', value: item.compensation },
    { label: '周期', value: item.duration },
    { label: '投递方式', value: item.apply_method },
  ].filter((fact) => fact.value)
})

/** 状态时间线：发布 → 过审 → 截止（数据缺失的节点不伪造） */
const timeline = computed(() => {
  const item = detail.value
  if (!item) return []
  const nodes = []
  if (item.created_at) nodes.push({ label: '发布', time: displayTime(item.created_at) })
  if (item.verified_at) nodes.push({ label: '过审', time: displayTime(item.verified_at) })
  nodes.push({ label: '截止', time: item.deadline || '长期有效' })
  return nodes
})

async function loadDetail() {
  loading.value = true
  loadError.value = ''
  notFound.value = false
  try {
    const res = await fetchRecruitmentDetail(recruitId)
    detail.value = res.data
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      notFound.value = true
    } else {
      loadError.value = '详情加载失败，请检查网络后重试'
    }
  } finally {
    loading.value = false
  }
}

function openRelated(item: RecruitmentItem) {
  router.push(`/recruitment/${item.recruit_id}`)
}

async function openSubmit() {
  documents.value = await fetchDocuments()
  selectedDocumentId.value = documents.value[0]?.document_id || ''
  submitDialogVisible.value = true
}

async function confirmSubmit() {
  if (submitting.value) return
  if (!detail.value || !selectedDocumentId.value) {
    ElMessage.warning('请先在个人信息页上传私有 PDF/DOCX')
    return
  }
  submitting.value = true
  try {
    const fingerprint = JSON.stringify({
      recruit_id: detail.value.recruit_id,
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
      detail.value.recruit_id,
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

onMounted(() => {
  loadFavorite()
  loadDetail()
})
</script>

<template>
  <SubPageLayout title="招募详情">
    <div v-loading="loading" class="detail-view">
      <div class="container">
        <!-- 404 / 加载失败 / 正常 三态区分 -->
        <div v-if="notFound" class="state-block">
          <p>招募不存在或未公开</p>
          <span>帖子可能未过审、已下架或已截止。</span>
          <el-button size="small" @click="router.push('/recruitment')">返回招募列表</el-button>
        </div>
        <div v-else-if="loadError" class="state-block">
          <p>{{ loadError }}</p>
          <el-button size="small" @click="loadDetail">重试</el-button>
        </div>

        <template v-else-if="detail">
          <!-- 院系色 hero -->
          <header class="hero" :style="heroStyle">
            <div class="hero-tags">
              <span
                class="type-chip"
                :style="{ background: typeColor(detail.type) + '22', color: typeColor(detail.type) }"
              >
                {{ detail.type }}
              </span>
              <span v-if="detail.is_urgent" class="urgent-chip">⚡ 急招</span>
              <span v-for="tag in detail.tags || []" :key="tag" class="tag-chip">
                # {{ tag }}
              </span>
            </div>
            <h1 class="hero-title">{{ detail.title }}</h1>
            <div class="hero-meta">
              <span class="publisher">
                {{ detail.publisher_type === 'advisor' ? '✓ 认证导师' : detail.publisher_type === 'senior' ? '学长学姐' : '学生' }} ·
                {{ detail.publisher_name }}
              </span>
              <span class="major">📍 {{ detail.major }}</span>
              <!-- SVG 环形倒计时（悬停精确到小时） -->
              <span class="ring-wrap" :title="countdownHours">
                <svg class="ring" viewBox="0 0 36 36" aria-hidden="true">
                  <circle class="ring-bg" cx="18" cy="18" r="15.5" />
                  <circle
                    class="ring-value"
                    cx="18"
                    cy="18"
                    r="15.5"
                    :style="{ strokeDasharray: ringDash, stroke: ringColor }"
                  />
                </svg>
                <span class="countdown-text" :style="{ color: ringColor }">
                  {{ countdownText }}
                </span>
              </span>
            </div>
          </header>

          <!-- 状态时间线 -->
          <ol class="timeline" aria-label="状态时间线">
            <li v-for="(node, index) in timeline" :key="node.label">
              <span class="node-dot" :class="{ last: index === timeline.length - 1 }" />
              <span class="node-label">{{ node.label }}</span>
              <span class="node-time">{{ node.time }}</span>
            </li>
          </ol>

          <!-- 要求与职责 -->
          <section class="panel">
            <h2 class="panel-title">要求与职责</h2>
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div class="markdown-body" v-html="renderedReq" />
          </section>

          <!-- 快速信息卡 -->
          <section v-if="quickFacts.length" class="panel">
            <h2 class="panel-title">快速信息</h2>
            <dl class="quick-facts">
              <div v-for="fact in quickFacts" :key="fact.label">
                <dt>{{ fact.label }}</dt>
                <dd>{{ fact.value }}</dd>
              </div>
            </dl>
          </section>

          <!-- 发布者卡（advisor 非空时） -->
          <section v-if="detail.advisor" class="panel publisher-card">
            <div>
              <h2 class="panel-title">发布者</h2>
              <p class="advisor-line">
                {{ detail.advisor.name }} · {{ detail.advisor.dept }}
              </p>
            </div>
            <el-button size="small" text type="primary" @click="router.push('/mentors')">
              查看导师 →
            </el-button>
          </section>

          <!-- 评价体系导流条：advisor 非空时条件渲染 -->
          <div v-if="detail.advisor" class="rating-banner">
            在这位导师组里待过？为 TA 的六维画像打分 →
            <el-button size="small" text type="primary" @click="router.push('/mentors')">
              前往导师资源库
            </el-button>
          </div>

          <!-- 相关招募 -->
          <section v-if="detail.related.length" class="panel">
            <h2 class="panel-title">相关招募</h2>
            <div class="related-list">
              <div
                v-for="item in detail.related"
                :key="item.recruit_id"
                class="related-card"
                role="link"
                tabindex="0"
                @click="openRelated(item)"
                @keyup.enter="openRelated(item)"
              >
                <span
                  class="type-chip small"
                  :style="{ background: typeColor(item.type) + '22', color: typeColor(item.type) }"
                >
                  {{ item.type }}
                </span>
                <strong>{{ item.title }}</strong>
                <span class="related-meta">{{ item.major }} · 截止 {{ item.deadline }}</span>
              </div>
            </div>
          </section>

          <!-- 评论区 -->
          <CommentSection :recruit-id="recruitId" />

          <!-- 底部操作 -->
          <div class="action-bar">
            <el-button type="primary" :disabled="daysLeft !== null && daysLeft < 0" @click="openSubmit">
              投递简历
            </el-button>
            <el-button :type="favorite ? 'warning' : 'default'" plain @click="toggleFavorite">
              {{ favorite ? '★ 已收藏' : '☆ 收藏' }}
            </el-button>
          </div>
        </template>
      </div>
    </div>

    <!-- 投递确认弹窗 -->
    <el-dialog v-model="submitDialogVisible" title="投递简历" width="min(460px, 92vw)">
      <p v-if="detail">确定将你的简历投递至「<strong>{{ detail.title }}</strong>」？</p>
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
  </SubPageLayout>
</template>

<style scoped lang="scss">
.detail-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
}

.state-block {
  min-height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: $spacing-sm;
  color: $text-placeholder;
  text-align: center;
}

.hero {
  border-radius: 14px;
  padding: $spacing-xl;
  border: 1px solid $color-border-light;
}
.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
  margin-bottom: $spacing-md;
  font-size: 11px;
}
.type-chip {
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: 500;
}
.type-chip.small {
  font-size: 10px;
  padding: 1px 8px;
}
.urgent-chip {
  color: $color-danger;
  font-weight: 600;
}
.tag-chip {
  color: $color-primary;
  background: rgba($color-primary, 0.08);
  padding: 2px 8px;
  border-radius: 999px;
}
.hero-title {
  font-size: 22px;
  font-weight: 700;
  color: $text-primary;
  margin-bottom: $spacing-md;
}
.hero-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: $spacing-md;
  font-size: 12px;
  color: $text-secondary;
}
.ring-wrap {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ring {
  width: 28px;
  height: 28px;
  transform: rotate(-90deg);
}
.ring-bg {
  fill: none;
  stroke: $color-border-light;
  stroke-width: 3;
}
.ring-value {
  fill: none;
  stroke-width: 3;
  stroke-linecap: round;
}
.countdown-text {
  font-size: 12px;
  font-weight: 600;
}

.timeline {
  display: flex;
  gap: $spacing-xl;
  padding: $spacing-md $spacing-lg;
  margin: $spacing-lg 0;
  border: 1px solid $color-border-light;
  border-radius: 10px;
  background: $color-bg-card;
  list-style: none;

  li {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
  }
  .node-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: $color-primary;
  }
  .node-dot.last {
    background: $color-warning;
  }
  .node-label {
    color: $text-primary;
    font-weight: 500;
  }
  .node-time {
    color: $text-placeholder;
  }
}

.panel {
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
  padding: $spacing-lg;
  margin-bottom: $spacing-lg;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: $spacing-md;
}
.markdown-body {
  font-size: 13px;
  color: $text-regular;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.quick-facts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: $spacing-md;
  dt {
    font-size: 11px;
    color: $text-placeholder;
  }
  dd {
    margin-top: 3px;
    font-size: 13px;
    color: $text-regular;
  }
}

.publisher-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  .advisor-line {
    font-size: 14px;
    color: $text-primary;
    font-weight: 500;
  }
}

.rating-banner {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  flex-wrap: wrap;
  padding: $spacing-md $spacing-lg;
  margin-bottom: $spacing-lg;
  border-radius: 10px;
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.08), rgba(64, 158, 255, 0.02));
  font-size: 12px;
  color: $text-regular;
}

.related-list {
  display: grid;
  gap: $spacing-sm;
}
.related-card {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  flex-wrap: wrap;
  padding: $spacing-sm $spacing-md;
  border-radius: 8px;
  background: $color-bg;
  cursor: pointer;
  transition: $transition-base;

  &:hover {
    background: $color-bg-hover;
  }
  strong {
    font-size: 13px;
    color: $text-primary;
  }
  .related-meta {
    margin-left: auto;
    font-size: 11px;
    color: $text-placeholder;
  }
}

.action-bar {
  display: flex;
  gap: $spacing-md;
  margin-top: $spacing-xl;
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

@media (max-width: $bp-tablet) {
  .detail-view {
    padding: $spacing-md;
  }
  .hero {
    padding: $spacing-lg;
  }
  .timeline {
    flex-direction: column;
    gap: $spacing-sm;
  }
  .ring-wrap {
    margin-left: 0;
  }
}
</style>
