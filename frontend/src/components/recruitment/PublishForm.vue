<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  publishRecruitment,
  updateRecruitment,
  type EditableRecruitment,
  type RecruitmentFormData,
} from '@/api/recruitment'
import { publishMentorRecruitment, updateMentorRecruitment } from '@/api/mentor'
import { newIdempotencyKey } from '@/api/request'

// =====================================================================
// 招募发布/编辑表单（F-11 参数化：学生端与导师门户共用同一实现）
// - channel='student' → /api/recruitments；channel='mentor' → /api/mentor/recruitments
// - 立体化扩展字段收进「更多信息（选填）」折叠分组；tags 动态标签输入
// =====================================================================

const props = withDefaults(defineProps<{ channel?: 'student' | 'mentor' }>(), {
  channel: 'student',
})

const dialogVisible = ref(false)
const publishing = ref(false)
const editingId = ref<string | null>(null)
const interacted = ref(false)
const moreOpen = ref(false)
const emit = defineEmits<{ (event: 'saved'): void }>()

const emptyForm = (): RecruitmentFormData => ({
  type: '招生',
  title: '',
  req: '',
  major: '',
  deadline: '',
  is_urgent: false,
  location: '',
  quota: '',
  compensation: '',
  duration: '',
  apply_method: '',
  tags: [],
  advisor_id: '',
})
const form = ref<RecruitmentFormData>(emptyForm())
const types = ['招生', '实习', '科研助理']
const pendingIntent = ref<{ fingerprint: string; key: string } | null>(null)
const tagDraft = ref('')

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
  tagDraft.value = ''
  interacted.value = false
  moreOpen.value = false
  resetIntent()
  dialogVisible.value = true
}

function openForEdit(item: EditableRecruitment) {
  editingId.value = item.recruit_id
  form.value = {
    type: item.type,
    title: item.title,
    req: item.req,
    major: item.major,
    deadline: item.deadline || '',
    is_urgent: item.is_urgent,
    location: item.location || '',
    quota: item.quota || '',
    compensation: item.compensation || '',
    duration: item.duration || '',
    apply_method: item.apply_method || '',
    tags: [...(item.tags || [])],
    advisor_id: item.advisor_id || '',
  }
  tagDraft.value = ''
  interacted.value = false
  moreOpen.value = true
  resetIntent()
  dialogVisible.value = true
}

function addTag() {
  const value = tagDraft.value.trim().slice(0, 20)
  if (!value) return
  const tags = form.value.tags || []
  if (tags.includes(value)) {
    ElMessage.warning('标签已存在')
    return
  }
  if (tags.length >= 10) {
    ElMessage.warning('最多添加 10 个标签')
    return
  }
  form.value.tags = [...tags, value]
  tagDraft.value = ''
  interacted.value = true
}

function removeTag(tag: string) {
  form.value.tags = (form.value.tags || []).filter((item) => item !== tag)
  interacted.value = true
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
    // 可空字段空串统一归一为空（服务端同样归一为 NULL）
    location: form.value.location?.trim() || undefined,
    quota: form.value.quota?.trim() || undefined,
    compensation: form.value.compensation?.trim() || undefined,
    duration: form.value.duration?.trim() || undefined,
    apply_method: form.value.apply_method?.trim() || undefined,
    advisor_id: form.value.advisor_id?.trim() || undefined,
    tags: form.value.tags?.length ? form.value.tags : undefined,
  }
  const fingerprint = JSON.stringify({ recruit_id: editingId.value, ...request })
  if (pendingIntent.value?.fingerprint !== fingerprint) {
    const intent = editingId.value ? 'update-recruitment' : 'create-recruitment'
    pendingIntent.value = {
      fingerprint,
      key: newIdempotencyKey(
        props.channel === 'mentor' ? `mentor-${intent}` : intent,
      ),
    }
  }
  publishing.value = true
  try {
    if (props.channel === 'mentor') {
      if (editingId.value) {
        await updateMentorRecruitment(editingId.value, request, pendingIntent.value.key)
        ElMessage.success('修改已保存并重新进入审核队列')
      } else {
        await publishMentorRecruitment(request, pendingIntent.value.key)
        ElMessage.success('已提交审核；通过前不会公开')
      }
    } else if (editingId.value) {
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

defineExpose({ openForEdit, openNew })
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

        <!-- 立体化扩展：全部选填，折叠收纳 -->
        <div class="more-section">
          <button type="button" class="more-toggle" @click="moreOpen = !moreOpen">
            {{ moreOpen ? '收起' : '更多信息（选填）' }}
            <span class="more-arrow" :class="{ open: moreOpen }">▸</span>
          </button>
          <div v-show="moreOpen" class="more-fields">
            <el-form-item label="地点">
              <el-input v-model="form.location" maxlength="60" placeholder="如：北京·清华科技园" />
            </el-form-item>
            <el-form-item label="名额">
              <el-input v-model="form.quota" maxlength="20" placeholder="如：2 人" />
            </el-form-item>
            <el-form-item label="待遇">
              <el-input v-model="form.compensation" maxlength="60" placeholder="如：按学校助研标准" />
            </el-form-item>
            <el-form-item label="周期">
              <el-input v-model="form.duration" maxlength="40" placeholder="如：6 个月" />
            </el-form-item>
            <el-form-item label="投递方式">
              <el-input
                v-model="form.apply_method"
                maxlength="200"
                placeholder="请引导站内投递，勿填手机号/微信号"
              />
            </el-form-item>
            <el-form-item label="标签">
              <div class="tag-editor">
                <el-tag
                  v-for="tag in form.tags"
                  :key="tag"
                  closable
                  class="tag-chip"
                  @close="removeTag(tag)"
                >
                  {{ tag }}
                </el-tag>
                <el-input
                  v-model="tagDraft"
                  class="tag-input"
                  maxlength="20"
                  placeholder="回车添加标签"
                  @keyup.enter.prevent="addTag"
                />
                <el-button size="small" :disabled="!tagDraft.trim()" @click="addTag">
                  添加
                </el-button>
              </div>
            </el-form-item>
            <el-form-item v-if="channel === 'student'" label="关联导师">
              <el-input
                v-model="form.advisor_id"
                maxlength="20"
                placeholder="选填：导师档案 ID"
              />
            </el-form-item>
          </div>
        </div>
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

.more-section {
  margin-top: $spacing-sm;
  border-top: 1px dashed $color-border-light;
  padding-top: $spacing-sm;
}
.more-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: $color-primary;
  font-size: 12px;
  margin-bottom: $spacing-sm;
}
.more-arrow {
  display: inline-block;
  transition: transform 0.2s ease;
}
.more-arrow.open { transform: rotate(90deg); }
.tag-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: $spacing-sm;
  width: 100%;
}
.tag-chip { flex-shrink: 0; }
.tag-input { flex: 1; min-width: 140px; }
</style>
