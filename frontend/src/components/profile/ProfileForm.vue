<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/useUserStore'
import { DEPARTMENTS } from '@/utils/depts'
import type { StudentCategory, StudentProfile } from '@/types/user'

// =====================================================================
// 个人信息表单（文档 §5.2 / 原 index.html studentPanel 升级）
// 简历资料只保存在当前浏览器内存；匹配偏好由服务端访谈画像管理。
// =====================================================================

const userStore = useUserStore()

const categories: StudentCategory[] = [
  '本科大一', '本科大二', '本科大三', '本科大四',
  '硕士研一', '硕士研二',
  '博士博一', '博士博二', '博士博三',
]

const grades = Array.from({ length: 8 }, (_, i) => `${2026 - i}级`)

// 本地表单副本（编辑时不直接改 store，保存时才提交）
function copyProfile(profile: StudentProfile) {
  return { ...profile, interest_tags: [...profile.interest_tags], weights: { ...profile.weights } }
}
const form = reactive(copyProfile(userStore.profile))
const newTag = ref<string>('')

// 同步 store → form
watch(
  () => userStore.profile,
  (p) => Object.assign(form, copyProfile(p)),
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

function save() {
  userStore.updateProfile(copyProfile(form))
  ElMessage.success('简历资料已保存到当前浏览器内存，刷新后清除')
}

function reset() {
  Object.assign(form, copyProfile(userStore.profile))
}
</script>

<template>
  <div class="profile-form">
    <el-alert
      class="profile-notice"
      type="info"
      :closable="false"
      show-icon
      title="本页保存简历资料，刷新后清除。保存后用于下方文档生成；匹配偏好请在首页访谈画像中编辑。"
    />
    <div class="form-section">
      <h3 class="section-title">简历基本资料</h3>
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
              <el-select v-model="form.dept" filterable placeholder="选择院系">
                <el-option v-for="d in DEPARTMENTS" :key="d" :label="d" :value="d" />
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
      <h3 class="section-title">简历研究兴趣<span class="section-hint">仅用于简历排版</span></h3>
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

    <!-- 操作按钮 -->
    <div class="form-actions">
      <el-button @click="reset">重置</el-button>
      <el-button type="primary" @click="save">
        <el-icon aria-hidden="true">✓</el-icon>
        保存简历资料
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.profile-form {
  max-width: 800px;
  margin: 0 auto;
}

.profile-notice {
  margin-bottom: $spacing-lg;
}

.form-section {
  background: $color-bg-card;
  border-radius: 10px;
  padding: $spacing-xl;
  margin-bottom: $spacing-lg;
  box-shadow: $shadow-card;
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
  .form-section {
    padding: $spacing-lg;
  }
}
</style>
