<script setup lang="ts">
// Tsing-RADAR Logo：六边形雷达图标 + 文字
withDefaults(
  defineProps<{
    showText?: boolean
    size?: number
  }>(),
  { showText: true, size: 32 },
)
</script>

<template>
  <div class="app-logo">
    <svg :width="size" :height="size" viewBox="0 0 64 64" class="logo-icon" aria-hidden="true">
      <circle cx="32" cy="32" r="30" fill="var(--color-primary)" />
      <g stroke="#fff" stroke-width="2.5" fill="none" opacity="0.9">
        <polygon points="32,12 50,22 50,42 32,52 14,42 14,22" />
        <line x1="32" y1="12" x2="32" y2="52" />
        <line x1="14" y1="22" x2="50" y2="42" />
        <line x1="50" y1="22" x2="14" y2="42" />
      </g>
      <circle cx="32" cy="32" r="5" fill="#FF9500" />
    </svg>
    <div v-if="showText" class="logo-text">
      <span class="logo-name">Tsing-RADAR</span>
      <span class="logo-sub">清研寻师雷达</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.app-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  user-select: none;

  .logo-icon {
    flex-shrink: 0;
  }
  .logo-text {
    display: flex;
    flex-direction: column;
    line-height: 1.1;
  }
  .logo-name {
    font-size: 16px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: 0.5px;
  }
  .logo-sub {
    font-size: 11px;
    color: var(--text-secondary);
    margin-top: 2px;
  }
}
</style>
