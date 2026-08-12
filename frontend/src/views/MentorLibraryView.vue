<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { fetchMentorResources } from '@/api/advisor'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import type {
  MentorResource,
  MentorResourceMeta,
  MentorResourceType,
} from '@/types/advisor'

const loading = ref(false)
const records = ref<MentorResource[]>([])
const meta = ref<MentorResourceMeta | null>(null)
const filters = reactive<{
  q: string
  dept: string
  resourceType: MentorResourceType | ''
  catalogType: '' | 'doctoral_regular' | 'doctoral_recommendation_exempt'
  page: number
  pageSize: number
}>({
  q: '',
  dept: '',
  resourceType: 'verified_mentor_profile',
  catalogType: '',
  page: 1,
  pageSize: 20,
})

async function loadResources() {
  loading.value = true
  try {
    const response = await fetchMentorResources({
      q: filters.q.trim() || undefined,
      dept: filters.dept.trim() || undefined,
      resource_type: filters.resourceType || undefined,
      catalog_type: filters.catalogType || undefined,
      page: filters.page,
      page_size: filters.pageSize,
    })
    records.value = response.data
    meta.value = response.meta
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  loadResources()
}

function changePage(page: number) {
  filters.page = page
  loadResources()
}

function resourceLabel(item: MentorResource) {
  if (item.resource_type === 'verified_mentor_profile') return '已核验导师画像'
  if (item.resource_type === 'advisor_group_catalog_entry') return '2027 目录导师组'
  return '2027 目录导师'
}

function sourceLinks(item: MentorResource) {
  const links = Object.values(item.provenance)
    .flat()
    .filter((citation) => citation.source_url)
  return Array.from(
    new Map(links.map((citation) => [citation.source_url, citation])).values(),
  ).slice(0, 4)
}

function catalogLabel(value: string) {
  return value === 'doctoral_regular' ? '普通招考' : '推免目录'
}

onMounted(loadResources)
</script>

<template>
  <SubPageLayout title="导师资源库">
    <div class="mentor-library">
      <section class="library-intro">
        <div>
          <h2>正式导师资源库</h2>
          <p>
            “已核验导师画像”可进入证据化匹配；“目录导师/导师组”只表示 2027 官方招生目录事实。
            页面不推断当前名额、录取概率、指导风格、经费或组内氛围。
          </p>
        </div>
        <dl v-if="meta" class="summary-grid">
          <div><dt>可推荐导师</dt><dd>{{ meta.match_candidate_records }}</dd></div>
          <div><dt>导师画像</dt><dd>{{ meta.verified_profile_records }}</dd></div>
          <div><dt>目录资源</dt><dd>{{ meta.catalog_records }}</dd></div>
        </dl>
      </section>

      <form class="search-panel" @submit.prevent="search">
        <el-input v-model="filters.q" clearable placeholder="姓名、专业或研究方向" />
        <el-input v-model="filters.dept" clearable placeholder="院系" />
        <el-select v-model="filters.resourceType" placeholder="全部资源">
          <el-option label="全部资源" value="" />
          <el-option label="已核验导师画像" value="verified_mentor_profile" />
          <el-option label="2027 目录导师" value="mentor_catalog_entry" />
          <el-option label="2027 目录导师组" value="advisor_group_catalog_entry" />
        </el-select>
        <el-select v-model="filters.catalogType" placeholder="全部目录类型">
          <el-option label="全部目录类型" value="" />
          <el-option label="普通招考" value="doctoral_regular" />
          <el-option label="推免目录" value="doctoral_recommendation_exempt" />
        </el-select>
        <el-button type="primary" native-type="submit">检索</el-button>
      </form>

      <p v-if="meta" class="result-count">共找到 {{ meta.filtered_records }} 条</p>
      <div v-loading="loading" class="resource-list" aria-live="polite">
        <el-empty v-if="!loading && !records.length" description="没有符合条件的已发布资源" />
        <article v-for="item in records" :key="item.advisor_id" class="resource-card">
          <div class="card-heading">
            <div>
              <span class="resource-badge" :class="item.resource_type">{{ resourceLabel(item) }}</span>
              <h3>{{ item.name }}</h3>
              <p>{{ item.dept }}<span v-if="item.title"> · {{ item.title }}</span></p>
            </div>
            <a
              v-if="item.official_homepage"
              :href="item.official_homepage"
              target="_blank"
              rel="noopener noreferrer"
              class="homepage-link"
            >官方主页 ↗</a>
          </div>

          <div v-if="item.programs?.length" class="fact-row">
            <strong>专业</strong>
            <span>{{ item.programs.join('、') }}</span>
          </div>
          <div v-if="item.research_keywords?.length" class="fact-row">
            <strong>目录研究方向</strong>
            <div class="tag-list">
              <span v-for="keyword in item.research_keywords" :key="keyword">{{ keyword }}</span>
            </div>
          </div>
          <div v-if="item.catalog_types?.length" class="fact-row">
            <strong>目录类型</strong>
            <span>{{ item.catalog_types.map(catalogLabel).join('、') }} · {{ item.academic_year }} 年</span>
          </div>

          <footer class="evidence-footer">
            <span>审核：{{ item.data_status.review_status }}</span>
            <span v-if="item.data_status.verified_at">
              审核时间：{{ new Date(item.data_status.verified_at).toLocaleDateString() }}
            </span>
            <span v-if="item.data_status.expires_at">
              复核期限：{{ new Date(item.data_status.expires_at).toLocaleDateString() }}
            </span>
            <a
              v-for="citation in sourceLinks(item)"
              :key="citation.evidence_id"
              :href="citation.source_url || undefined"
              target="_blank"
              rel="noopener noreferrer"
            >官方来源 ↗</a>
          </footer>
        </article>
      </div>

      <el-pagination
        v-if="meta && meta.total_pages > 1"
        class="pagination"
        background
        layout="prev, pager, next"
        :current-page="filters.page"
        :page-size="filters.pageSize"
        :total="meta.filtered_records"
        @current-change="changePage"
      />
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.mentor-library {
  max-width: 1180px;
  margin: 0 auto;
  padding: $spacing-xl $spacing-lg 48px;
}

.library-intro {
  display: flex;
  justify-content: space-between;
  gap: $spacing-xl;
  padding: $spacing-xl;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.1), rgba(103, 194, 58, 0.06));
  border: 1px solid rgba(64, 158, 255, 0.18);
  border-radius: 14px;

  h2 { margin-bottom: 8px; font-size: 22px; color: $text-primary; }
  p { max-width: 720px; color: $text-secondary; font-size: 13px; line-height: 1.7; }
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(92px, 1fr));
  gap: 8px;

  div { padding: 12px; text-align: center; background: rgba(255, 255, 255, 0.72); border-radius: 10px; }
  dt { color: $text-secondary; font-size: 11px; }
  dd { margin-top: 4px; color: $color-primary; font-size: 24px; font-weight: 700; }
}

