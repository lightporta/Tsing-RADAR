<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteComment,
  likeComment,
  postComment,
  reportComment,
  type CommentNode,
} from '@/api/recruitmentComment'
import { newIdempotencyKey } from '@/api/request'
import { displayTime } from '@/utils/format'

// =====================================================================
// 单条评论：徽章 / 时间 / 点赞 / 回复 / 举报 / 作者自删 / 长文折叠
// 仅两级：depth=1 的回复不再提供回复入口（服务端同样 422 拒绝）
// =====================================================================

const props = withDefaults(
  defineProps<{
    recruitId: string
    comment: CommentNode
    depth?: number
  }>(),
  { depth: 0 },
)
const emit = defineEmits<{ (event: 'changed'): void }>()

const MAX_LEN = 500
const isTopLevel = computed(() => props.depth === 0)

// —— 长文折叠（>6 行显示展开/收起）——
const expanded = ref(false)
const contentEl = ref<HTMLElement | null>(null)
const collapsible = ref(false)

async function measureCollapsible() {
  await nextTick()
  const el = contentEl.value
  if (el) collapsible.value = el.scrollHeight > el.clientHeight + 2
}

// —— 回复输入 ——
const replyOpen = ref(false)
const replyDraft = ref('')
const replySending = ref(false)
const replyIntent = ref<{ fingerprint: string; key: string } | null>(null)
const replyPendingReview = ref(false)

// —— 回复展开（嵌套回复默认收起）——
const repliesOpen = ref(false)

const replyTotal = computed(() => props.comment.reply_total ?? 0)
const previewReplies = computed(() => props.comment.replies ?? [])

// —— 点赞（每主体一次去重，服务端兜底）——
const likeSending = ref(false)
const likeIntentKey = ref<string | null>(null)
const likeCount = ref(props.comment.like_count)
const liked = ref(false)

async function sendLike() {
  if (likeSending.value || liked.value || props.comment.deleted) return
  likeSending.value = true
  if (!likeIntentKey.value) likeIntentKey.value = newIdempotencyKey('comment-like')
  try {
    const res = await likeComment(
      props.recruitId,
      props.comment.comment_id,
      likeIntentKey.value,
    )
    if (typeof res.like_count === 'number') likeCount.value = res.like_count
    liked.value = true
  } finally {
    likeSending.value = false
  }
}

// —— 举报（立即隐藏，服务端转审核队列）——
const reportSending = ref(false)

async function sendReport() {
  if (reportSending.value) return
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请说明举报原因', '举报评论', {
      confirmButtonText: '提交举报',
      cancelButtonText: '取消',
      inputPlaceholder: '如：含站外联系方式、广告、不友善内容',
      inputValidator: (value) => Boolean(value && value.trim()) || '请填写举报原因',
    })
    reason = result.value.trim()
  } catch {
    return
  }
  reportSending.value = true
  try {
    await reportComment(
      props.recruitId,
      props.comment.comment_id,
      reason,
      newIdempotencyKey('comment-report'),
    )
    ElMessage.success('已举报，该评论已隐藏并进入审核队列')
    emit('changed')
  } finally {
    reportSending.value = false
  }
}

// —— 作者自删（软删保楼层）——
const deleteSending = ref(false)

