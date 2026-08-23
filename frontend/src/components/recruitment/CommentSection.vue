<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import CommentItem from './CommentItem.vue'
import { fetchComments, postComment, type CommentNode } from '@/api/recruitmentComment'
import { newIdempotencyKey } from '@/api/request'

// =====================================================================
// 评论区容器：发表框（字数计数 / 已提交态）+ 两级树分页加载
// 空态诚实文案；加载失败与空态可区分（loadError + 重试）
// =====================================================================

const props = defineProps<{ recruitId: string }>()

const MAX_LEN = 500
const PAGE_SIZE = 10

const items = ref<CommentNode[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadError = ref('')
const draft = ref('')
const sending = ref(false)
const sendIntent = ref<{ fingerprint: string; key: string } | null>(null)
const pendingReviewNote = ref(false)

async function loadPage(targetPage: number, append: boolean) {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchComments(props.recruitId, targetPage, PAGE_SIZE)
    items.value = append ? [...items.value, ...res.data] : res.data
    total.value = res.meta.total
    page.value = targetPage
  } catch {
    loadError.value = '评论加载失败'
  } finally {
    loading.value = false
  }
}

async function refresh() {
  await loadPage(1, false)
}

async function loadMore() {
  await loadPage(page.value + 1, true)
}

async function send() {
  if (sending.value) return
  const content = draft.value.trim()
  if (!content) return
  const fingerprint = JSON.stringify({ parent_id: null, content })
  if (sendIntent.value?.fingerprint !== fingerprint) {
    sendIntent.value = { fingerprint, key: newIdempotencyKey('comment') }
  }
  sending.value = true
  try {
    const res = await postComment(
      props.recruitId,
      content,
      null,
      sendIntent.value.key,
    )
    sendIntent.value = null
    draft.value = ''
    if (res.review_status === 'pending_review') {
      // 先审后发：诚实提示「已提交，审核中」，不伪造可见性
      pendingReviewNote.value = true
      ElMessage.info('已提交，审核通过后展示')
    } else {
      pendingReviewNote.value = false
      ElMessage.success('已发布')
      await refresh()
    }
  } finally {
    sending.value = false
  }
}

onMounted(() => loadPage(1, false))
</script>

<template>
  <section class="comment-section" aria-labelledby="comment-title">
    <h3 id="comment-title" class="section-title">💬 评论区</h3>

    <!-- 发表框 -->
    <div class="editor">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        :maxlength="MAX_LEN"
        show-word-limit
        placeholder="问一句名额、方向或作息…（勿留联系方式，含链接将先审后发）"
        aria-label="发表评论"
      />
      <div class="editor-foot">
        <span class="counter">{{ draft.length }}/{{ MAX_LEN }}</span>
        <el-button
          type="primary"
          size="small"
          :loading="sending"
          :disabled="!draft.trim()"
          @click="send"
        >
          发表评论
        </el-button>
      </div>
      <p v-if="pendingReviewNote" class="pending-note">你的评论已提交，审核通过后展示。</p>
    </div>

    <!-- 评论树 -->
    <div v-loading="loading && page === 1" class="comment-list">
      <template v-if="items.length">
        <CommentItem
          v-for="item in items"
          :key="item.comment_id"
          :recruit-id="recruitId"
          :comment="item"
          @changed="refresh"
        />
        <div v-if="items.length < total" class="load-more">
          <el-button size="small" text :loading="loading" @click="loadMore">
            加载更多（{{ items.length }}/{{ total }}）
          </el-button>
        </div>
      </template>
      <div v-else-if="loadError" class="empty">
        <p>{{ loadError }}</p>
        <el-button size="small" @click="refresh">重试</el-button>
      </div>
      <p v-else-if="!loading" class="empty">还没有评论，问一句名额、方向或作息？</p>
    </div>
  </section>
</template>

<style scoped lang="scss">
.comment-section {
  margin-top: $spacing-xl;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: $spacing-md;
}

.editor {
  padding: $spacing-md;
  border: 1px solid $color-border-light;
  border-radius: 10px;
  background: $color-bg-card;
  margin-bottom: $spacing-md;
}

.editor-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: $spacing-sm;
  .counter {
    font-size: 11px;
    color: $text-placeholder;
  }
}

.pending-note {
  margin-top: $spacing-sm;
  font-size: 11px;
  color: #b26a00;
}

.comment-list {
  min-height: 80px;
}

.load-more {
  display: flex;
  justify-content: center;
  padding: $spacing-sm 0;
}

.empty {
  padding: $spacing-xl;
  text-align: center;
  color: $text-placeholder;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: $spacing-sm;
}
</style>
