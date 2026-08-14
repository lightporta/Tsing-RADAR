<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import MiniRadar from '@/components/charts/MiniRadar.vue'
import AdvisorDetail from './AdvisorDetail.vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'
import { useUserStore } from '@/stores/useUserStore'
import { submitFeedback } from '@/api/feedback'
import { deptColor } from '@/utils/format'
import type { MatchedAdvisor } from '@/types/advisor'

// =====================================================================
// 单张导师卡片（文档 §3.4）
// 左：头像 + 姓名 + 院系职称
// 中：研究方向标签 + 契合度百分比
// 右：迷你双轨雷达图
// 点击：选中态高亮 + 触发右栏切换大雷达图
// 二次点击/展开按钮：向下展开详情面板
// =====================================================================

const props = defineProps<{ advisor: MatchedAdvisor; selected?: boolean }>()

const deptColorAvatar = computed(() => deptColor(props.advisor.dept) + '22')

const advisorStore = useAdvisorStore()
const userStore = useUserStore()
const router = useRouter()
const expanded = ref(false)
const feedbackGiven = ref<1 | -1 | null>(null)
const comparisonKey = computed(() => props.advisor.advisor_id || props.advisor.name)
const compared = computed(() =>
  advisorStore.comparisonIds.includes(comparisonKey.value),
)

function onClick() {
  if (advisorStore.selectedName === props.advisor.name) {
    // 二次点击 = 展开详情
    expanded.value = !expanded.value
  } else {
    advisorStore.selectAdvisor(props.advisor.name)
    expanded.value = false
  }
}

function toggleExpand(e: Event) {
  e.stopPropagation()
  expanded.value = !expanded.value
}

// A5 只进入站内行动准备，不发邮件或联系第三方。
function contactAdvisor() {
  router.push('/profile')
}

function toggleCompare(e: Event) {
  e.stopPropagation()
  if (!compared.value && advisorStore.comparisonIds.length >= 3) {
    ElMessage.warning('最多对比 3 位导师')
    return
  }
  advisorStore.toggleComparison(comparisonKey.value)
}

// 评价反馈
async function giveFeedback(rating: 1 | -1) {
  if (feedbackGiven.value === rating) return
  feedbackGiven.value = rating
  try {
    await submitFeedback({
      advisor_id: props.advisor.name,
      rating,
    })
    ElMessage.success(rating === 1 ? '已点赞' : '已记录反馈')
  } catch {
    // 静默失败（mock 模式无后端）
    feedbackGiven.value = null
  }
}
</script>

<template>
  <article
    class="advisor-card"
    :class="{ selected, expanded }"
    @click="onClick"
  >
    <div class="card-main">
      <!-- 左：头像 + 姓名 + 院系 -->
      <div class="card-left">
        <div class="avatar" :style="{ background: deptColorAvatar }">
          {{ advisor.name.charAt(0) }}
        </div>
        <div class="info">
          <h3 class="name">
            {{ advisor.name }}
            <span v-if="advisor.tags?.includes('院士')" class="badge院士">院士</span>
          </h3>
          <p v-if="advisor.dept" class="dept">{{ advisor.dept }}</p>
          <p v-if="advisor.field" class="field text-ellipsis">{{ advisor.field }}</p>
        </div>
      </div>

      <!-- 中：标签 + 契合度 -->
      <div class="card-middle">
        <div class="tags">
          <span v-for="tag in (advisor.tags || []).slice(0, 3)" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <div class="score-row">
          <div class="synergy">
            <span class="synergy-label">保守排序</span>
            <span class="synergy-value">{{ advisor.score.toFixed(1) }}</span>
          </div>
          <span
            v-if="typeof advisor.popularity === 'number'"
            class="popularity-tag"
            :class="{ hot: advisor.popularity > 60 }"
          >
            {{ advisor.popularity > 60 ? '🔥 热门' : '❄️ 冷门' }}
          </span>
        </div>
      </div>

      <!-- 右：迷你雷达 -->
      <div class="card-right">
        <MiniRadar
          :advisor-traits="advisor.radar_traits"
          :student-weights="userStore.profile.weights"
          :size="80"
        />
        <span v-if="!advisor.radar_traits" class="evidence-mini">仅学生需求</span>
        <button class="expand-btn" :class="{ open: expanded }" aria-label="展开详情" @click="toggleExpand">
          <el-icon><ArrowDown /></el-icon>
        </button>
      </div>
    </div>

    <button class="compare-btn" :aria-pressed="compared" @click="toggleCompare">
      {{ compared ? '移出对比' : '加入对比' }}
    </button>

    <!-- 展开详情面板 -->
    <transition name="slide-up">
      <div v-if="expanded" class="card-detail" @click.stop>
        <AdvisorDetail :advisor="advisor" />
        <div class="card-actions">
          <button class="action-btn primary" @click="contactAdvisor">
            <el-icon><Message /></el-icon>
            准备简历
          </button>
          <button
            class="action-btn"
            :class="{ active: feedbackGiven === 1 }"
            @click="giveFeedback(1)"
          >
            👍 {{ feedbackGiven === 1 ? '已赞' : '点赞' }}
          </button>
          <button
            class="action-btn"
            :class="{ active: feedbackGiven === -1 }"
            @click="giveFeedback(-1)"
          >
            👎
          </button>
        </div>
      </div>
    </transition>
  </article>
