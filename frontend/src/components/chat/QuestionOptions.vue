<script setup lang="ts">
import { computed, ref } from 'vue'
import { useChatStore } from '@/stores/useChatStore'
import type { InterviewQuestionOption } from '@/types/interview'

// =====================================================================
// 交互式问题选项组件
// 当当前访谈问题是 single_choice 时，在消息区底部渲染可点击选项
// 用户点击选项 = 以该选项的 label 作为消息发送
// 底部保留"自己输入"切换到自由文本输入
// =====================================================================

const chatStore = useChatStore()
const showFreeInput = ref(false)

const question = computed(() => chatStore.currentQuestion)
const isChoice = computed(() =>
  question.value?.answer_type === 'single_choice' &&
  question.value.options.length > 0,
)
const canShow = computed(() =>
  isChoice.value &&
  !chatStore.streaming &&
  !chatStore.needsConfirmation &&
  chatStore.interviewStatus === 'in_progress',
)

const dimensionLabel = computed(() => {
  const labels: Record<string, string> = {
    research_interests: '研究兴趣',
    research_mode: '科研方式',
    mentorship_style: '指导风格',
    career_orientation: '职业取向',
    innovation_risk: '风险偏好',
    hard_constraints: '硬约束',
  }
  return question.value ? labels[question.value.dimension] || question.value.dimension : ''
})

const remainingCount = computed(() => chatStore.profile
  ? (chatStore.currentQuestion ? 1 : 0) + countNullDimensions(chatStore.profile)
  : 6,
)

function countNullDimensions(p: Record<string, unknown>): number {
  const dims = ['research_interests', 'research_mode', 'mentorship_style', 'career_orientation', 'innovation_risk', 'hard_constraints']
  let count = 0
  for (const d of dims) {
    const v = p[d]
    if (v === null || v === undefined || (Array.isArray(v) && v.length === 0)) count++
  }
  return count
}

function selectOption(option: InterviewQuestionOption) {
  if (chatStore.streaming) return
  chatStore.send(option.label)
}

function selectCustom() {
  showFreeInput.value = true
}
</script>

<template>
  <div v-if="canShow" class="question-options">
    <div class="question-header">
      <span class="dimension-badge">{{ dimensionLabel }}</span>
      <span class="remaining">还剩约 {{ remainingCount }} 个问题</span>
    </div>
    <p class="question-prompt">{{ question?.prompt }}</p>
    <div class="options-grid">
      <button
        v-for="opt in question?.options"
        :key="opt.value"
        class="option-btn"
        :disabled="chatStore.streaming"
        @click="selectOption(opt)"
      >
        <span class="option-label">{{ opt.label }}</span>
      </button>
    </div>
    <div class="options-footer">
      <button
        v-if="!showFreeInput"
        class="custom-input-btn"
        @click="selectCustom"
      >
        ✏️ 以上都不符合，我想自己描述
      </button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.question-options {
  margin: $spacing-sm $spacing-xl $spacing-md;
  padding: $spacing-md;
  background: rgba(64, 158, 255, 0.04);
  border: 1px solid rgba(64, 158, 255, 0.15);
  border-radius: 12px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.question-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-sm;
}

.dimension-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(64, 158, 255, 0.12);
  color: $color-primary;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.remaining {
  font-size: 11px;
  color: $text-placeholder;
}

.question-prompt {
  font-size: 14px;
  color: $text-primary;
  line-height: 1.5;
  margin: 0 0 $spacing-md;
  font-weight: 500;
}

.options-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: $spacing-sm;
}

.option-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px 14px;
  border: 1.5px solid $color-border;
  border-radius: 10px;
  background: $color-bg-card;
  cursor: pointer;
  transition: all 0.2s ease;
  min-height: 42px;
  font-size: 13px;
  color: $text-primary;
  text-align: center;
  line-height: 1.4;

  &:hover:not(:disabled) {
    border-color: $color-primary;
    background: rgba(64, 158, 255, 0.06);
    color: $color-primary;
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(64, 158, 255, 0.12);
  }

  &:active:not(:disabled) {
    transform: translateY(0);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.option-label {
  font-weight: 500;
}

.options-footer {
  margin-top: $spacing-sm;
  text-align: center;
}

.custom-input-btn {
  padding: 6px 16px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: $text-secondary;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.2s;

  &:hover {
    color: $color-primary;
    text-decoration: underline;
  }
}

@media (max-width: $bp-tablet) {
  .question-options {
    margin: $spacing-sm $spacing-md;
  }
  .options-grid {
    grid-template-columns: 1fr;
  }
}
</style>
