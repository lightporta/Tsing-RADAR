<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import RecruitmentList from '@/components/recruitment/RecruitmentList.vue'
import PublishForm from '@/components/recruitment/PublishForm.vue'
import {
  fetchMyRecruitments,
  withdrawRecruitment,
  type MyRecruitment,
} from '@/api/recruitment'
import { newIdempotencyKey } from '@/api/request'

const mine = ref<MyRecruitment[]>([])
const mineLoading = ref(false)
const withdrawingId = ref<string | null>(null)
const detailVisible = ref(false)
const selectedDetail = ref<MyRecruitment | null>(null)
const publishForm = ref<{ openForEdit: (item: MyRecruitment) => void } | null>(null)
const withdrawIntents = new Map<string, string>()

const statusLabels: Record<string, string> = {
  pending_review: '待审核',
  verified: '已通过',
  rejected: '未通过',
  restricted: '未公开',
  published: '已公开',
  withdrawn: '已撤回',
}

async function loadMine() {
  mineLoading.value = true
  try {
    mine.value = (await fetchMyRecruitments()).data
  } finally {
    mineLoading.value = false
  }
}

function edit(item: MyRecruitment) {
  detailVisible.value = false
  publishForm.value?.openForEdit(item)
}

function viewDetail(item: MyRecruitment) {
  selectedDetail.value = item
  detailVisible.value = true
}

async function withdraw(item: MyRecruitment) {
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
  if (!withdrawIntents.has(item.recruit_id)) {
    withdrawIntents.set(item.recruit_id, newIdempotencyKey('withdraw-recruitment'))
  }
  try {
    await withdrawRecruitment(item.recruit_id, withdrawIntents.get(item.recruit_id)!)
    withdrawIntents.delete(item.recruit_id)
    detailVisible.value = false
    selectedDetail.value = null
    ElMessage.success('投稿已撤回并停止公开')
    await loadMine()
  } finally {
    withdrawingId.value = null
  }
}

function displayTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

onMounted(loadMine)
</script>

