<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useChatStore } from '@/stores/useChatStore'
import { useUserStore } from '@/stores/useUserStore'
import { fetchStudentDepartments } from '@/api/advisor'
import { TRAITS } from '@/types/advisor'
import type { StudentCategory, StudentProfile } from '@/types/user'

const userStore = useUserStore()
const chatStore = useChatStore()
const advisorStore = useAdvisorStore()
const departments = ref<string[]>([])

const categories: StudentCategory[] = [
  '本科大一', '本科大二', '本科大三', '本科大四',
  '硕士研一', '硕士研二',
  '博士博一', '博士博二', '博士博三',
]
const grades = Array.from({ length: 8 }, (_, index) => `${2026 - index}级`)

function cloneProfile(profile: StudentProfile): StudentProfile {
  return {
    ...profile,
    interest_tags: [...profile.interest_tags],
    weights: { ...profile.weights },
  }
}

function basicSnapshot(profile: StudentProfile) {
  return {
    name: profile.name,
    avatarUrl: profile.avatarUrl,
    email: profile.email,
    dept: profile.dept,
    category: profile.category,
    grade: profile.grade,
    phone: profile.phone,
    gpa: profile.gpa,
    research_experience: profile.research_experience,
  }
}

function preferenceSnapshot(profile: StudentProfile) {
  return {
    research_interest: profile.research_interest,
    interest_tags: [...profile.interest_tags],
    weights: { ...profile.weights },
  }
}

const form = reactive<StudentProfile>(cloneProfile(userStore.profile))
const lastSavedBasic = ref(basicSnapshot(userStore.profile))
const lastSavedPreferences = ref(preferenceSnapshot(userStore.profile))
const newTag = ref('')
const tagInputError = ref('')
const avatarInput = ref<HTMLInputElement | null>(null)
const avatarBusy = ref(false)

const avatarInitial = computed(() => {
  const name = form.name.trim()
  return name ? Array.from(name)[0].toUpperCase() : '我'
})

const emailError = computed(() => {
  const value = form.email.trim()
  return value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? '请输入有效的邮箱地址' : ''
})
const phoneError = computed(() => {
  const value = form.phone?.trim() || ''
  if (!value) return ''
  const digits = value.replace(/\D/g, '')
  return !/^\+?[\d\s()-]+$/.test(value) || digits.length < 7 || digits.length > 15
    ? '请输入 7—15 位有效电话号码，可包含 +、空格和短横线'
    : ''
})
const gpaError = computed(() => {
  const value = form.gpa?.trim() || ''
  if (!value) return ''
  const matched = value.match(/^(\d+(?:\.\d+)?)\s*(?:\/\s*(\d+(?:\.\d+)?))?$/)
  if (!matched) return '请输入如 3.8 或 3.8/4.0 的 GPA'
  const score = Number(matched[1])
  const scale = matched[2] ? Number(matched[2]) : 4
  return scale <= 0 || scale > 100 || score < 0 || score > scale
    ? 'GPA 分数不能超过满分，满分须在 0—100 之间'
    : ''
})
const nameError = computed(() =>
  Array.from(form.name.trim()).length > 50 ? '姓名不能超过 50 个字' : '',
)
const experienceError = computed(() =>
  Array.from(form.research_experience?.trim() || '').length > 2000
    ? '科研经历不能超过 2000 个字'
    : '',
)
const interestError = computed(() =>
  Array.from(form.research_interest?.trim() || '').length > 500
    ? '研究兴趣说明不能超过 500 个字'
    : '',
)
const savedTagError = computed(() => {
  const normalized = new Set<string>()
  for (const tag of form.interest_tags) {
    const trimmed = tag.trim()
    if (!trimmed) return '兴趣标签不能是空白内容'
    if (Array.from(trimmed).length > 20) return `标签“${trimmed.slice(0, 12)}”超过 20 个字`
    const key = trimmed.toLocaleLowerCase('zh-CN')
    if (normalized.has(key)) return `标签“${trimmed}”重复`
    normalized.add(key)
  }
  return ''
})
const basicValid = computed(
  () => !emailError.value && !phoneError.value && !gpaError.value && !nameError.value && !experienceError.value,
)
const preferencesValid = computed(() => !interestError.value && !savedTagError.value)

const AVATAR_MAX_BYTES = 2 * 1024 * 1024
const AVATAR_MAX_EDGE = 384
const AVATAR_MAX_DATA_LENGTH = 600_000
const AVATAR_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

