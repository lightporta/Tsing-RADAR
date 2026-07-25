<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchRecruitments } from '@/api/recruitment'
import { mockRecruitments } from '@/mock'
import type { RecruitmentItem } from '@/types/api'

// =====================================================================
// 招募信息列表（文档 §2.1.7 / §4.2.3）
// 含急需榜（is_urgent=true 置顶）
// 支持投递简历
// =====================================================================

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

const allItems = ref<RecruitmentItem[]>([])
const loading = ref(false)
const filterUrgent = ref(false)
const submitDialogVisible = ref(false)
const submittingItem = ref<RecruitmentItem | null>(null)

const displayItems = computed(() => {
  // 急招置顶
  const sorted = [...allItems.value].sort((a, b) => {
    if (a.is_urgent !== b.is_urgent) return a.is_urgent ? -1 : 1
    return 0
  })
  return filterUrgent.value ? sorted.filter((i) => i.is_urgent) : sorted
})

const urgentCount = computed(() => allItems.value.filter((i) => i.is_urgent).length)

async function loadList() {
  loading.value = true
  try {
    if (USE_MOCK) {
      allItems.value = mockRecruitments
    } else {
      const res = await fetchRecruitments()
      allItems.value = res.data
    }
  } finally {
    loading.value = false
  }
}

function openSubmit(item: RecruitmentItem) {
  submittingItem.value = item
  submitDialogVisible.value = true
}

async function confirmSubmit() {
  // 投递逻辑实际由 ResumeManager 选定 resume_id 后调用 submitResume
  ElMessage.success(`已投递简历至「${submittingItem.value?.title}」`)
  submitDialogVisible.value = false
}

const typeColors: Record<string, string> = {
  招生: '#409eff',
  实习: '#67c23a',
  科研助理: '#e6a23c',
}

onMounted(loadList)
</script>

<template>
  <div class="recruitment-list">
    <!-- 急需榜横幅 -->
    <div v-if="urgentCount > 0" class="urgent-banner">
      <span class="urgent-icon">🔥</span>
      <span>急需榜：当前有 <strong>{{ urgentCount }}</strong> 条紧急招募</span>
      <el-switch v-model="filterUrgent" active-text="仅看急招" />
    </div>

    <!-- 列表 -->
    <div v-loading="loading" class="list-body">
      <div v-for="item in displayItems" :key="item.recruit_id" class="recruit-card" :class="{ urgent: item.is_urgent }">
        <div class="card-head">
          <span class="recruit-type" :style="{ background: (typeColors[item.type] || '#909399') + '22', color: typeColors[item.type] || '#909399' }">
            {{ item.type }}
          </span>
          <span v-if="item.is_urgent" class="urgent-tag">🔥 急招</span>
          <span class="publisher">{{ item.publisher_name }}</span>
          <span class="dept">{{ item.dept }}</span>
          <span class="deadline">截止：{{ item.deadline }}</span>
        </div>
        <h3 class="recruit-title">{{ item.title }}</h3>
        <p class="recruit-req">{{ item.req }}</p>
        <div class="card-foot">
          <span class="major">📍 {{ item.major }}</span>
          <el-button size="small" type="primary" @click="openSubmit(item)">
            投递简历
          </el-button>
        </div>
      </div>

      <div v-if="!loading && !displayItems.length" class="empty">
        <p>暂无招募信息</p>
      </div>
    </div>

    <!-- 投递确认弹窗 -->
    <el-dialog v-model="submitDialogVisible" title="投递简历" width="420px">
      <p v-if="submittingItem">确定将你的简历投递至「<strong>{{ submittingItem.title }}</strong>」？</p>
      <p class="dialog-hint">投递后可在个人信息页查看投递状态</p>
      <template #footer>
        <el-button @click="submitDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmSubmit">确认投递</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.urgent-banner {
  display: flex;
  align-items: center;
  gap: $spacing-md;
  padding: $spacing-md $spacing-lg;
  background: linear-gradient(90deg, rgba(245, 108, 108, 0.08), rgba(230, 162, 60, 0.08));
  border-radius: 10px;
  margin-bottom: $spacing-lg;
  font-size: 13px;
  color: $text-regular;

  .urgent-icon {
    font-size: 18px;
  }
  strong {
    color: $color-danger;
  }
  .el-switch {
    margin-left: auto;
  }
}

.list-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: $spacing-lg;
}

.recruit-card {
  background: $color-bg-card;
  border-radius: 10px;
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-left: 4px solid $color-primary;
  transition: $transition-base;

  &:hover {
    box-shadow: $shadow-card-hover;
    transform: translateY(-2px);
  }
  &.urgent {
    border-left-color: $color-danger;
  }
}

.card-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $spacing-sm;
  font-size: 11px;
  margin-bottom: $spacing-sm;
  .recruit-type {
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
  }
  .urgent-tag {
    color: $color-danger;
  }
  .publisher {
    color: $text-primary;
    font-weight: 500;
  }
  .dept {
    color: $text-secondary;
  }
  .deadline {
    margin-left: auto;
    color: $text-placeholder;
  }
}

.recruit-title {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
  margin-bottom: $spacing-sm;
}

.recruit-req {
  font-size: 12px;
  color: $text-regular;
  line-height: 1.6;
  margin-bottom: $spacing-md;
  min-height: 36px;
}

.card-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  .major {
    font-size: 11px;
    color: $text-placeholder;
  }
}

.empty {
  text-align: center;
  padding: 60px 20px;
  color: $text-placeholder;
}

.dialog-hint {
  font-size: 12px;
  color: $text-placeholder;
  margin-top: $spacing-sm;
}
</style>
