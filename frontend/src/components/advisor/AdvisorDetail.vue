<script setup lang="ts">
import { computed } from 'vue'
import type { MatchedAdvisor } from '@/types/advisor'
import { TRAITS } from '@/types/advisor'
import { displayTime } from '@/utils/format'
import RatingPanel from './RatingPanel.vue'
import RatingSummary from './RatingSummary.vue'

// =====================================================================
// 导师详情面板（卡片展开后显示，文档 §3.4 / §4.3.1）
// 展示：六维特质明细 / 学生评价（M1）/ 在研项目 / 招募信息 / 联系方式
// =====================================================================

const props = defineProps<{ advisor: MatchedAdvisor }>()

const traitRows = computed(() =>
  TRAITS.map((t) => ({
    label: t.label,
    desc: t.description,
    score: props.advisor.radar_traits?.[t.key] ?? 0,
  })),
)

const recruitments = computed(() => props.advisor.recruitments || [])
const projects = computed(() => props.advisor.projects || [])
</script>

<template>
  <div class="advisor-detail">
    <div v-if="advisor.explanation" class="section evidence-section">
      <h4 class="section-title">可核验证据与不确定性</h4>
      <p>
        证据覆盖 {{ ((advisor.evidence_coverage ?? 0) * 100).toFixed(0) }}% ·
        置信度 {{ ((advisor.evidence_confidence ?? 0) * 100).toFixed(0) }}% ·
        适配分 {{ (advisor.fit_score ?? advisor.score).toFixed(1) }}
      </p>
      <ul class="evidence-list">
        <li v-for="claim in advisor.explanation.supporting_evidence" :key="claim.statement">
          <strong>支持：</strong>{{ claim.statement }}
          <span v-for="citation in claim.citations" :key="citation.evidence_id" class="citation">
            <a
              v-if="citation.source_url"
              :href="citation.source_url"
              target="_blank"
              rel="noopener noreferrer"
            >
              来源
            </a>
            <span v-else>{{ citation.citation }}</span>
            · {{ displayTime(citation.captured_at) }}
            · {{ (citation.confidence * 100).toFixed(0) }}%
          </span>
        </li>
        <li v-for="claim in advisor.explanation.counter_evidence" :key="claim.statement">
          <strong>反证：</strong>{{ claim.statement }}
        </li>
        <li v-for="item in advisor.explanation.uncertainties" :key="item">
          <strong>不确定：</strong>{{ item }}
        </li>
        <li v-for="item in advisor.explanation.questions_to_verify" :key="item">
          <strong>待核实：</strong>{{ item }}
        </li>
      </ul>
    </div>

    <!-- 六维特质条 -->
    <div v-if="advisor.radar_traits" class="section">
      <h4 class="section-title">🎯 六维导师特质</h4>
      <div class="trait-bars">
        <div v-for="row in traitRows" :key="row.label" class="trait-row">
          <div class="trait-head">
            <span class="trait-label">{{ row.label }}</span>
            <span class="trait-score">{{ row.score }}</span>
          </div>
          <div class="trait-bar">
            <div class="trait-fill" :style="{ width: row.score + '%' }" />
          </div>
          <p class="trait-desc">{{ row.desc }}</p>
        </div>
      </div>
    </div>

    <!-- 学生评价（M1）：聚合摘要 + 匿名评分面板 -->
    <div class="section">
      <h4 class="section-title">🧑‍🎓 学生评价</h4>
      <RatingSummary :advisor-id="advisor.advisor_id" />
    </div>
    <div class="section">
      <h4 class="section-title">✍️ 我要评价（匿名）</h4>
      <RatingPanel :advisor-id="advisor.advisor_id" />
    </div>

    <!-- 在研项目 -->
    <div v-if="projects.length" class="section">
      <h4 class="section-title">🔬 在研项目</h4>
      <ul class="project-list">
        <li v-for="(p, i) in projects" :key="i" class="project-item">
          <div class="project-title">{{ p.title }}</div>
          <p class="project-desc">{{ p.desc }}</p>
          <span class="project-fund">{{ p.fund }}</span>
        </li>
      </ul>
    </div>

    <!-- 招募信息 -->
    <div v-if="recruitments.length" class="section">
      <h4 class="section-title">📢 招募信息</h4>
      <ul class="recruit-list">
        <li v-for="(r, i) in recruitments" :key="i" class="recruit-item" :class="{ urgent: r.is_urgent }">
          <div class="recruit-head">
            <span class="recruit-type">{{ r.type }}</span>
            <span v-if="r.is_urgent" class="urgent-tag">🔥 急招</span>
            <span class="recruit-deadline">截止：{{ r.deadline }}</span>
          </div>
          <div class="recruit-title">{{ r.title }}</div>
          <p class="recruit-req">{{ r.req }}</p>
          <span class="recruit-major">专业板块：{{ r.major }}</span>
        </li>
      </ul>
    </div>

    <!-- 联系方式 -->
    <div v-if="advisor.contact_email || advisor.office_loc" class="section">
      <h4 class="section-title">📍 联系方式</h4>
      <div class="contact-info">
        <p v-if="advisor.contact_email">📧 {{ advisor.contact_email }}</p>
        <p v-if="advisor.office_loc">🏫 {{ advisor.office_loc }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.advisor-detail {
  display: flex;
  flex-direction: column;
  gap: $spacing-lg;
}

.section {
  .section-title {
    font-size: 12px;
    font-weight: 600;
    color: $text-regular;
    margin-bottom: $spacing-sm;
  }
}

.evidence-section {
  padding: $spacing-md;
  background: rgba(64, 158, 255, 0.04);
  border-radius: 8px;

  > p {
    font-size: 12px;
    color: $text-secondary;
  }
}

.evidence-list {
  margin-top: $spacing-sm;
  display: grid;
  gap: 6px;

  li {
    font-size: 11px;
    color: $text-regular;
  }
}

.citation {
  display: block;
  margin-left: 12px;
  color: $text-secondary;
}

.trait-bars {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: $spacing-md;
}
.trait-row {
  .trait-head {
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    margin-bottom: 3px;
    .trait-label {
      color: $text-regular;
    }
    .trait-score {
      color: $color-accent;
      font-weight: 600;
    }
  }
  .trait-bar {
    height: 4px;
    background: $color-border-light;
    border-radius: 2px;
    overflow: hidden;
  }
  .trait-fill {
    height: 100%;
    background: linear-gradient(90deg, $color-primary, $color-accent);
    border-radius: 2px;
    transition: width 0.5s ease;
  }
  .trait-desc {
    font-size: 10px;
    color: $text-placeholder;
    margin-top: 3px;
    line-height: 1.4;
  }
}

.project-list,
.recruit-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-sm;
}
.project-item {
  padding: $spacing-sm $spacing-md;
  background: $color-bg;
  border-radius: 6px;
  .project-title {
    font-size: 12px;
    font-weight: 600;
    color: $text-primary;
  }
  .project-desc {
    font-size: 11px;
    color: $text-secondary;
    margin: 2px 0;
  }
  .project-fund {
    font-size: 10px;
    color: $color-primary;
  }
}

.recruit-item {
  padding: $spacing-sm $spacing-md;
  background: $color-bg;
  border-radius: 6px;
  border-left: 3px solid $color-primary;

  &.urgent {
    border-left-color: $color-danger;
    background: rgba(245, 108, 108, 0.04);
  }
  .recruit-head {
    display: flex;
    align-items: center;
    gap: $spacing-sm;
    font-size: 10px;
    .recruit-type {
      background: rgba(64, 158, 255, 0.1);
      color: $color-primary;
      padding: 1px 6px;
      border-radius: 3px;
    }
    .urgent-tag {
      color: $color-danger;
    }
    .recruit-deadline {
      color: $text-placeholder;
      margin-left: auto;
    }
  }
  .recruit-title {
    font-size: 12px;
    font-weight: 600;
    margin: 4px 0;
  }
  .recruit-req {
    font-size: 11px;
    color: $text-secondary;
    margin-bottom: 4px;
  }
  .recruit-major {
    font-size: 10px;
    color: $text-placeholder;
  }
}

.contact-info {
  p {
    font-size: 12px;
    color: $text-regular;
    margin-bottom: 4px;
  }
}
</style>