<template>
  <SubPageLayout title="信息平台 · 招募信息">
    <div class="recruitment-view">
      <div class="container">
        <div class="view-head">
          <p class="view-desc">导师与学长学姐发布的实习、科研助理、招生信息</p>
          <PublishForm ref="publishForm" @saved="loadMine" />
        </div>
        <section v-loading="mineLoading" class="mine-panel" aria-labelledby="mine-title">
          <div class="mine-heading">
            <div>
              <h2 id="mine-title">我的投稿</h2>
              <p>可查看完整内容；待审核或未通过投稿可修改后重新送审。</p>
            </div>
            <button type="button" class="refresh-mine" :disabled="mineLoading" @click="loadMine">
              刷新
            </button>
          </div>
          <div v-if="mine.length" class="mine-list">
            <article v-for="item in mine" :key="item.recruit_id" class="mine-item">
              <div class="mine-title-row">
                <div>
                  <strong>{{ item.title }}</strong>
                  <p>提交 {{ displayTime(item.created_at) }} · 更新 {{ displayTime(item.updated_at) }}</p>
                </div>
                <div class="status-row" aria-label="投稿状态">
                  <span class="status-chip">{{ statusLabels[item.review_status] || item.review_status }}</span>
                  <span class="status-chip muted">
                    {{ statusLabels[item.publication_status] || item.publication_status }}
                  </span>
                </div>
              </div>
              <dl class="mine-details">
                <div><dt>类型</dt><dd>{{ item.type }}<span v-if="item.is_urgent"> · 急招</span></dd></div>
                <div><dt>专业板块</dt><dd>{{ item.major }}</dd></div>
                <div><dt>截止日期</dt><dd>{{ item.deadline }}</dd></div>
              </dl>
              <div class="mine-actions">
                <el-button size="small" type="primary" plain @click="viewDetail(item)">
                  查看
                </el-button>
                <el-button
                  v-if="['pending_review', 'rejected'].includes(item.review_status)"
                  size="small"
                  @click="edit(item)"
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
            </article>
          </div>
          <p v-else-if="!mineLoading" class="mine-empty">暂无投稿</p>
        </section>
        <el-dialog
          v-model="detailVisible"
          class="recruitment-detail-dialog"
          title="投稿详情"
          width="min(620px, 92vw)"
          destroy-on-close
        >
          <div v-if="selectedDetail" class="detail-content">
            <div class="detail-status" aria-label="投稿审核与发布状态">
              <span class="status-chip">
                {{ statusLabels[selectedDetail.review_status] || selectedDetail.review_status }}
              </span>
              <span class="status-chip muted">
                {{ statusLabels[selectedDetail.publication_status] || selectedDetail.publication_status }}
              </span>
            </div>
            <dl class="detail-fields">
              <div class="wide"><dt>标题</dt><dd>{{ selectedDetail.title }}</dd></div>
              <div><dt>类型</dt><dd>{{ selectedDetail.type }}</dd></div>
              <div><dt>是否急招</dt><dd>{{ selectedDetail.is_urgent ? '是' : '否' }}</dd></div>
              <div><dt>专业板块</dt><dd>{{ selectedDetail.major }}</dd></div>
              <div><dt>截止日期</dt><dd>{{ selectedDetail.deadline }}</dd></div>
              <div><dt>提交时间</dt><dd>{{ displayTime(selectedDetail.created_at) }}</dd></div>
              <div><dt>更新时间</dt><dd>{{ displayTime(selectedDetail.updated_at) }}</dd></div>
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
              @click="edit(selectedDetail)"
            >
              修改并重新送审
            </el-button>
            <el-button
              v-if="selectedDetail && selectedDetail.review_status !== 'withdrawn'"
              type="danger"
              plain
              :loading="withdrawingId === selectedDetail.recruit_id"
              @click="withdraw(selectedDetail)"
            >
              撤回
            </el-button>
          </template>
        </el-dialog>
        <RecruitmentList />
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.recruitment-view { padding: $spacing-xl $spacing-lg; }
.container { max-width: 1200px; margin: 0 auto; }
.view-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: $spacing-lg;
}
.view-desc { font-size: 13px; color: $text-secondary; }
.mine-panel {
  margin-bottom: $spacing-xl;
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.mine-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;
}
.mine-heading h2 { color: $text-primary; font-size: 15px; }
.mine-heading p { margin-top: 4px; color: $text-placeholder; font-size: 11px; }
.refresh-mine { color: $color-primary; font-size: 12px; }
.refresh-mine:disabled { opacity: 0.5; cursor: wait; }
.mine-list { display: grid; gap: $spacing-md; }
.mine-item {
  display: grid;
  gap: $spacing-md;
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.mine-title-row,
.status-row,
.mine-actions {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}
.mine-title-row { justify-content: space-between; }
.mine-title-row strong { color: $text-primary; font-size: 13px; }
.mine-title-row p { margin-top: 3px; color: $text-placeholder; font-size: 10px; }
.status-chip {
  padding: 3px 7px;
  border-radius: 999px;
  color: #8a5a14;
  background: #fff3dc;
  font-size: 10px;
}
.status-chip.muted { color: $text-secondary; background: $color-bg-hover; }
.mine-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px $spacing-md;
}
.mine-details div { min-width: 0; }
.mine-details .wide { grid-column: 1 / -1; }
.mine-details dt { color: $text-placeholder; font-size: 10px; }
.mine-details dd { margin-top: 2px; color: $text-regular; font-size: 12px; line-height: 1.6; white-space: pre-wrap; }
.mine-actions { justify-content: flex-end; }
.mine-empty { padding: $spacing-lg; text-align: center; color: $text-placeholder; font-size: 12px; }
.detail-content { display: grid; gap: $spacing-md; }
.detail-status { display: flex; gap: $spacing-sm; }
.detail-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: $spacing-md;
}
.detail-fields .wide { grid-column: 1 / -1; }
.detail-fields dt { color: $text-placeholder; font-size: 11px; }
.detail-fields dd { margin-top: 4px; color: $text-regular; font-size: 13px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.detail-fields .review-reason { padding: 10px; border-radius: 8px; background: #fff7e8; }
:deep(.recruitment-detail-dialog) { border-radius: 14px; }

@media (max-width: $bp-tablet) {
  .recruitment-view { padding: $spacing-md; }
  .view-head { flex-direction: column; align-items: flex-start; gap: $spacing-sm; }
  .mine-title-row { align-items: flex-start; flex-direction: column; }
  .mine-details { grid-template-columns: 1fr; }
  .mine-details .wide { grid-column: auto; }
  .mine-actions { justify-content: flex-start; }
  .detail-fields { grid-template-columns: 1fr; }
  .detail-fields .wide { grid-column: auto; }
}
</style>
