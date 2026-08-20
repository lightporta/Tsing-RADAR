<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { TRAITS } from '@/types/advisor'
import type { PeriodInGroup, TraitKey } from '@/types/advisor'
import { submitRating, myRatings } from '@/api/rating'
import { newIdempotencyKey } from '@/api/request'
import { useRatingSummary } from '@/composables/useRatingSummary'

// =====================================================================
// 学生评价提交面板（M1 纯分数）
// 六维星条（1-5）+ 在组时长下拉 + 提交（loading / 已提交态 / 错误提示）
// 隐私：匿名提交，导师与他人无法看到打分人身份
// =====================================================================

const props = defineProps<{ advisorId: string }>()
const emit = defineEmits<{ submitted: [] }>()

const { ensureRatingSummary, invalidateRatingSummary } = useRatingSummary()

// 0 表示该维尚未选择
const scores = reactive<Record<TraitKey, number>>({
  acumen: 0,
  network: 0,
  mentorship: 0,
  tolerance: 0,
  funding: 0,
  efficiency: 0,
})

const PERIOD_OPTIONS: Array<{ value: PeriodInGroup; label: string }> = [
  { value: '0.5y', label: '半年以内' },
  { value: '0.5-2y', label: '半年到两年' },
  { value: '2y+', label: '两年以上' },
  { value: 'outside', label: '组外（旁听 / 合作等）' },
]

const SCORE_WORDS: Record<number, string> = {
  1: '很差',
  2: '较差',
  3: '一般',
  4: '较好',
  5: '很好',
}

const period = ref<PeriodInGroup | ''>('')
const submitting = ref(false)
const submitted = ref(false)
const errorMessage = ref('')
// 每次用户意图生成一个高熵键；失败后手动重试复用同一键
const pendingKey = ref<string | null>(null)

const allScored = computed(() =>
  TRAITS.every((t) => scores[t.key] >= 1 && scores[t.key] <= 5),
)

function scoreWord(value: number): string {
  return value >= 1 ? SCORE_WORDS[value] : '未评分'
}

onMounted(async () => {
  // 已评价过该导师则直接展示已提交态（服务端仍以唯一约束兜底）
  try {
    const mine = await myRatings()
    if (mine.data.some((item) => item.advisor_id === props.advisorId)) {
      submitted.value = true
    }
  } catch {
    // 会话未就绪等场景静默失败，不影响面板展示
  }
})

async function onSubmit() {
  if (!allScored.value || submitting.value) return
  submitting.value = true
  errorMessage.value = ''
  if (!pendingKey.value) pendingKey.value = newIdempotencyKey('rating')
  try {
    await submitRating(
      props.advisorId,
      {
        scores: { ...scores },
        period_in_group: period.value || null,
      },
      pendingKey.value,
    )
    submitted.value = true
    pendingKey.value = null
    ElMessage.success('评价已提交，感谢分享')
    // 刷新聚合缓存：摘要与雷达第三系列随即反映新样本
    invalidateRatingSummary(props.advisorId)
    void ensureRatingSummary(props.advisorId)
    emit('submitted')
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 409) {
      // 同人同导师唯一约束：视为已提交
      submitted.value = true
      return
    }
    errorMessage.value = axios.isAxiosError(error)
      ? String(error.response?.data?.detail || '提交失败，请稍后重试')
      : '提交失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="rating-panel">
    <template v-if="!submitted">
      <p class="panel-tip">
        匿名评价：导师与他人无法看到您的身份，请基于真实接触为六个维度打分（1-5 星）。
      </p>
      <div class="trait-rate-list">
        <div v-for="trait in TRAITS" :key="trait.key" class="trait-rate-row">
          <div class="trait-rate-head">
            <span class="trait-rate-label">{{ trait.label }}</span>
            <el-rate v-model="scores[trait.key]" :max="5" />
            <span class="trait-rate-word" :class="{ dim: scores[trait.key] === 0 }">
              {{ scoreWord(scores[trait.key]) }}
            </span>
          </div>
          <p class="trait-rate-desc">{{ trait.description }}</p>
        </div>
      </div>
      <div class="panel-footer">
        <el-select
          v-model="period"
          placeholder="在组时长（选填）"
          clearable
          size="small"
          class="period-select"
        >
          <el-option
            v-for="opt in PERIOD_OPTIONS"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-button
          type="primary"
          size="small"
          :loading="submitting"
          :disabled="!allScored"
          @click="onSubmit"
        >
          提交评价
        </el-button>
      </div>
      <p v-if="!allScored" class="panel-hint">请为全部六个维度打分后提交</p>
      <p v-if="errorMessage" class="panel-error">{{ errorMessage }}</p>
    </template>
    <div v-else class="submitted-state">
      ✅ 已提交学生评价，感谢分享（匿名，导师无法看到您的身份）
    </div>
  </div>
</template>

<style scoped lang="scss">
.rating-panel {
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
}

.panel-tip {
  font-size: 11px;
  color: $text-secondary;
  line-height: 1.5;
}

.trait-rate-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: $spacing-sm $spacing-md;
}

.trait-rate-row {
  .trait-rate-head {
    display: flex;
    align-items: center;
    gap: $spacing-sm;
  }
  .trait-rate-label {
    font-size: 12px;
    color: $text-regular;
    flex-shrink: 0;
    width: 60px;
  }
  .trait-rate-word {
    font-size: 11px;
    color: $color-primary;
    flex-shrink: 0;
    &.dim {
      color: $text-placeholder;
    }
  }
  .trait-rate-desc {
    font-size: 10px;
    color: $text-placeholder;
    margin-top: 2px;
    line-height: 1.4;
  }
}

.panel-footer {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  margin-top: 2px;
}

.period-select {
  width: 180px;
}

.panel-hint {
  font-size: 10px;
  color: $text-placeholder;
}

.panel-error {
  font-size: 11px;
  color: $color-danger;
}

.submitted-state {
  padding: $spacing-sm $spacing-md;
  background: rgba(103, 194, 58, 0.08);
  border-radius: 6px;
  font-size: 12px;
  color: #67c23a;
}

@media (max-width: $bp-tablet) {
  .trait-rate-list {
    grid-template-columns: 1fr;
  }
}
</style>
