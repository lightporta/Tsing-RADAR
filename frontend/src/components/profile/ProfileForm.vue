<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/useUserStore'
import { DEPARTMENTS } from '@/utils/depts'
import { TRAITS } from '@/types/advisor'
import type { StudentCategory } from '@/types/user'

// =====================================================================
// 个人信息表单（文档 §5.2 / 原 index.html studentPanel 升级）
// 院系 / 年级 / 学号 / 邮箱 / GPA / 科研经历 / 研究兴趣标签 / 六维权重滑块
// =====================================================================

const userStore = useUserStore()

const categories: StudentCategory[] = [
  '本科大一', '本科大二', '本科大三', '本科大四',
  '硕士研一', '硕士研二',
  '博士博一', '博士博二', '博士博三',
]

const grades = Array.from({ length: 8 }, (_, i) => `${2026 - i}级`)

// 本地表单副本（编辑时不直接改 store，保存时才提交）
const form = reactive({ ...userStore.profile })
const newTag = ref<string>('')

// 同步 store → form
watch(
  () => userStore.profile,
  (p) => Object.assign(form, p),
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
  userStore.updateProfile({ ...form })
  userStore.persist()
  ElMessage.success('个人信息已保存')
}

function reset() {
  Object.assign(form, userStore.profile)
}
</script>

<template>
  <div class="profile-form">
    <div class="form-section">
      <h3 class="section-title">基本信息</h3>
      <el-form :model="form" label-width="80px" label-position="left">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="姓名">
              <el-input v-model="form.name" placeholder="请输入姓名" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="学号">
              <el-input v-model="form.student_id" placeholder="清华学号" />
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
              <el-input v-model="form.phone" placeholder="加密存储" />
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
        <el-icon><Check /></el-icon>
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
  .weight-sliders {
    grid-template-columns: 1fr;
  }
  .form-section {
    padding: $spacing-lg;
  }
}
</style>
