<script setup lang="ts">
import { useRouter } from 'vue-router'
import { HomeFilled } from '@element-plus/icons-vue'

const router = useRouter()
</script>

<template>
  <div class="not-found-view">
    <div class="not-found-card">
      <h1 class="title">404</h1>
      <p class="desc">抱歉，你访问的页面不存在。</p>
      <div class="actions">
        <el-button type="primary" @click="router.push('/')">
          <el-icon><HomeFilled /></el-icon>
          回首页
        </el-button>
        <el-button @click="router.back()">
          回上一页
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.not-found-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: $color-bg;
  padding: $spacing-lg;
}

.not-found-card {
  text-align: center;
  background: $color-bg-card;
  border: 1px solid $color-border-light;
  border-radius: $card-radius;
  padding: $spacing-xxl $spacing-xl;
  box-shadow: $shadow-card;
  max-width: 420px;
  width: 100%;
}

.title {
  font-size: 72px;
  font-weight: 700;
  color: $color-primary;
  line-height: 1;
  margin: 0 0 $spacing-md;
}

.desc {
  font-size: 16px;
  color: $text-regular;
  margin: 0 0 $spacing-xl;
}

.actions {
  display: flex;
  justify-content: center;
  gap: $spacing-md;
}
</style>
