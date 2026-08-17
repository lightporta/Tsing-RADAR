<script setup lang="ts">
// =====================================================================
// 导师服务状态标签：tone 决定配色，label 为展示文案
// =====================================================================

withDefaults(
  defineProps<{
    label: string
    tone?: 'default' | 'muted' | 'success' | 'warning' | 'danger'
  }>(),
  { tone: 'default' },
)
</script>

<template>
  <span class="status-chip" :class="tone">{{ label }}</span>
</template>

<style scoped lang="scss">
.status-chip {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.5;
  white-space: nowrap;

  &.default {
    color: #4a5a72;
    background: #eef2f7;
  }
  &.muted {
    color: $text-secondary;
    background: $color-bg-hover;
  }
  &.success {
    color: #287a4d;
    background: #edf8f1;
  }
  &.warning {
    color: #8a5a14;
    background: #fff3dc;
  }
  &.danger {
    color: #b4442e;
    background: #fdeeea;
  }
}
</style>
