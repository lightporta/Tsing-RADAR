<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import RecruitmentList from '@/components/recruitment/RecruitmentList.vue'
import PublishForm from '@/components/recruitment/PublishForm.vue'
import {
  fetchMyRecruitments,
  withdrawRecruitment,
  type MyRecruitment,
} from '@/api/recruitment'

// =====================================================================
// 招募信息平台页（文档 §5.1 /recruitment）
// =====================================================================
const mine = ref<MyRecruitment[]>([])
const mineLoading = ref(false)

const statusLabels: Record<string, string> = {
  pending_review: '待审核',
  verified: '已通过',
  rejected: '未通过',
  restricted: '未公开',
  published: '已公开',
}

async function loadMine() {
  mineLoading.value = true
  try {
    mine.value = (await fetchMyRecruitments()).data
  } finally {
    mineLoading.value = false
  }
}

async function withdraw(item: MyRecruitment) {
  try {
    await ElMessageBox.confirm(
      `撤回后会删除投稿「${item.title}」，是否继续？`,
      '撤回投稿',
      { confirmButtonText: '确认撤回', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await withdrawRecruitment(item.recruit_id)
  ElMessage.success('投稿已撤回')
  await loadMine()
}

onMounted(loadMine)
</script>

<template>
  <SubPageLayout title="信息平台 · 招募信息">
    <div class="recruitment-view">
      <div class="container">
        <div class="view-head">
          <p class="view-desc">导师与学长学姐发布的实习、科研助理、招生信息</p>
          <PublishForm @published="loadMine" />
        </div>
        <section v-loading="mineLoading" class="mine-panel">
          <div class="mine-heading">
            <div>
              <h2>我的投稿</h2>
              <p>新投稿只进入审核队列，通过前不会出现在公开列表。</p>
            </div>
            <button type="button" class="refresh-mine" @click="loadMine">刷新</button>
          </div>
          <div v-if="mine.length" class="mine-list">
            <article v-for="item in mine" :key="item.recruit_id" class="mine-item">
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ new Date(item.created_at).toLocaleString() }}</p>
              </div>
              <span class="status-chip">{{ statusLabels[item.review_status] || item.review_status }}</span>
              <span class="status-chip muted">{{ statusLabels[item.publication_status] || item.publication_status }}</span>
              <el-button
                v-if="item.publication_status !== 'published'"
                size="small"
                text
                type="danger"
                @click="withdraw(item)"
              >
                撤回
              </el-button>
            </article>
          </div>
          <p v-else-if="!mineLoading" class="mine-empty">暂无投稿</p>
        </section>
        <RecruitmentList />
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.recruitment-view {
  padding: $spacing-xl $spacing-lg;
}
.container {
  max-width: 1200px;
  margin: 0 auto;
}
.view-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: $spacing-lg;
  .view-desc {
    font-size: 13px;
    color: $text-secondary;
  }
}
.mine-panel {
  margin-bottom: $spacing-xl;
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.mine-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;

  h2 { color: $text-primary; font-size: 15px; }
  p { margin-top: 4px; color: $text-placeholder; font-size: 11px; }
}
.refresh-mine { color: $color-primary; font-size: 12px; }
.mine-list { display: grid; gap: 8px; }
.mine-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: $spacing-sm;
  padding: 10px 12px;
  border-radius: 8px;
  background: $color-bg;

  strong { color: $text-primary; font-size: 13px; }
  p { margin-top: 3px; color: $text-placeholder; font-size: 10px; }
}
.status-chip {
  padding: 3px 7px;
  border-radius: 999px;
  color: #8a5a14;
  background: #fff3dc;
  font-size: 10px;
  &.muted { color: $text-secondary; background: $color-bg-hover; }
}
.mine-empty { padding: $spacing-lg; text-align: center; color: $text-placeholder; font-size: 12px; }

@media (max-width: $bp-tablet) {
  .recruitment-view {
    padding: $spacing-md;
  }
  .view-head {
    flex-direction: column;
    align-items: flex-start;
    gap: $spacing-sm;
  }
  .mine-item { grid-template-columns: minmax(0, 1fr) auto; }
  .mine-item .status-chip { display: none; }
}
</style>
