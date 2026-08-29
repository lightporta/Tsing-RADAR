<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import FilterBar from './FilterBar.vue'
import AdvisorCard from './AdvisorCard.vue'
import { useAdvisorStore } from '@/stores/useAdvisorStore'

withDefaults(defineProps<{ mobileMode?: boolean }>(), { mobileMode: false })

const advisorStore = useAdvisorStore()
const router = useRouter()
const page = ref(1)
const pageSize = 5
const pageCount = computed(() =>
  Math.max(1, Math.ceil(advisorStore.matchedAdvisors.length / pageSize)),
)
const visibleAdvisors = computed(() => {
  const start = (page.value - 1) * pageSize
  return advisorStore.matchedAdvisors.slice(start, start + pageSize)
})

watch(
  () => advisorStore.matchedAdvisors,
  () => {
    page.value = 1
  },
)

function latestEvidenceTime(item: (typeof advisorStore.matchedAdvisors)[number]) {
  const dates =
    item.explanation?.supporting_evidence
      .flatMap((claim) => claim.citations)
      .map((citation) => citation.captured_at)
      .filter(Boolean) || []
  return dates.sort().at(-1)
}
</script>

<template>
  <div class="advisor-list-panel">
    <FilterBar />

    <div class="list-scroll" aria-live="polite">
      <div v-if="!advisorStore.matchedAdvisors.length && !advisorStore.loading" class="empty-state">
        <el-icon class="empty-icon" aria-hidden="true"><Search /></el-icon>
        <p>{{ advisorStore.resultMessage }}</p>
        <span v-if="advisorStore.resultStatus === 'no_published_data'" class="empty-hint">
          这是数据审核状态，不是匹配失败；2027 招生目录也不会冒充导师个人画像。
        </span>
        <span v-else class="empty-hint">完成访谈、逐项确认硬约束后再执行匹配。</span>
      </div>

      <div v-else-if="advisorStore.loading && !advisorStore.matchedAdvisors.length" class="skeleton-list">
        <div v-for="i in 5" :key="i" class="skeleton-card" />
      </div>

      <template v-else>
        <div class="card-list">
          <AdvisorCard
            v-for="advisor in visibleAdvisors"
            :key="advisor.advisor_id || advisor.name"
            :advisor="advisor"
            :selected="advisorStore.selectedName === advisor.name"
          />
        </div>

        <nav v-if="pageCount > 1" class="pagination" aria-label="有界推荐结果分页">
          <el-button size="small" :disabled="page === 1" @click="page--">上一页</el-button>
          <span>有界推荐第 {{ page }} / {{ pageCount }} 页（最多 20 条）</span>
          <el-button size="small" :disabled="page === pageCount" @click="page++">下一页</el-button>
        </nav>

        <section v-if="advisorStore.comparedAdvisors.length" class="compare-tray" aria-labelledby="compare-title">
          <div class="compare-head">
            <h3 id="compare-title">导师对比（{{ advisorStore.comparedAdvisors.length }}/3）</h3>
            <el-button type="primary" size="small" @click="router.push('/profile')">
              进入站内行动准备
            </el-button>
          </div>
          <div class="compare-table" role="table" aria-label="导师证据对比">
            <article v-for="item in advisorStore.comparedAdvisors" :key="item.advisor_id" role="row">
              <strong>{{ item.name }}</strong>
              <span>保守排序 {{ item.score.toFixed(1) }}</span>
              <span>适配 {{ (item.fit_score ?? item.score).toFixed(1) }}</span>
              <span>覆盖 {{ ((item.evidence_coverage ?? 0) * 100).toFixed(0) }}%</span>
              <span>置信 {{ ((item.evidence_confidence ?? 0) * 100).toFixed(0) }}%</span>
              <span>证据截至 {{ latestEvidenceTime(item) || '待核实' }}</span>
            </article>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped lang="scss">
.advisor-list-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: $color-bg-card;
  overflow: hidden;
}

.list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: $spacing-md $spacing-lg;
}

.card-list,
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 260px;
  padding: 40px 20px;
  color: $text-placeholder;
  text-align: center;

  .empty-icon {
    font-size: 40px;
    margin-bottom: $spacing-md;
  }
  p {
    color: $text-secondary;
  }
  .empty-hint {
    margin-top: 6px;
    font-size: 12px;
  }
}

.skeleton-card {
  height: 100px;
  border-radius: $card-radius;
  background: $color-border-light;
}

.pagination,
.compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}

.pagination {
  margin: $spacing-lg 0;
  font-size: 12px;
}

.compare-tray {
  margin-top: $spacing-lg;
  padding: $spacing-md;
  border: 1px solid $color-primary-light;
  border-radius: 10px;
  background: rgba(64, 158, 255, 0.04);
}

.compare-table {
  display: grid;
  gap: $spacing-xs;
  margin-top: $spacing-sm;

  article {
    display: grid;
    grid-template-columns: 1.1fr repeat(5, 1fr);
    gap: 6px;
    font-size: 11px;
  }
}

@media (max-width: $bp-tablet) {
  .compare-table article {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