.search-panel {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr 1fr auto;
  gap: 10px;
  margin: $spacing-lg 0 $spacing-sm;
  padding: $spacing-md;
  background: $color-bg-card;
  border: 1px solid $color-border-light;
  border-radius: 12px;
}

.result-count { margin: 12px 2px; color: $text-secondary; font-size: 12px; }
.resource-list { min-height: 220px; display: grid; gap: $spacing-md; }
.resource-card { padding: $spacing-lg; background: $color-bg-card; border: 1px solid $color-border-light; border-radius: 12px; }
.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.card-heading h3 { display: inline; margin-right: 8px; font-size: 18px; }
.card-heading p { margin-top: 5px; color: $text-secondary; font-size: 12px; }
.resource-badge { display: inline-block; margin-right: 8px; padding: 3px 7px; border-radius: 999px; background: rgba(144, 147, 153, 0.12); color: $text-secondary; font-size: 10px; }
.resource-badge.verified_mentor_profile { background: rgba(103, 194, 58, 0.12); color: #4f8f2f; }
.homepage-link, .evidence-footer a { color: $color-primary; font-size: 12px; }
.fact-row { display: grid; grid-template-columns: 110px 1fr; gap: 10px; margin-top: 14px; font-size: 12px; color: $text-regular; }
.fact-row strong { color: $text-secondary; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-list span { padding: 3px 7px; border-radius: 5px; background: rgba(64, 158, 255, 0.08); color: $color-primary-dark; }
.evidence-footer { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: $spacing-lg; padding-top: $spacing-sm; border-top: 1px solid $color-border-light; color: $text-placeholder; font-size: 10px; }
.pagination { justify-content: center; margin-top: $spacing-xl; }

@media (max-width: $bp-tablet) {
  .mentor-library { padding: $spacing-md; }
  .library-intro { flex-direction: column; padding: $spacing-lg; }
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .search-panel { grid-template-columns: 1fr; }
  .fact-row { grid-template-columns: 1fr; gap: 4px; }
}
</style>
