<script setup lang="ts">
import type { MentorInboundMatches } from '@/types/mentor'
import { displayTime } from '@/utils/format'

// =====================================================================
// 意向中心列表：展示匹配意向摘要；学生身份信息不下发（后端已匿名化）。
// =====================================================================

defineProps<{
  matches: MentorInboundMatches
  loading: boolean
}>()
</script>

<template>
  <section class="inbound-list" aria-label="匹配意向列表">
    <div class="inbound-head">
      <h3>匹配意向</h3>
      <span class="inbound-count">共 {{ matches.total }} 条</span>
    </div>
    <div v-loading="loading" class="inbound-body">
      <ul v-if="matches.recent.length" class="inbound-items">
        <li v-for="item in matches.recent" :key="item.record_id" class="inbound-item">
          <div class="inbound-top">
            <span class="inbound-score">
              匹配度 {{ item.synergy_score != null ? `${Math.round(item.synergy_score * 100)}%` : '—' }}
            </span>
            <span class="inbound-time">{{ displayTime(item.created_at) }}</span>
          </div>
          <p v-if="item.match_reason" class="inbound-reason">{{ item.match_reason }}</p>
        </li>
      </ul>
      <p v-else-if="!loading" class="inbound-empty">暂无匹配意向</p>
    </div>
  </section>
</template>

<style scoped lang="scss">
.inbound-list {
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 12px;
  background: $color-bg-card;
}
.inbound-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $spacing-md;
}
.inbound-head h3 {
  color: $text-primary;
  font-size: 14px;
}
.inbound-count {
  color: $text-placeholder;
  font-size: 11px;
}
.inbound-items {
  display: grid;
  gap: $spacing-sm;
}
.inbound-item {
  padding: $spacing-md;
  border-radius: 8px;
  background: $color-bg;
}
.inbound-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $spacing-sm;
}
.inbound-score {
  color: $color-primary;
  font-size: 12px;
  font-weight: 600;
}
.inbound-time {
  color: $text-placeholder;
  font-size: 10px;
}
.inbound-reason {
  margin-top: 6px;
  color: $text-regular;
  font-size: 12px;
  line-height: 1.6;
}
.inbound-empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
}
</style>
