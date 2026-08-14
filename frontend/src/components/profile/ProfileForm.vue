<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/useUserStore'
import { fetchDepartments } from '@/api/advisor'
import { TRAITS } from '@/types/advisor'
import type { StudentCategory } from '@/types/user'
import type { StudentProfile } from '@/types/user'

// =====================================================================
// 个人信息表单（文档 §5.2 / 原 index.html studentPanel 升级）
// 这些字段只用于当前浏览器的展示偏好，不参与身份认证。
// =====================================================================

const userStore = useUserStore()
const departments = ref<string[]>([])

const categories: StudentCategory[] = [
  '本科大一', '本科大二', '本科大三', '本科大四',
  '硕士研一', '硕士研二',
  '博士博一', '博士博二', '博士博三',
]

const grades = Array.from({ length: 8 }, (_, i) => `${2026 - i}级`)

function cloneProfile(profile: StudentProfile): StudentProfile {
  return {
    ...profile,
    interest_tags: [...profile.interest_tags],
    weights: { ...profile.weights },
  }
}

// 深拷贝隔离标签和六维权重，取消编辑时不会污染 store。
const form = reactive<StudentProfile>(cloneProfile(userStore.profile))
const lastSaved = ref<StudentProfile>(cloneProfile(userStore.profile))
const newTag = ref<string>('')
const avatarInput = ref<HTMLInputElement | null>(null)
const avatarInitial = computed(() => {
  const name = form.name.trim()
  return name ? Array.from(name)[0].toUpperCase() : '我'
})

const AVATAR_MAX_BYTES = 2 * 1024 * 1024
const AVATAR_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

// 同步 store → form
watch(
  () => userStore.profile,
  (p) => {
    const snapshot = cloneProfile(p)
    lastSaved.value = snapshot
    Object.assign(form, cloneProfile(snapshot))
  },
  { deep: true },
)

function addTag() {
  const t = newTag.value.trim()
  if (!t) return
  if (form.interest_tags.includes(t)) {
    ElMessage.warning('标签已存在')
    return
  }
  form.interest_tags.push(t)
  newTag.value = ''
}

function removeTag(idx: number) {
  form.interest_tags.splice(idx, 1)
}

function chooseAvatar() {
  avatarInput.value?.click()
}

function handleAvatarChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  if (!AVATAR_TYPES.has(file.type)) {
    ElMessage.error('头像仅支持 JPG、PNG 或 WebP 图片')
    return
  }
  if (file.size > AVATAR_MAX_BYTES) {
    ElMessage.error('头像图片不能超过 2 MB')
    return
  }

  const reader = new FileReader()
  reader.onload = () => {
    if (typeof reader.result === 'string') form.avatarUrl = reader.result
  }
  reader.onerror = () => ElMessage.error('头像读取失败，请重新选择')
  reader.readAsDataURL(file)
}

function removeAvatar() {
  form.avatarUrl = ''
}

function save() {
  const snapshot = cloneProfile(form)
  userStore.updateProfile(snapshot)
  lastSaved.value = cloneProfile(snapshot)
  ElMessage.success('信息仅保留在当前页面内存，刷新后清除')
}

function reset() {
  Object.assign(form, cloneProfile(lastSaved.value))
}

onMounted(async () => {
  try {
    const response = await fetchDepartments()
    departments.value = response.data.map((item) => item.name)
  } catch {
    departments.value = form.dept ? [form.dept] : []
  }
})
</script>

