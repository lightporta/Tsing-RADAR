<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import {
  fetchMyMentorRecruitments,
  publishMentorRecruitment,
  updateMentorRecruitment,
  withdrawMentorRecruitment,
} from '@/api/mentor'
import type { MentorRecruitmentItem } from '@/types/mentor'
import type { RecruitmentFormData } from '@/api/recruitment'

// =====================================================================
// 招募管理页：导师发布/维护招生与实习招募；发布后进入审核队列，
// 通过后并入公开招募列表（与学生侧同表，授权来源标记为导师）。
// =====================================================================

const items = ref<MentorRecruitmentItem[]>([])
const loading = ref(false)
const withdrawingId = ref<string | null>(null)
const detailVisible = ref(false)
const selectedDetail = ref<MentorRecruitmentItem | null>(null)

const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const publishing = ref(false)
const form = ref<RecruitmentFormData>({
  type: '招生',
  title: '',
  req: '',
  major: '',
  deadline: '',
  is_urgent: false,
})
const interacted = ref(false)

const types = ['招生', '实习', '科研助理']

const reviewLabels: Record<string, string> = {
  pending_review: '待审核',
  verified: '已通过',
  rejected: '未通过',
}
const publicationLabels: Record<string, string> = {
  restricted: '未公开',
  published: '已公开',
  withdrawn: '已撤回',
}

const today = () => new Date(new Date().setHours(0, 0, 0, 0))

const formErrors = computed(() => {
  const title = form.value.title.trim()
  const req = form.value.req.trim()
  const major = form.value.major.trim()
  const deadline = form.value.deadline
  return {
    title:
      title.length < 2 ? '标题至少 2 个字' : title.length > 200 ? '标题不能超过 200 字' : '',
    req: req.length < 2 ? '要求至少 2 个字' : req.length > 4000 ? '要求不能超过 4000 字' : '',
    major: !major ? '请填写专业板块' : major.length > 100 ? '专业板块不能超过 100 字' : '',
    deadline: !deadline ? '请选择截止日期' : '',
  }
})

const formValid = computed(() => Object.values(formErrors.value).every((value) => !value))

const dialogTitle = computed(() => (editingId.value ? '编辑并重新送审' : '发布招募信息'))

async function loadItems() {
  loading.value = true
  try {
    items.value = (await fetchMyMentorRecruitments()).data
  } finally {
    loading.value = false
  }
}

function openNew() {
  editingId.value = null
  form.value = { type: '招生', title: '', req: '', major: '', deadline: '', is_urgent: false }
  interacted.value = false
  dialogVisible.value = true
}

function openForEdit(item: MentorRecruitmentItem) {
  editingId.value = item.recruit_id
  form.value = {
    type: item.type,
    title: item.title,
    req: item.req,
    major: item.major,
    deadline: item.deadline || '',
    is_urgent: item.is_urgent,
  }
  interacted.value = false
  dialogVisible.value = true
}

async function submit() {
  if (publishing.value) return
  interacted.value = true
  if (!formValid.value) {
    ElMessage.warning('请先修正表单中的问题')
    return
  }
  publishing.value = true
  try {
    const request: RecruitmentFormData = {
      ...form.value,
      title: form.value.title.trim(),
      req: form.value.req.trim(),
      major: form.value.major.trim(),
    }
    if (editingId.value) {
      await updateMentorRecruitment(editingId.value, request)
      ElMessage.success('修改已保存并重新进入审核队列')
    } else {
      await publishMentorRecruitment(request)
      ElMessage.success('已提交审核；通过前不会公开')
    }
    dialogVisible.value = false
    await loadItems()
  } finally {
    publishing.value = false
  }
}

function viewDetail(item: MentorRecruitmentItem) {
  selectedDetail.value = item
  detailVisible.value = true
}