async function sendDelete() {
  if (deleteSending.value) return
  try {
    await ElMessageBox.confirm('删除后楼层保留为「已删除」占位，回复仍可见。', '删除评论', {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  deleteSending.value = true
  try {
    await deleteComment(
      props.recruitId,
      props.comment.comment_id,
      newIdempotencyKey('comment-delete'),
    )
    ElMessage.success('评论已删除')
    emit('changed')
  } finally {
    deleteSending.value = false
  }
}

// —— 发表回复 ——
async function sendReply() {
  if (replySending.value) return
  const content = replyDraft.value.trim()
  if (!content) return
  const fingerprint = JSON.stringify({
    parent_id: props.comment.comment_id,
    content,
  })
  if (replyIntent.value?.fingerprint !== fingerprint) {
    replyIntent.value = {
      fingerprint,
      key: newIdempotencyKey('comment-reply'),
    }
  }
  replySending.value = true
  try {
    const res = await postComment(
      props.recruitId,
      content,
      props.comment.comment_id,
      replyIntent.value.key,
    )
    replyIntent.value = null
    replyDraft.value = ''
    replyOpen.value = false
    if (res.review_status === 'pending_review') {
      // 先审后发：诚实提示，不伪造可见性
      replyPendingReview.value = true
      ElMessage.info('已提交，审核通过后展示')
    } else {
      ElMessage.success('已发布')
      repliesOpen.value = true
      emit('changed')
    }
  } finally {
    replySending.value = false
  }
}

defineExpose({ measureCollapsible })
</script>

<template>
  <div class="comment-item" :class="{ deleted: comment.deleted }">
    <div class="comment-head">
      <span class="badge" :class="{ op: comment.is_op }">{{ comment.badge }}</span>
      <span class="time">{{ displayTime(comment.created_at) }}</span>
    </div>
    <p
      ref="contentEl"
      class="content"
      :class="{ clamped: !expanded }"
      @vue:mounted="measureCollapsible"
    >
      {{ comment.content }}
    </p>
    <button
      v-if="collapsible"
      type="button"
      class="expand-toggle"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起' : '展开全文' }}
    </button>

    <div v-if="!comment.deleted" class="actions">
      <button
        type="button"
        class="action"
        :class="{ liked }"
        :disabled="likeSending"
        @click="sendLike"
      >
        👍 {{ likeCount }}
      </button>
      <button
        v-if="isTopLevel"
        type="button"
        class="action"
        @click="replyOpen = !replyOpen"
      >
        回复
      </button>
      <button
        type="button"
        class="action danger"
        :disabled="reportSending"
        @click="sendReport"
      >
        举报
      </button>
      <button
        v-if="comment.own"
        type="button"
        class="action danger"
        :disabled="deleteSending"
        @click="sendDelete"
      >
        删除
      </button>
    </div>

    <!-- 回复输入框 -->
    <div v-if="replyOpen" class="reply-box">
      <el-input
        v-model="replyDraft"
        type="textarea"
        :rows="2"
        :maxlength="MAX_LEN"
        show-word-limit
        placeholder="写下你的回复…"
        aria-label="回复评论"
      />
      <div class="reply-actions">
        <el-button size="small" @click="replyOpen = false">取消</el-button>
        <el-button
          size="small"
          type="primary"
          :loading="replySending"
          :disabled="!replyDraft.trim()"
          @click="sendReply"
        >
          发布回复
        </el-button>
      </div>
    </div>
    <p v-if="replyPendingReview" class="pending-note">你的回复已提交，审核通过后展示。</p>

    <!-- 嵌套回复：默认收起 -->
    <div v-if="isTopLevel && replyTotal > 0" class="replies">
      <button type="button" class="replies-toggle" @click="repliesOpen = !repliesOpen">
        {{ repliesOpen ? '收起回复' : `查看 ${replyTotal} 条回复` }}
      </button>
      <div v-show="repliesOpen" class="reply-list">
        <CommentItem
          v-for="reply in previewReplies"
          :key="reply.comment_id"
          :recruit-id="recruitId"
          :comment="reply"
          :depth="depth + 1"
          @changed="emit('changed')"
        />
        <p v-if="replyTotal > previewReplies.length" class="more-note">
          仅展示前 {{ previewReplies.length }} 条，共 {{ replyTotal }} 条回复
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.comment-item {
  padding: $spacing-md 0;
  border-bottom: 1px solid $color-border-light;

  &:last-child {
    border-bottom: none;
  }
  &.deleted .content {
    color: $text-placeholder;
    font-style: italic;
  }
}

.comment-head {
  display: flex;
  align-items: center;
  gap: $spacing-sm;
  margin-bottom: 4px;
  .badge {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 999px;
    color: $text-secondary;
    background: $color-bg-hover;

    &.op {
      color: $color-primary;
      background: rgba($color-primary, 0.1);
      font-weight: 600;
    }
  }
  .time {
    font-size: 10px;
    color: $text-placeholder;
  }
}

.content {
  font-size: 13px;
  color: $text-regular;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;

  &.clamped {
    display: -webkit-box;
    -webkit-line-clamp: 6;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
}

.expand-toggle,
.replies-toggle {
  font-size: 11px;
  color: $color-primary;
  margin-top: 4px;
}

.actions {
  display: flex;
  gap: $spacing-md;
  margin-top: 6px;
  .action {
    font-size: 11px;
    color: $text-secondary;

    &:hover {
      color: $color-primary;
    }
    &.liked {
      color: $color-primary;
      font-weight: 600;
    }
    &.danger:hover {
      color: $color-danger;
    }
    &:disabled {
      opacity: 0.5;
      cursor: wait;
    }
  }
}

.reply-box {
  margin-top: $spacing-sm;
  .reply-actions {
    display: flex;
    justify-content: flex-end;
    gap: $spacing-sm;
    margin-top: $spacing-sm;
  }
}

.pending-note {
  margin-top: $spacing-sm;
  font-size: 11px;
  color: #b26a00;
}

.replies {
  margin-top: $spacing-sm;
  .reply-list {
    margin-top: $spacing-xs;
    padding-left: $spacing-md;
    border-left: 2px solid $color-border-light;
  }
  .more-note {
    font-size: 10px;
    color: $text-placeholder;
    padding: $spacing-xs 0;
  }
}
</style>
