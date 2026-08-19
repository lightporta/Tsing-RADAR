<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/useChatStore'
import { getActivityQuestion, suggestDirections } from '@/api/interview'
import type { ActivityOption, DirectionCandidate } from '@/types/interview'

// =====================================================================
// 兴趣探索卡片（修改说明 §6）
// 面向研究方向不明确的学生：活动兴趣多选题（O*NET Interest Profiler
// 思路改写为研究场景）→ 确定性映射生成候选研究方向（含详细介绍）→
// 单选/多选写回画像，继续推荐导师。GLM 不参与、不改变结果。
// =====================================================================

const chatStore = useChatStore()

const expanded = ref(false)
const questionPrompt = ref('')
const options = ref<ActivityOption[]>([])
const selectedActivities = ref<string[]>([])
const candidates = ref<DirectionCandidate[]>([])
const candidatesHint = ref('')
const selectedDirections = ref<string[]>([])
const loadingSuggestions = ref(false)
const applying = ref(false)

// 显示时机：访谈进行中、研究方向尚未填写（画像缺 research_interests）
const researchInterestsEmpty = computed(
  () => !(chatStore.profile?.research_interests ?? []).length,
)
const canShow = computed(
  () =>
    researchInterestsEmpty.value &&
    chatStore.interviewStatus === 'in_progress' &&
    !chatStore.streaming &&
    !chatStore.needsConfirmation,
)

onMounted(async () => {
  try {
    const question = await getActivityQuestion()
    questionPrompt.value = question.prompt
    options.value = question.options
  } catch {
    // 题目拉取失败不阻塞访谈；入口保持收起
  }
})

function toggleExpanded() {
  expanded.value = !expanded.value
  if (expanded.value && !options.value.length) return
}

function toggleActivity(value: string) {
  const index = selectedActivities.value.indexOf(value)
  if (index >= 0) selectedActivities.value.splice(index, 1)
  else selectedActivities.value.push(value)
}

async function generateCandidates() {
  if (!selectedActivities.value.length || loadingSuggestions.value) return
  loadingSuggestions.value = true
  try {
    const result = await suggestDirections([...selectedActivities.value])
    candidates.value = result.candidates
    candidatesHint.value = result.hint
    selectedDirections.value = []
  } catch {
    ElMessage.error('候选方向生成失败，请稍后重试')
  } finally {
    loadingSuggestions.value = false
  }
}

function toggleDirection(key: string) {
  const index = selectedDirections.value.indexOf(key)
  if (index >= 0) selectedDirections.value.splice(index, 1)
  else selectedDirections.value.push(key)
}

async function applySelection() {
  if (!selectedDirections.value.length || applying.value) return
  applying.value = true
  try {
    await chatStore.applyInterestDirections(
      [...selectedDirections.value],
      [...selectedActivities.value],
    )
    ElMessage.success('已写入研究方向，访谈继续')
    expanded.value = false
    candidates.value = []
    selectedDirections.value = []
  } catch {
    ElMessage.error('写入画像失败，画像版本可能已变化，请重试')
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div v-if="canShow" class="interest-exploration">
    <button v-if="!expanded" class="entry-btn" @click="toggleExpanded">
      🧭 还不确定研究方向？先做 1 道活动兴趣选择题
    </button>

    <div v-else class="exploration-card">
      <div class="card-header">
        <span class="card-badge">兴趣探索</span>
        <button class="collapse-btn" aria-label="收起" @click="toggleExpanded">
          收起
        </button>
      </div>

      <p class="card-prompt">{{ questionPrompt }}</p>

      <div class="activity-grid">
        <button
          v-for="opt in options"
          :key="opt.value"
          class="activity-btn"
          :class="{ active: selectedActivities.includes(opt.value) }"
          :title="opt.description"
          @click="toggleActivity(opt.value)"
        >
          <span class="activity-label">{{ opt.label }}</span>
        </button>
      </div>

      <div class="card-actions">
        <button
          class="primary-btn"
          :disabled="!selectedActivities.length || loadingSuggestions"
          @click="generateCandidates"
        >
          {{ loadingSuggestions ? '生成中…' : '看看候选研究方向' }}
        </button>
      </div>

      <div v-if="candidates.length" class="candidates">
        <p class="candidates-hint">{{ candidatesHint }}</p>
        <div
          v-for="candidate in candidates"
          :key="candidate.key"
          class="candidate-item"
          :class="{ active: selectedDirections.includes(candidate.key) }"
          role="checkbox"
          :aria-checked="selectedDirections.includes(candidate.key)"
          tabindex="0"
          @click="toggleDirection(candidate.key)"
          @keydown.enter.prevent="toggleDirection(candidate.key)"
          @keydown.space.prevent="toggleDirection(candidate.key)"
        >
          <div class="candidate-head">
            <span class="candidate-label">{{ candidate.label }}</span>
            <span class="candidate-score">命中 {{ candidate.match_score }} 项活动</span>
          </div>
          <p class="candidate-desc">{{ candidate.description }}</p>
          <div class="candidate-matches">
            <span
              v-for="activity in candidate.matched_activities"
              :key="activity.value"
              class="match-tag"
            >
              {{ activity.label }}
            </span>
          </div>
        </div>
        <div class="card-actions">
          <button
            class="primary-btn"
            :disabled="!selectedDirections.length || applying"
            @click="applySelection"
          >
            {{ applying ? '写入中…' : '选定方向，继续推荐导师' }}
          </button>
        </div>
      </div>
      <p v-else-if="candidatesHint" class="candidates-empty">{{ candidatesHint }}</p>
    </div>
  </div>
</template>

<style scoped lang="scss">
.interest-exploration {
  margin: 0 $spacing-xl $spacing-sm;
}

.entry-btn {
  width: 100%;
  padding: 10px 14px;
  border: 1.5px dashed rgba(103, 194, 58, 0.5);
  border-radius: 10px;
  background: rgba(103, 194, 58, 0.05);
  color: $color-success;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: $color-success;
    background: rgba(103, 194, 58, 0.1);
  }
}

.exploration-card {
  padding: $spacing-md;
  background: rgba(103, 194, 58, 0.04);
  border: 1px solid rgba(103, 194, 58, 0.2);
  border-radius: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-sm;
}

.card-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(103, 194, 58, 0.14);
  color: $color-success;
  font-size: 11px;
  font-weight: 600;
}