<template>
  <div class="profile-form">
    <div class="form-section">
      <h3 class="section-title">基本信息</h3>
      <div class="avatar-editor">
        <div class="profile-avatar" aria-hidden="true">
          <img v-if="form.avatarUrl" :src="form.avatarUrl" alt="" />
          <span v-else>{{ avatarInitial }}</span>
        </div>
        <div class="avatar-actions">
          <div>
            <el-button @click="chooseAvatar">
              {{ form.avatarUrl ? '更换头像' : '上传头像' }}
            </el-button>
            <el-button v-if="form.avatarUrl" @click="removeAvatar">移除头像</el-button>
          </div>
          <p>支持 JPG、PNG、WebP，不超过 2 MB；仅当前会话使用</p>
        </div>
        <input
          ref="avatarInput"
          class="avatar-input"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          @change="handleAvatarChange"
        />
      </div>
      <el-form :model="form" label-width="80px" label-position="left">
        <el-row :gutter="16">
          <el-col :span="24">
            <el-form-item label="姓名">
              <el-input v-model="form.name" placeholder="请输入姓名" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="院系">
              <el-select v-model="form.dept" filterable clearable placeholder="选择院系">
                <el-option v-for="d in departments" :key="d" :label="d" :value="d" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类别">
              <el-select v-model="form.category">
                <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="年级">
              <el-select v-model="form.grade">
                <el-option v-for="g in grades" :key="g" :label="g" :value="g" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="GPA">
              <el-input v-model="form.gpa" placeholder="如 3.8/4.0" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="邮箱">
              <el-input v-model="form.email" placeholder="清华邮箱" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="电话">
              <el-input v-model="form.phone" placeholder="仅当前页面内存使用" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="科研经历">
          <el-input
            v-model="form.research_experience"
            type="textarea"
            :rows="2"
            placeholder="简要描述参与的科研项目、论文等"
          />
        </el-form-item>
      </el-form>
    </div>

    <!-- 研究兴趣标签 -->
    <div class="form-section">
      <h3 class="section-title">研究兴趣</h3>
      <div class="tag-input">
        <div class="tags-display">
          <el-tag
            v-for="(t, i) in form.interest_tags"
            :key="i"
            closable
            @close="removeTag(i)"
          >
            {{ t }}
          </el-tag>
          <span v-if="!form.interest_tags.length" class="empty-tags">暂无标签</span>
        </div>
        <div class="tag-add">
          <el-input
            v-model="newTag"
            size="small"
            aria-label="添加研究兴趣标签"
            placeholder="添加兴趣标签"
            @keydown.enter="addTag"
          />
          <el-button size="small" @click="addTag">添加</el-button>
        </div>
      </div>
    </div>

    <!-- 六维权重滑块 -->
    <div class="form-section">
      <h3 class="section-title">
        六维需求权重
        <span class="section-hint">调整你的短板偏好，影响匹配排序</span>
      </h3>
      <div class="weight-sliders">
        <div v-for="t in TRAITS" :key="t.key" class="slider-item">
          <div class="slider-head">
            <span class="slider-label">{{ t.label }}</span>
            <span class="slider-value">{{ form.weights[t.key] }}</span>
          </div>
          <el-slider
            v-model="form.weights[t.key]"
            :min="0"
            :max="100"
            :show-tooltip="false"
          />
          <p class="slider-desc">{{ t.description }}</p>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="form-actions">
      <el-button @click="reset">重置</el-button>
      <el-button type="primary" @click="save">
        <el-icon aria-hidden="true">✓</el-icon>
        保存
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.profile-form {
  max-width: 800px;
  margin: 0 auto;
}

.form-section {
  background: $color-bg-card;
  border-radius: 10px;
  padding: $spacing-xl;
  margin-bottom: $spacing-lg;
  box-shadow: $shadow-card;
}

.avatar-editor {
  display: flex;
  align-items: center;
  gap: $spacing-lg;
  margin-bottom: $spacing-xl;
}

.profile-avatar {
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: $color-accent;
  color: #fff;
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
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: $spacing-lg;
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  .section-hint {
    font-size: 12px;
    font-weight: 400;
    color: $text-placeholder;
  }
}

.tag-input {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}
.tags-display {
  display: flex;
  flex-wrap: wrap;
  gap: $spacing-sm;
  min-height: 32px;
  padding: $spacing-sm;
  background: $color-bg;
  border-radius: 6px;
  .empty-tags {
    color: $text-placeholder;
    font-size: 13px;
  }
}
.tag-add {
  display: flex;
  gap: $spacing-sm;
}

.weight-sliders {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: $spacing-lg;
}
.slider-item {
  .slider-head {
    display: flex;
    justify-content: space-between;
    font-size: 13px;
    margin-bottom: 4px;
    .slider-label {
      color: $text-regular;
    }
    .slider-value {
      color: $color-accent;
      font-weight: 600;
    }
  }
  .slider-desc {
    font-size: 11px;
    color: $text-placeholder;
    margin-top: 2px;
    line-height: 1.4;
  }
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: $spacing-sm;
  padding: $spacing-lg 0;
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
}
</style>
