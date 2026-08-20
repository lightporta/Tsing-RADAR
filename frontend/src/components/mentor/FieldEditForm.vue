<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { SELF_CLAIM_FIELD_META } from '@/types/mentor'
import { submitMentorFieldEdit } from '@/api/mentor'

// =====================================================================
// 字段级编辑表单：选择字段 → 填写新内容 → 提交审批；
// 同一字段存在待审批申请时后端会拒绝（409）。
// =====================================================================

const emit = defineEmits<{ (e: 'saved'): void }>()

const fieldName = ref('')
const newValue = ref('')
const interacted = ref(false)
const submitting = ref(false)

const fieldOptions = Object.entries(SELF_CLAIM_FIELD_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

const currentMeta = computed(
  () => SELF_CLAIM_FIELD_META[fieldName.value] || null,
)

const newValueError = computed(() => {
  const value = newValue.value.trim()
  if (!value) return '请填写新内容'
  if (value.length > 2000) return '内容不能超过 2000 字'
  return ''
})

async function submit() {
  if (submitting.value) return
  interacted.value = true
  if (!fieldName.value) {
    ElMessage.warning('请选择要编辑的字段')
    return
  }
  if (newValueError.value) {
    ElMessage.warning(newValueError.value)
    return
  }
  submitting.value = true
  try {
    await submitMentorFieldEdit(fieldName.value, newValue.value.trim())
    ElMessage.success('已提交编辑申请，等待管理员审批')
    newValue.value = ''
    fieldName.value = ''
    interacted.value = false
    emit('saved')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="field-edit-form">
    <el-form label-position="top">
      <el-form-item label="选择字段">
        <el-select v-model="fieldName" placeholder="请选择要编辑的字段" style="width: 100%">
          <el-option
            v-for="option in fieldOptions"
            :key="option.value"
            :value="option.value"
            :label="option.label"
          />
        </el-select>
      </el-form-item>
      <el-form-item v-if="currentMeta" :label="currentMeta.label">
        <el-input
          v-model="newValue"
          type="textarea"
          :rows="5"
          maxlength="2000"
          show-word-limit
          :placeholder="currentMeta.placeholder"
          @input="interacted = true"
        />
        <p v-if="interacted && newValueError" class="field-error">
          {{ newValueError }}
        </p>
      </el-form-item>
      <p v-else class="field-hint">选择字段后填写内容；提交后需管理员审批通过才会生效。</p>
    </el-form>
    <el-button type="primary" plain :loading="submitting" @click="submit">
      提交编辑申请
    </el-button>
  </div>
</template>

<style scoped lang="scss">
.field-edit-form {
  display: grid;
  gap: $spacing-md;
}
.field-hint {
  color: $text-placeholder;
  font-size: 12px;
}
.field-error {
  margin-top: 6px;
  color: #b4442e;
  font-size: 12px;
}
</style>