.collapse-btn {
  padding: 2px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: $text-secondary;
  font-size: 11px;
  cursor: pointer;

  &:hover {
    color: $color-success;
  }
}

.card-prompt {
  font-size: 13px;
  color: $text-primary;
  line-height: 1.5;
  margin: 0 0 $spacing-sm;
  font-weight: 500;
}

.activity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: $spacing-sm;
}

.activity-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 9px 12px;
  border: 1.5px solid $color-border;
  border-radius: 10px;
  background: $color-bg-card;
  cursor: pointer;
  font-size: 12px;
  color: $text-primary;
  text-align: center;
  line-height: 1.4;
  transition: all 0.2s ease;

  &:hover {
    border-color: $color-success;
  }

  &.active {
    border-color: $color-success;
    background: rgba(103, 194, 58, 0.1);
    color: $color-success;
    font-weight: 600;
  }
}

.card-actions {
  margin-top: $spacing-sm;
  text-align: center;
}

.primary-btn {
  padding: 8px 20px;
  border: none;
  border-radius: 8px;
  background: $color-success;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease;

  &:hover:not(:disabled) {
    opacity: 0.9;
  }

  &:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
}

.candidates {
  margin-top: $spacing-md;
}

.candidates-hint {
  font-size: 11px;
  color: $text-placeholder;
  margin: 0 0 $spacing-sm;
}

.candidates-empty {
  font-size: 11px;
  color: $text-placeholder;
  margin: $spacing-sm 0 0;
}

.candidate-item {
  padding: $spacing-sm $spacing-md;
  border: 1.5px solid $color-border;
  border-radius: 10px;
  margin-bottom: $spacing-sm;
  cursor: pointer;
  transition: all 0.2s ease;
  outline: none;

  &:hover {
    border-color: $color-success;
  }

  &.active {
    border-color: $color-success;
    background: rgba(103, 194, 58, 0.08);
  }

  &:focus-visible {
    box-shadow: 0 0 0 2px rgba(103, 194, 58, 0.35);
  }
}

.candidate-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}

.candidate-label {
  font-size: 13px;
  font-weight: 600;
  color: $text-primary;
}

.candidate-score {
  flex-shrink: 0;
  font-size: 10px;
  color: $color-success;
  background: rgba(103, 194, 58, 0.12);
  padding: 1px 6px;
  border-radius: 4px;
}

.candidate-desc {
  font-size: 11px;
  color: $text-secondary;
  line-height: 1.5;
  margin: 4px 0;
}

.candidate-matches {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.match-tag {
  font-size: 10px;
  color: $text-placeholder;
  background: $color-bg;
  padding: 1px 6px;
  border-radius: 4px;
}

@media (max-width: $bp-tablet) {
  .interest-exploration {
    margin: 0 $spacing-md $spacing-sm;
  }
  .activity-grid {
    grid-template-columns: 1fr;
  }
}
</style>
