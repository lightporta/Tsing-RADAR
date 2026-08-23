<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import StatusChip from '@/components/mentor/StatusChip.vue'
import {
  fetchMentorPrivacyStatus,
  fetchMyMentorTakedowns,
  submitMentorTakedown,
  updateMentorVisibility,
} from '@/api/mentor'
import type { MentorPrivacyStatus, MentorTakedownRecord } from '@/types/mentor'
import { REVIEW_STATUS_LABELS, VISIBILITY_FIELD_META } from '@/types/mentor'
import { displayTime } from '@/utils/format'

// =====================================================================
// 隐私控制页：字段展示策略（即时生效，仅导师端/管理端展示层）
// 与档案下架申请（需管理员审批）。
// =====================================================================

const privacy = ref<MentorPrivacyStatus>({
  visibility: {},
  takedown: { active: false, effective_at: null },
})
const takedowns = ref<MentorTakedownRecord[]>([])
const statusLoading = ref(false)
const takedownsLoading = ref(false)
const updating = ref(false)

const takedownVisible = ref(false)
const submitting = ref(false)
const scope = ref<'full' | 'field'>('full')
const reason = ref('')
const fieldName = ref('')
const takedownError = ref('')

const visibilityFields = Object.entries(VISIBILITY_FIELD_META)

async function loadStatus() {
  statusLoading.value = true
  try {
    privacy.value = await fetchMentorPrivacyStatus()
  } finally {
    statusLoading.value = false
  }
}

async function loadTakedowns() {
  takedownsLoading.value = true
  try {
    takedowns.value = (await fetchMyMentorTakedowns()).data
  } finally {
    takedownsLoading.value = false
  }
}

async function toggleField(field: string, visible: boolean) {
  if (updating.value) return
  updating.value = true
  try {
    const result = await updateMentorVisibility({ [field]: visible })
    privacy.value.visibility = result.visibility
    ElMessage.success(visible ? '该字段已恢复展示' : '该字段已隐藏')
  } finally {
    updating.value = false
  }
}

async function submitTakedown() {
  if (submitting.value) return
  if (!reason.value.trim()) {
    takedownError.value = '请填写申请原因'
    return
  }
  if (scope.value === 'field' && !fieldName.value) {
    takedownError.value = '请选择要下架的字段'
    return
  }
  submitting.value = true
  takedownError.value = ''
  try {
    await submitMentorTakedown({
      reason: reason.value.trim(),
      scope: scope.value,
      field_name: scope.value === 'field' ? fieldName.value : undefined,
    })
    ElMessage.success('下架申请已提交，等待管理员审批')
    takedownVisible.value = false
    reason.value = ''
    await loadTakedowns()
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void loadStatus()
  void loadTakedowns()
})
</script>

<template>
  <SubPageLayout title="隐私控制 · Tsing-RADAR">
    <div class="privacy-view">
      <div class="container">
        <section v-loading="statusLoading" class="visibility-panel" aria-labelledby="visibility-title">
          <div class="panel-head">
            <div>
              <h2 id="visibility-title">字段展示策略</h2>
              <p>关闭后该字段对您与管理端隐藏；学生侧展示合并将在二期开放。</p>
            </div>
          </div>
          <div v-if="privacy.takedown.active" class="takedown-banner">
            <strong>档案已整体下架</strong>
            <span>生效时间：{{ displayTime(privacy.takedown.effective_at) }}</span>
          </div>
          <ul v-else class="visibility-list">
            <li v-for="[field, meta] in visibilityFields" :key="field" class="visibility-item">
              <div>
                <strong>{{ meta.label }}</strong>
                <p>{{ field }}</p>
              </div>
              <el-switch
                :model-value="privacy.visibility[field] !== false"
                :disabled="updating"
                @change="(value: string | number | boolean) => toggleField(field, Boolean(value))"
              />
            </li>
          </ul>
        </section>

        <section v-loading="takedownsLoading" class="takedown-panel" aria-labelledby="takedown-title">
          <div class="panel-head">
            <div>
              <h2 id="takedown-title">档案下架</h2>
              <p>整体或按字段申请下架公开档案；需管理员审批后生效。</p>
            </div>
            <el-button type="danger" plain size="small" @click="takedownVisible = true">
              申请下架
            </el-button>
          </div>
          <ul v-if="takedowns.length" class="takedown-list">
            <li v-for="item in takedowns" :key="item.req_id" class="takedown-item">
              <div class="takedown-top">
                <strong>{{ item.scope === 'full' ? '整体下架' : `字段下架：${item.field_name}` }}</strong>
                <StatusChip
                  :label="REVIEW_STATUS_LABELS[item.status] || item.status"
                  :tone="item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'danger' : 'warning'"
                />
              </div>
              <p class="takedown-reason">{{ item.reason }}</p>
              <p class="takedown-meta">
                提交 {{ displayTime(item.created_at) }} · 判定 {{ displayTime(item.decided_at) }}
              </p>
              <p v-if="item.admin_note" class="takedown-note">{{ item.admin_note }}</p>
            </li>
          </ul>
          <p v-else-if="!takedownsLoading" class="takedown-empty">暂无下架申请</p>
        </section>

        <el-dialog
          v-model="takedownVisible"
          title="申请档案下架"
          width="min(480px, 92vw)"
          destroy-on-close
        >
          <el-form label-position="top">
            <el-form-item label="下架范围">
              <el-radio-group v-model="scope">
                <el-radio value="full">整体下架</el-radio>
                <el-radio value="field">仅下架单个字段</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="scope === 'field'" label="选择字段">
              <el-select v-model="fieldName" placeholder="请选择字段" style="width: 100%">
                <el-option
                  v-for="[field, meta] in visibilityFields"
                  :key="field"
                  :value="field"
                  :label="meta.label"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="申请原因" :error="takedownError">
              <el-input
                v-model="reason"
                type="textarea"
                :rows="4"
                maxlength="1000"
                show-word-limit
                placeholder="请说明下架原因（如内容更新、联系方式变更等）"
              />
            </el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="takedownVisible = false">取消</el-button>
            <el-button type="danger" plain :loading="submitting" @click="submitTakedown">
              提交申请
            </el-button>
          </template>
        </el-dialog>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.privacy-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 860px;
  margin: 0 auto;
  display: grid;
  gap: $spacing-lg;
}
.visibility-panel,
.takedown-panel {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: $spacing-md;
  margin-bottom: $spacing-md;
}
.panel-head h2 {
  color: $text-primary;
  font-size: 15px;
}
.panel-head p {
  margin-top: 4px;
  color: $text-secondary;
  font-size: 12px;
}
.takedown-banner {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: $spacing-sm $spacing-md;
  border-radius: 8px;
  background: #fdeeea;
  color: #b4442e;
  font-size: 12px;
}
.visibility-list,
.takedown-list {
  display: grid;
  gap: $spacing-sm;
}
.visibility-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-md;
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.visibility-item strong {
  color: $text-primary;
  font-size: 13px;
}
.visibility-item p {
  margin-top: 2px;
  color: $text-placeholder;
  font-size: 10px;
}
.takedown-item {
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.takedown-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}
.takedown-top strong {
  color: $text-primary;
  font-size: 13px;
}
.takedown-reason {
  margin-top: 6px;
  color: $text-regular;
  font-size: 12px;
  line-height: 1.6;
}
.takedown-meta {
  margin-top: 4px;
  color: $text-placeholder;
  font-size: 10px;
}
.takedown-note {
  margin-top: 6px;
  color: #8a5a14;
  font-size: 12px;
}
.takedown-empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
</style>
