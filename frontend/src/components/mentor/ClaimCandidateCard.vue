<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { MentorCandidate } from '@/types/mentor'
import { submitMentorClaim } from '@/api/mentor'

// =====================================================================
// 认领候选卡片：展示公开档案要点，认领时带上候选身份信息；
// 唯一候选自动绑定，重名候选进入人工审核。
// =====================================================================

const props = defineProps<{ candidate: MentorCandidate }>()
const emit = defineEmits<{
  (e: 'claimed'): void
  (e: 'pending'): void
}>()

const claiming = ref(false)

async function claim() {
  if (claiming.value) return
  claiming.value = true
  try {
    const result = await submitMentorClaim({
      candidate_id: props.candidate.advisor_id,
      name: props.candidate.name,
      department: props.candidate.dept,
    })
    if (result.status === 'claimed') {
      ElMessage.success('认领成功，已绑定该档案')
      emit('claimed')
    } else {
      ElMessage.info('已提交认领申请，等待管理员人工审核')
      emit('pending')
    }
  } finally {
    claiming.value = false
  }
}
</script>

<template>
  <article class="candidate-card">
    <div class="candidate-main">
      <strong class="candidate-name">{{ candidate.name }}</strong>
      <span class="candidate-dept">{{ candidate.dept }}</span>
      <span v-if="candidate.title" class="candidate-title">{{ candidate.title }}</span>
      <span class="candidate-id">{{ candidate.advisor_id }}</span>
    </div>
    <el-button
      type="primary"
      plain
      size="small"
      :loading="claiming"
      @click="claim"
    >
      认领此档案
    </el-button>
  </article>
</template>

<style scoped lang="scss">
.candidate-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-md;
  padding: $spacing-md;
  border: 1px solid $color-border-light;
  border-radius: 10px;
  background: $color-bg;
}
.candidate-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $spacing-sm;
  min-width: 0;
}
.candidate-name {
  color: $text-primary;
  font-size: 14px;
}
.candidate-dept,
.candidate-title {
  color: $text-regular;
  font-size: 12px;
}
.candidate-id {
  color: $text-placeholder;
  font-size: 11px;
}

@media (max-width: $bp-tablet) {
  .candidate-card {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