</template>

<style scoped lang="scss">
.advisor-card {
  background: $color-bg-card;
  border: 1px solid $color-border-light;
  border-radius: $card-radius;
  padding: $spacing-md $spacing-lg;
  cursor: pointer;
  transition: $transition-base;
  position: relative;

  &:hover {
    border-color: $color-primary-light;
    box-shadow: $shadow-card-hover;
    transform: translateY(-2px);
  }
  &.selected {
    border-color: $color-primary;
    border-width: 2px;
    padding: calc(#{$spacing-md} - 1px) calc(#{$spacing-lg} - 1px);
    box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.1);
  }
}

.card-main {
  display: flex;
  align-items: center;
  gap: $spacing-md;
}

.card-left {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  min-width: 0;
  flex: 0 0 auto;
}
.avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: $color-primary;
  font-weight: 700;
  font-size: 18px;
  flex-shrink: 0;
}
.info {
  min-width: 0;
  .name {
    font-size: 14px;
    font-weight: 600;
    color: $text-primary;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .dept {
    font-size: 11px;
    color: $text-secondary;
    margin-top: 2px;
  }
  .field {
    font-size: 11px;
    color: $text-placeholder;
    max-width: 140px;
    margin-top: 2px;
  }
}
.badge院士 {
  background: rgba(255, 149, 0, 0.15);
  color: $color-accent;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
}

.card-middle {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.tag {
  font-size: 10px;
  padding: 2px 6px;
  background: rgba(64, 158, 255, 0.08);
  color: $color-primary-dark;
  border-radius: 4px;
}
.score-row {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
}
.synergy {
  display: flex;
  align-items: baseline;
  gap: 4px;
  .synergy-label {
    font-size: 11px;
    color: $text-secondary;
  }
  .synergy-value {
    font-size: 18px;
    font-weight: 700;
    color: $color-accent;
    small {
      font-size: 11px;
    }
  }
}
.popularity-tag {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(144, 147, 153, 0.1);
  color: $text-secondary;
  &.hot {
    background: rgba(245, 108, 108, 0.1);
    color: $color-danger;
  }
}

.card-right {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.expand-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: $text-placeholder;
  font-size: 12px;
  transition: $transition-fast;
  &:hover {
    color: $color-primary;
    background: $color-bg-hover;
  }
  &.open {
    transform: rotate(180deg);
  }
}

.card-detail {
  margin-top: $spacing-md;
  padding-top: $spacing-md;
  border-top: 1px dashed $color-border;
}

.compare-btn {
  margin-top: $spacing-sm;
  color: $color-primary;
  font-size: 11px;
}

.evidence-mini {
  max-width: 70px;
  text-align: center;
  font-size: 11px;
  color: $text-secondary;
}

.card-actions {
  display: flex;
  gap: $spacing-sm;
  margin-top: $spacing-md;
}
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 1px solid $color-border;
  border-radius: $card-radius;
  font-size: 12px;
  color: $text-regular;
  transition: $transition-fast;

  &:hover {
    border-color: $color-primary;
    color: $color-primary;
  }
  &.primary {
    background: $color-primary;
    color: #fff;
    border-color: $color-primary;
    &:hover {
      background: $color-primary-light;
    }
  }
  &.active {
    background: rgba(64, 158, 255, 0.1);
    color: $color-primary;
    border-color: $color-primary;
  }
}

@media (max-width: $bp-tablet) {
  .card-main {
    flex-wrap: wrap;
  }
  .card-middle {
    flex: 1 1 100%;
    order: 3;
  }
}
</style>
