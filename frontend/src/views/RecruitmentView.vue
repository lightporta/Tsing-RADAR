<script setup lang="ts">
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import RecruitmentList from '@/components/recruitment/RecruitmentList.vue'
import PublishForm from '@/components/recruitment/PublishForm.vue'

// =====================================================================
// 招募信息平台页（文档 §5.1 /recruitment）
// =====================================================================
</script>

<template>
  <SubPageLayout title="信息平台 · 招募信息">
    <div class="recruitment-view">
      <div class="container">
        <div class="view-head">
          <p class="view-desc">导师与学长学姐发布的实习、科研助理、招生信息</p>
          <PublishForm />
        </div>
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

@media (max-width: $bp-tablet) {
  .recruitment-view {
    padding: $spacing-md;
  }
  .view-head {
    flex-direction: column;
    align-items: flex-start;
    gap: $spacing-sm;
  }
}
</style>
