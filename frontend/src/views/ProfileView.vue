<script setup lang="ts">
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import ProfileForm from '@/components/profile/ProfileForm.vue'
import ResumeManager from '@/components/profile/ResumeManager.vue'

// =====================================================================
// 个人信息与简历管理页（文档 §5.1 /profile）
// =====================================================================
</script>

<template>
  <SubPageLayout title="个人信息与简历管理">
    <div class="profile-view">
      <div class="container">
        <ProfileForm />
        <ResumeManager />
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.profile-view {
  padding: $spacing-xl $spacing-lg;
}

.container {
  max-width: 900px;
  margin: 0 auto;
}

@media (max-width: $bp-tablet) {
  .profile-view {
    padding: $spacing-md;
  }
}
</style>