async function withdraw(item: MentorRecruitmentItem) {
  if (withdrawingId.value) return
  try {
    await ElMessageBox.confirm(
      `撤回投稿「${item.title}」？若已公开，将立即从公开列表下架。`,
      '撤回投稿',
      { confirmButtonText: '确认撤回', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  withdrawingId.value = item.recruit_id
  try {
    await withdrawMentorRecruitment(item.recruit_id)
    detailVisible.value = false
    selectedDetail.value = null
    ElMessage.success('投稿已撤回并停止公开')
    await loadItems()
  } finally {
    withdrawingId.value = null
  }
}

function displayTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

onMounted(loadItems)
</script>

<template>
  <SubPageLayout title="招募管理 · Tsing-RADAR">
    <div class="recruit-view">
      <div class="container">
        <div class="view-head">
          <p class="view-desc">发布招生、实习与科研助理信息；通过审核后对学生公开。</p>
          <el-button type="primary" plain @click="openNew">发布招募</el-button>
        </div>

        <section v-loading="loading" class="list-panel" aria-labelledby="list-title">
          <div class="list-head">
            <h2 id="list-title">我的招募</h2>
            <button type="button" class="refresh-btn" :disabled="loading" @click="loadItems">
              刷新
            </button>
          </div>
          <ul v-if="items.length" class="item-list">
            <li v-for="item in items" :key="item.recruit_id" class="item-card">
              <div class="item-top">
                <div class="item-title-block">
                  <strong>{{ item.title }}</strong>
                  <p>提交 {{ displayTime(item.created_at) }} · 更新 {{ displayTime(item.updated_at) }}</p>
                </div>
                <div class="item-status">
                  <StatusChip
                    :label="reviewLabels[item.review_status] || item.review_status"
                    :tone="item.review_status === 'rejected' ? 'danger' : item.review_status === 'verified' ? 'success' : 'warning'"
                  />
                  <StatusChip
                    :label="publicationLabels[item.publication_status] || item.publication_status"
                    tone="muted"
                  />
                </div>
              </div>
              <dl class="item-details">
                <div><dt>类型</dt><dd>{{ item.type }}<span v-if="item.is_urgent"> · 急招</span></dd></div>
                <div><dt>专业板块</dt><dd>{{ item.major }}</dd></div>
                <div><dt>截止日期</dt><dd>{{ item.deadline || '—' }}</dd></div>
              </dl>
              <div class="item-actions">
                <el-button size="small" type="primary" plain @click="viewDetail(item)">查看</el-button>
                <el-button
                  v-if="['pending_review', 'rejected'].includes(item.review_status)"
                  size="small"
                  @click="openForEdit(item)"
                >
                  {{ item.review_status === 'rejected' ? '修改并重新送审' : '编辑并重新送审' }}
                </el-button>
                <el-button
                  v-if="item.review_status !== 'withdrawn'"
                  size="small"
                  plain
                  type="danger"
                  :loading="withdrawingId === item.recruit_id"
                  @click="withdraw(item)"
                >
                  撤回
                </el-button>
              </div>
            </li>
          </ul>
          <p v-else-if="!loading" class="list-empty">暂无招募</p>
        </section>

        <el-dialog
          v-model="dialogVisible"
          :title="dialogTitle"
          width="min(500px, 92vw)"
          destroy-on-close
        >
          <el-form :model="form" label-width="88px" label-position="left">
            <el-form-item label="类型">
              <el-select v-model="form.type" style="width: 100%">
                <el-option v-for="type in types" :key="type" :value="type" :label="type" />
              </el-select>
            </el-form-item>
            <el-form-item label="标题" :error="interacted ? formErrors.title : ''">
              <el-input v-model="form.title" maxlength="200" @input="interacted = true" />
            </el-form-item>
            <el-form-item label="专业板块" :error="interacted ? formErrors.major : ''">
              <el-input v-model="form.major" maxlength="100" @input="interacted = true" />
            </el-form-item>
            <el-form-item label="截止日期" :error="interacted ? formErrors.deadline : ''">
              <el-date-picker
                v-model="form.deadline"
                type="date"
                value-format="YYYY-MM-DD"
                :disabled-date="(date: Date) => date.getTime() < today().getTime()"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="是否急招">
              <el-switch v-model="form.is_urgent" />
            </el-form-item>
            <el-form-item label="要求与职责" :error="interacted ? formErrors.req : ''">
              <el-input
                v-model="form.req"
                type="textarea"
                :rows="5"
                maxlength="4000"
                show-word-limit
                @input="interacted = true"
              />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="publishing" @click="submit">
              提交审核
            </el-button>
          </template>
        </el-dialog>

        <el-dialog
          v-model="detailVisible"
          title="招募详情"
          width="min(620px, 92vw)"
          destroy-on-close
        >
          <div v-if="selectedDetail" class="detail-content">
            <div class="detail-status">
              <StatusChip
                :label="reviewLabels[selectedDetail.review_status] || selectedDetail.review_status"
                :tone="selectedDetail.review_status === 'rejected' ? 'danger' : selectedDetail.review_status === 'verified' ? 'success' : 'warning'"
              />
              <StatusChip
                :label="publicationLabels[selectedDetail.publication_status] || selectedDetail.publication_status"
                tone="muted"
              />
            </div>
            <dl class="detail-fields">
              <div class="wide"><dt>标题</dt><dd>{{ selectedDetail.title }}</dd></div>
              <div><dt>类型</dt><dd>{{ selectedDetail.type }}</dd></div>
              <div><dt>是否急招</dt><dd>{{ selectedDetail.is_urgent ? '是' : '否' }}</dd></div>
              <div><dt>专业板块</dt><dd>{{ selectedDetail.major }}</dd></div>
              <div><dt>截止日期</dt><dd>{{ selectedDetail.deadline || '—' }}</dd></div>
              <div><dt>提交时间</dt><dd>{{ displayTime(selectedDetail.created_at) }}</dd></div>
              <div class="wide"><dt>要求与职责</dt><dd>{{ selectedDetail.req }}</dd></div>
              <div v-if="selectedDetail.review_reason" class="wide review-reason">
                <dt>最近审核说明</dt><dd>{{ selectedDetail.review_reason }}</dd>
              </div>
            </dl>
          </div>
          <template #footer>
            <el-button @click="detailVisible = false">关闭</el-button>
            <el-button
              v-if="selectedDetail && ['pending_review', 'rejected'].includes(selectedDetail.review_status)"
              @click="openForEdit(selectedDetail)"
            >
              修改并重新送审
            </el-button>
          </template>
        </el-dialog>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.recruit-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
}
.view-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: $spacing-lg;
}
.view-desc {
  color: $text-secondary;
  font-size: 13px;
}
.list-panel {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;
}
.list-head h2 {
  color: $text-primary;
  font-size: 15px;
}
.refresh-btn {
  color: $color-primary;
  font-size: 12px;
}
.refresh-btn:disabled {
  opacity: 0.5;
  cursor: wait;
}
.item-list {
  display: grid;
  gap: $spacing-md;
}
.item-card {
  display: grid;
  gap: $spacing-md;
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.item-top,
.item-status,
.item-actions {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}
.item-top {
  justify-content: space-between;
}
.item-title-block strong {
  color: $text-primary;
  font-size: 13px;
}
.item-title-block p {
  margin-top: 3px;
  color: $text-placeholder;
  font-size: 10px;
}
.item-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px $spacing-md;
}
.item-details dt {
  color: $text-placeholder;
  font-size: 10px;
}
.item-details dd {
  margin-top: 2px;
  color: $text-regular;
  font-size: 12px;
}
.item-actions {
  justify-content: flex-end;
}
.list-empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
.detail-content {
  display: grid;
  gap: $spacing-md;
}
.detail-status {
  display: flex;
  gap: $spacing-sm;
}
.detail-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: $spacing-md;
}
.detail-fields .wide {
  grid-column: 1 / -1;
}
.detail-fields dt {
  color: $text-placeholder;
  font-size: 11px;
}
.detail-fields dd {
  margin-top: 4px;
  color: $text-regular;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.detail-fields .review-reason {
  padding: 10px;
  border-radius: 8px;
  background: #fff7e8;
}

@media (max-width: $bp-tablet) {
  .recruit-view {
    padding: $spacing-md;
  }
  .view-head {
    flex-direction: column;
    align-items: flex-start;
    gap: $spacing-sm;
  }
  .item-top {
    align-items: flex-start;
    flex-direction: column;
  }
  .item-details {
    grid-template-columns: 1fr;
  }
  .item-actions {
    justify-content: flex-start;
  }
  .detail-fields {
    grid-template-columns: 1fr;
  }
  .detail-fields .wide {
    grid-column: auto;
  }
}
</style>