function addTag() {
  const tag = newTag.value.trim()
  if (!tag) {
    tagInputError.value = '请输入兴趣标签，不能只包含空格'
    return
  }
  if (Array.from(tag).length > 20) {
    tagInputError.value = '每个标签最多 20 个字'
    return
  }
  if (form.interest_tags.some((item) => item.trim().toLocaleLowerCase('zh-CN') === tag.toLocaleLowerCase('zh-CN'))) {
    tagInputError.value = '该标签已存在，请勿重复添加'
    return
  }
  form.interest_tags.push(tag)
  newTag.value = ''
  tagInputError.value = ''
}

function removeTag(index: number) {
  form.interest_tags.splice(index, 1)
  tagInputError.value = ''
}

function chooseAvatar() {
  avatarInput.value?.click()
}

function loadImage(url: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('image_decode_failed'))
    image.src = url
  })
}

async function compressAvatar(file: File) {
  const objectUrl = URL.createObjectURL(file)
  try {
    const image = await loadImage(objectUrl)
    const ratio = Math.min(1, AVATAR_MAX_EDGE / Math.max(image.naturalWidth, image.naturalHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('canvas_unavailable')
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const compressed = canvas.toDataURL('image/webp', 0.82)
    if (compressed.length > AVATAR_MAX_DATA_LENGTH) throw new Error('avatar_too_large')
    return compressed
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

async function handleAvatarChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  if (!AVATAR_TYPES.has(file.type)) {
    ElMessage.error('头像仅支持 JPG、PNG 或 WebP 图片')
    return
  }
  if (file.size > AVATAR_MAX_BYTES) {
    ElMessage.error('头像原图不能超过 2 MB')
    return
  }

  avatarBusy.value = true
  try {
    form.avatarUrl = await compressAvatar(file)
  } catch {
    ElMessage.error('头像压缩失败，请选择尺寸更小的图片')
  } finally {
    avatarBusy.value = false
  }
}

function removeAvatar() {
  form.avatarUrl = ''
}

function showStorageResult(result: ReturnType<typeof userStore.saveBasicProfile>, section: string) {
  if (result.ok) ElMessage.success(`${section}已保存到当前浏览器`)
  else ElMessage.error(userStore.storageError)
}

function saveBasic() {
  if (!basicValid.value) {
    ElMessage.error('请先修正基本信息中的格式问题')
    return
  }
  form.name = form.name.trim()
  form.email = form.email.trim()
  form.phone = form.phone?.trim() || ''
  form.gpa = form.gpa?.trim() || ''
  form.research_experience = form.research_experience?.trim() || ''
  const result = userStore.saveBasicProfile(form)
  if (result.ok) lastSavedBasic.value = basicSnapshot(form)
  showStorageResult(result, '基本信息')
}

function restoreBasic() {
  Object.assign(form, basicSnapshot({ ...form, ...lastSavedBasic.value }))
  ElMessage.info('已恢复到上次保存的基本信息')
}

function savePreferences() {
  if (!preferencesValid.value) {
    ElMessage.error(interestError.value || savedTagError.value)
    return
  }
  form.research_interest = form.research_interest?.trim() || ''
  form.interest_tags = form.interest_tags.map((tag) => tag.trim())
  const result = userStore.savePreferenceProfile(form)
  if (result.ok) lastSavedPreferences.value = preferenceSnapshot(form)
  showStorageResult(result, '兴趣与权重')
}

function restorePreferences() {
  const saved = lastSavedPreferences.value
  form.research_interest = saved.research_interest
  form.interest_tags = [...saved.interest_tags]
  form.weights = { ...saved.weights }
  newTag.value = ''
  tagInputError.value = ''
  ElMessage.info('已恢复到上次保存的兴趣与权重')
}

async function clearLocalData() {
  try {
    await ElMessageBox.confirm(
      '将清除本机保存的个人资料、头像和会话历史，并重置当前会话。已上传到私有文档区的文件不会被删除。',
      '清除本机数据？',
      {
        confirmButtonText: '确认清除',
        cancelButtonText: '取消',
        type: 'warning',
        autofocus: true,
      },
    )
  } catch {
    return
  }

  userStore.clearLocalProfile()
  chatStore.clearSavedSessions()
  chatStore.newConversation()
  advisorStore.resetResults()
  const cleared = cloneProfile(userStore.profile)
  Object.assign(form, cleared)
  lastSavedBasic.value = basicSnapshot(cleared)
  lastSavedPreferences.value = preferenceSnapshot(cleared)
  ElMessage.success('本机个人资料和会话历史已清除')
}

onMounted(async () => {
  try {
    const response = await fetchStudentDepartments()
    departments.value = response.data.map((item) => item.name)
  } catch {
    departments.value = form.dept ? [form.dept] : []
  }
})
</script>

<template>
  <div class="profile-form">
    <aside class="privacy-note" aria-label="本机保存说明">
      <strong>本机保存</strong>
      <span>本页“保存”只写入当前浏览器，不建立云端个人档案。清除浏览器网站数据也会删除这些内容。</span>
    </aside>

    <section class="form-section" aria-labelledby="basic-profile-title">
      <h3 id="basic-profile-title" class="section-title">基本信息</h3>
      <div class="avatar-editor">
        <div class="profile-avatar" aria-hidden="true">
          <img v-if="form.avatarUrl" :src="form.avatarUrl" alt="" />
          <span v-else>{{ avatarInitial }}</span>
        </div>
        <div class="avatar-actions">
          <div>
            <el-button :loading="avatarBusy" @click="chooseAvatar">
              {{ form.avatarUrl ? '更换头像' : '上传头像' }}
            </el-button>
            <el-button v-if="form.avatarUrl" @click="removeAvatar">移除头像</el-button>
          </div>
          <p>支持 JPG、PNG、WebP，原图不超过 2 MB；保存前会在本机压缩。</p>
        </div>
        <input
          ref="avatarInput"
          class="avatar-input"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          aria-label="选择头像图片"
          @change="handleAvatarChange"
        />
      </div>

      <el-form :model="form" label-width="80px" label-position="left">
        <el-form-item label="姓名" :error="nameError">
          <el-input v-model="form.name" maxlength="50" show-word-limit placeholder="请输入姓名" :aria-invalid="!!nameError" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="院系">
              <el-select v-model="form.dept" filterable clearable placeholder="请选择院系">
                <el-option v-for="department in departments" :key="department" :label="department" :value="department" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类别">
              <el-select v-model="form.category" clearable placeholder="请选择学生类别">
                <el-option v-for="category in categories" :key="category" :label="category" :value="category" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="年级">
              <el-select v-model="form.grade" clearable placeholder="请选择入学年级">
                <el-option v-for="grade in grades" :key="grade" :label="grade" :value="grade" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="GPA" :error="gpaError">
              <el-input v-model="form.gpa" placeholder="例如：3.8/4.0" :aria-invalid="!!gpaError" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="邮箱" :error="emailError">
              <el-input v-model="form.email" type="email" placeholder="例如：name@tsinghua.edu.cn" :aria-invalid="!!emailError" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="电话" :error="phoneError">
              <el-input v-model="form.phone" type="tel" placeholder="请输入联系电话（可选）" :aria-invalid="!!phoneError" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="科研经历" :error="experienceError">
          <el-input
            v-model="form.research_experience"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="请简要描述参与的科研项目、论文或竞赛经历"
            :aria-invalid="!!experienceError"
          />
        </el-form-item>
      </el-form>
      <div class="section-actions">
        <el-button @click="restoreBasic">恢复已保存</el-button>
        <el-button type="primary" :disabled="!basicValid || avatarBusy" @click="saveBasic">保存基本信息</el-button>
      </div>
    </section>

    <section class="form-section" aria-labelledby="preference-profile-title">
      <h3 id="preference-profile-title" class="section-title">
        兴趣与权重
        <span class="section-hint">作为本机匹配偏好，不生成导师特质事实</span>
      </h3>
      <el-form :model="form" label-width="80px" label-position="left">
        <el-form-item label="兴趣说明" :error="interestError">
          <el-input
            v-model="form.research_interest"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="请描述希望研究的问题、方法或应用方向（可选）"
            :aria-invalid="!!interestError"
          />
        </el-form-item>
      </el-form>

      <div class="tag-input">
        <span class="field-label">兴趣标签</span>
        <div class="tags-display" aria-live="polite">
          <el-tag v-for="(tag, index) in form.interest_tags" :key="tag" closable @close="removeTag(index)">
            {{ tag }}
          </el-tag>
          <span v-if="!form.interest_tags.length" class="empty-tags">暂无标签</span>
        </div>
        <div class="tag-add">
          <el-input
            v-model="newTag"
            size="small"
            maxlength="20"
            show-word-limit
            aria-label="添加研究兴趣标签，最多二十个字"
            :aria-invalid="!!tagInputError"
            placeholder="输入兴趣标签，最多 20 个字"
            @input="tagInputError = ''"
            @keydown.enter.prevent="addTag"
          />
          <el-button size="small" @click="addTag">添加标签</el-button>
        </div>
        <p v-if="tagInputError || savedTagError" class="field-error" role="alert">
          {{ tagInputError || savedTagError }}
        </p>
      </div>

      <div class="weight-sliders" aria-label="六维需求权重">
        <div v-for="trait in TRAITS" :key="trait.key" class="slider-item">
          <div class="slider-head">
            <span class="slider-label">{{ trait.label }}</span>
            <output class="slider-value">{{ form.weights[trait.key] }}</output>
          </div>
          <el-slider
            v-model="form.weights[trait.key]"
            :min="0"
            :max="100"
            :show-tooltip="false"
            :aria-label="`${trait.label}权重`"
          />
          <p class="slider-desc">{{ trait.description }}</p>
        </div>
      </div>

      <div class="section-actions">
        <el-button @click="restorePreferences">恢复已保存</el-button>
        <el-button type="primary" :disabled="!preferencesValid" @click="savePreferences">保存兴趣与权重</el-button>
      </div>
    </section>

    <section class="local-data-actions" aria-labelledby="local-data-title">
      <div>
        <h3 id="local-data-title">本机数据管理</h3>
        <p>清除个人资料、压缩头像和最近会话；不会删除已上传到私有文档区的文件。</p>
      </div>
      <el-button type="danger" plain @click="clearLocalData">清除本机数据</el-button>
    </section>
  </div>
</template>

<style scoped lang="scss">
.profile-form {
  max-width: 800px;
  margin: 0 auto;
}

.privacy-note {
  display: flex;
  gap: $spacing-sm;
  margin-bottom: $spacing-lg;
  padding: $spacing-md $spacing-lg;
  border: 1px solid rgba(64, 158, 255, 0.2);
  border-radius: 9px;
  color: $text-secondary;
  background: rgba(64, 158, 255, 0.06);
  font-size: 12px;
  line-height: 1.6;

  strong {
    flex: 0 0 auto;
    color: $color-primary;
  }
}

.form-section {
  margin-bottom: $spacing-lg;
  padding: $spacing-xl;
  border-radius: 10px;
  background: $color-bg-card;
  box-shadow: $shadow-card;
}

.avatar-editor {
  display: flex;
  align-items: center;
  gap: $spacing-lg;
  margin-bottom: $spacing-xl;
}

.profile-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  overflow: hidden;
  border-radius: 50%;
  color: #fff;
  background: $color-accent;
  font-size: 24px;
  font-weight: 600;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}

.avatar-actions {
  display: grid;
  gap: $spacing-sm;

  p {
    color: $text-placeholder;
    font-size: 12px;
  }
}

.avatar-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  border: 0;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.section-title {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  margin-bottom: $spacing-lg;
  color: $text-primary;
  font-size: 15px;
  font-weight: 600;

  .section-hint {
    color: $text-placeholder;
    font-size: 12px;
    font-weight: 400;
  }
}

.tag-input {
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
  margin-bottom: $spacing-xl;
}

.field-label {
  color: $text-regular;
  font-size: 14px;
}

.tags-display {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
  min-height: 32px;
  padding: $spacing-sm;
  border-radius: 6px;
  background: $color-bg;

  .empty-tags {
    color: $text-placeholder;
    font-size: 13px;
  }
}

.tag-add {
  display: flex;
  gap: $spacing-sm;
}

.field-error {
  color: $color-danger;
  font-size: 12px;
}

.weight-sliders {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: $spacing-lg;
}

.slider-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 13px;
}

.slider-label {
  color: $text-regular;
}

.slider-value {
  color: $color-accent;
  font-weight: 600;
}

.slider-desc {
  margin-top: 2px;
  color: $text-placeholder;
  font-size: 11px;
  line-height: 1.4;
}

.section-actions {
  display: flex;
  justify-content: flex-end;
  gap: $spacing-sm;
  margin-top: $spacing-xl;
  padding-top: $spacing-md;
  border-top: 1px solid $color-border-light;
}

.local-data-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-lg;
  padding: $spacing-lg;
  border: 1px solid rgba(245, 108, 108, 0.25);
  border-radius: 10px;
  background: rgba(245, 108, 108, 0.04);

  h3 {
    color: $text-primary;
    font-size: 14px;
  }

  p {
    margin-top: 4px;
    color: $text-secondary;
    font-size: 12px;
  }
}

@media (max-width: $bp-tablet) {
  :deep(.el-col-12) {
    flex: 0 0 100%;
    max-width: 100%;
  }

  .weight-sliders {
    grid-template-columns: 1fr;
  }

  .form-section {
    padding: $spacing-lg;
  }

  .privacy-note,
  .local-data-actions {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
