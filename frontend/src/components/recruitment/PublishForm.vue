<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  publishRecruitment,
  updateRecruitment,
  type MyRecruitment,
  type RecruitmentFormData,
} from '@/api/recruitment'
import { newIdempotencyKey } from '@/api/request'

const dialogVisible = ref(false)
const publishing = ref(false)
const editingId = ref<string | null>(null)
const interacted = ref(false)
const emit = defineEmits<{ (event: 'saved'): void }>()

const emptyForm = (): RecruitmentFormData => ({
  type: '招生',
  title: '',
  req: '',
  major: '',
  deadline: '',
  is_urgent: false,
})
const form = ref<RecruitmentFormData>(emptyForm())
const types = ['招生', '实习', '科研助理']
const pendingIntent = ref<{ fingerprint: string; key: string } | null>(null)

const today = () => new Date(new Date().setHours(0, 0, 0, 0))
const disablePastDates = (date: Date) => date.getTime() < today().getTime()

const errors = computed(() => {
  const title = form.value.title.trim()
  const req = form.value.req.trim()
  const major = form.value.major.trim()
  const deadline = form.value.deadline
  return {
    title: title.length < 2 ? '标题至少 2 个字' : title.length > 200 ? '标题不能超过 200 字' : '',
    req: req.length < 2 ? '要求至少 2 个字' : req.length > 4000 ? '要求不能超过 4000 字' : '',
    major: !major ? '请填写专业板块' : major.length > 100 ? '专业板块不能超过 100 字' : '',
    deadline:
      !deadline
        ? '请选择截止日期'
        : new Date(`${deadline}T00:00:00`).getTime() < today().getTime()
          ? '截止日期不能早于今天'
          : '',
  }
})

const formValid = computed(() => Object.values(errors.value).every((value) => !value))
const dialogTitle = computed(() => (editingId.value ? '编辑并重新送审' : '发布招募信息'))

function resetIntent() {
  pendingIntent.value = null
}

function openNew() {
  editingId.value = null
  form.value = emptyForm()
  interacted.value = false
  resetIntent()
  dialogVisible.value = true
}

function openForEdit(item: MyRecruitment) {
  editingId.value = item.recruit_id
  form.value = {
    type: item.type,
    title: item.title,
    req: item.req,
    major: item.major,
    deadline: item.deadline,
    is_urgent: item.is_urgent,
  }
  interacted.value = false
  resetIntent()
  dialogVisible.value = true
}

async function submit() {
  if (publishing.value) return
  interacted.value = true
  if (!formValid.value) {
    ElMessage.warning('请先修正表单中的问题')
    return
  }
  const request: RecruitmentFormData = {
    ...form.value,
    title: form.value.title.trim(),
    req: form.value.req.trim(),
    major: form.value.major.trim(),
  }
  const fingerprint = JSON.stringify({ recruit_id: editingId.value, ...request })
  if (pendingIntent.value?.fingerprint !== fingerprint) {
    pendingIntent.value = {
      fingerprint,
      key: newIdempotencyKey(editingId.value ? 'update-recruitment' : 'create-recruitment'),
    }
  }
  publishing.value = true
  try {
    if (editingId.value) {
      await updateRecruitment(editingId.value, request, pendingIntent.value.key)
      ElMessage.success('修改已保存并重新进入审核队列')
    } else {
      await publishRecruitment(request, pendingIntent.value.key)
      ElMessage.success('已提交审核；通过前不会公开')
    }
    pendingIntent.value = null
    dialogVisible.value = false
    emit('saved')
  } finally {
    publishing.value = false
  }
}

defineExpose({ openForEdit })
</script>

<template>
  <div class="publish-form">
    <el-button type="primary" plain @click="openNew">
      发布招募
    </el-button>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="min(500px, 92vw)">
      <el-form :model="form" label-width="88px" label-position="left" @input="interacted = true">
        <el-alert
          title="身份由当前私有会话绑定；提交后只进入受限审核队列。"
          type="info"
          :closable="false"
          show-icon
        />
        <el-form-item label="类型">
          <el-select v-model="form.type" aria-label="招募类型">
            <el-option v-for="item in types" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" :error="interacted ? errors.title : ''">
          <el-input v-model="form.title" maxlength="200" show-word-limit aria-label="招募标题" />
        </el-form-item>
        <el-form-item label="要求" :error="interacted ? errors.req : ''">
          <el-input
            v-model="form.req"
            type="textarea"
            :rows="4"
            maxlength="4000"
            show-word-limit
            aria-label="招募要求与职责"
          />
        </el-form-item>
        <el-form-item label="专业板块" :error="interacted ? errors.major : ''">
          <el-input v-model="form.major" maxlength="100" aria-label="专业板块" />
        </el-form-item>
        <el-form-item label="截止日期" :error="interacted ? errors.deadline : ''">
          <el-date-picker
            v-model="form.deadline"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择截止日期"
            :disabled-date="disablePastDates"
            aria-label="截止日期"
          />
        </el-form-item>
        <el-form-item label="急招">
          <el-switch v-model="form.is_urgent" aria-label="是否急招" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="publishing" :disabled="!formValid" @click="submit">
          {{ editingId ? '保存并重新送审' : '提交审核' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.publish-form { display: inline-flex; }
.publish-form :deep(.el-select),
.publish-form :deep(.el-date-editor) { width: 100%; }
</style>
