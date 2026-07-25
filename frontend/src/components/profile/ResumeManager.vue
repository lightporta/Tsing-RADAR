<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/useUserStore'
import { generateResume } from '@/api/resume'
import { genId } from '@/utils/format'
import type { Resume, ResumeEntry } from '@/types/user'

// =====================================================================
// 简历智能管理（文档 §2.1.6 / §6.3）
// - 简历列表（查看 / 编辑 / 删除 / 下载）
// - LLM 自动生成打磨
// - 定向导师个性化包装
// =====================================================================

const userStore = useUserStore()

const dialogVisible = ref(false)
const generating = ref(false)
const editingId = ref<string | null>(null)

const form = ref({
  title: '',
  target_advisor: '',
  projects: [{ name: '', detail: '' }],
  awards: [''],
  positions: [''],
})

function openCreate() {
  editingId.value = null
  form.value = {
    title: `${userStore.profile.name || '同学'}-个人简历`,
    target_advisor: '',
    projects: [{ name: '', detail: '' }],
    awards: [''],
    positions: [''],
  }
  dialogVisible.value = true
}

function addEntry(arr: ResumeEntry[] | Array<{ name: string; detail: string } | string>, type: 'project' | 'award' | 'position') {
  if (type === 'project') {
    ;(arr as Array<{ name: string; detail: string }>).push({ name: '', detail: '' })
  } else {
    ;(arr as string[]).push('')
  }
}

function removeEntry(arr: unknown[], idx: number) {
  arr.splice(idx, 1)
}

async function generate() {
  if (generating.value) return
  generating.value = true
  try {
    const profile = userStore.profile
    const res = await generateResume({
      student_name: profile.name || '同学',
      dept: profile.dept,
      email: profile.email,
      phone: profile.phone || '',
      projects: form.value.projects.filter((p) => p.name),
      awards: form.value.awards.filter(Boolean),
      positions: form.value.positions.filter(Boolean),
      target_advisor: form.value.target_advisor || undefined,
    })

    const entries: ResumeEntry[] = [
      ...form.value.projects
        .filter((p) => p.name)
        .map((p) => ({ id: genId('entry'), type: 'project' as const, title: p.name, detail: p.detail })),
      ...form.value.awards
        .filter(Boolean)
        .map((a) => ({ id: genId('entry'), type: 'award' as const, title: a, detail: '' })),
      ...form.value.positions
        .filter(Boolean)
        .map((p) => ({ id: genId('entry'), type: 'position' as const, title: p, detail: '' })),
    ]

    const resume: Resume = {
      resume_id: editingId.value || genId('resume'),
      title: res.title || form.value.title,
      content: entries,
      polished_text: res.polished_text,
      target_advisor: form.value.target_advisor || undefined,
      created_at: Date.now(),
    }
    userStore.upsertResume(resume)
    dialogVisible.value = false
    ElMessage.success('简历已生成')
  } catch {
    // 错误已由拦截器提示
  } finally {
    generating.value = false
  }
}

function editResume(r: Resume) {
  editingId.value = r.resume_id
  form.value = {
    title: r.title,
    target_advisor: r.target_advisor || '',
    projects: r.content.filter((e) => e.type === 'project').map((e) => ({ name: e.title, detail: e.detail })),
    awards: r.content.filter((e) => e.type === 'award').map((e) => e.title),
    positions: r.content.filter((e) => e.type === 'position').map((e) => e.title),
  }
  dialogVisible.value = true
}

async function deleteResume(r: Resume) {
  try {
    await ElMessageBox.confirm(`确定删除简历「${r.title}」？`, '删除简历', {
      type: 'warning',
    })
    userStore.removeResume(r.resume_id)
    ElMessage.success('已删除')
  } catch {
    // cancel
  }
}

function downloadResume(r: Resume) {
  const blob = new Blob([r.polished_text], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${r.title}.md`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="resume-manager">
    <div class="manager-head">
      <h3 class="section-title">📄 我的简历</h3>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>
        新建简历
      </el-button>
    </div>

    <!-- 简历列表 -->
    <div v-if="userStore.resumes.length" class="resume-list">
      <div v-for="r in userStore.resumes" :key="r.resume_id" class="resume-item">
        <div class="resume-info">
          <h4 class="resume-title">{{ r.title }}</h4>
          <p v-if="r.target_advisor" class="resume-target">定向：{{ r.target_advisor }}</p>
          <p class="resume-time">{{ new Date(r.created_at).toLocaleString() }}</p>
        </div>
        <div class="resume-actions">
          <el-button size="small" @click="editResume(r)">编辑</el-button>
          <el-button size="small" @click="downloadResume(r)">
            <el-icon><Download /></el-icon>
          </el-button>
          <el-button size="small" type="danger" plain @click="deleteResume(r)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
    </div>
    <div v-else class="empty-resume">
      <p>还没有简历，点击「新建简历」让 AI 帮你生成</p>
    </div>

    <!-- 新建 / 编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑简历' : '新建简历'"
      width="600px"
    >
      <el-form :model="form" label-width="90px" label-position="left">
        <el-form-item label="简历标题">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="定向导师">
          <el-input v-model="form.target_advisor" placeholder="选填，定向包装用" />
        </el-form-item>

        <div class="entry-group">
          <div class="entry-head">
            <span>项目经历</span>
            <el-button text size="small" @click="addEntry(form.projects, 'project')">+ 添加</el-button>
          </div>
          <div v-for="(p, i) in form.projects" :key="i" class="entry-row">
            <el-input v-model="p.name" placeholder="项目名称" />
            <el-input v-model="p.detail" placeholder="项目详情" />
            <el-button text @click="removeEntry(form.projects, i)">✕</el-button>
          </div>
        </div>

        <div class="entry-group">
          <div class="entry-head">
            <span>获奖荣誉</span>
            <el-button text size="small" @click="addEntry(form.awards, 'award')">+ 添加</el-button>
          </div>
          <div v-for="(a, i) in form.awards" :key="i" class="entry-row">
            <el-input v-model="form.awards[i]" placeholder="奖项名称" />
            <el-button text @click="removeEntry(form.awards, i)">✕</el-button>
          </div>
        </div>

        <div class="entry-group">
          <div class="entry-head">
            <span>担任职务</span>
            <el-button text size="small" @click="addEntry(form.positions, 'position')">+ 添加</el-button>
          </div>
          <div v-for="(p, i) in form.positions" :key="i" class="entry-row">
            <el-input v-model="form.positions[i]" placeholder="职务名称" />
            <el-button text @click="removeEntry(form.positions, i)">✕</el-button>
          </div>
        </div>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="generate">
          <el-icon><MagicStick /></el-icon>
          AI 生成打磨
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.manager-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: $spacing-lg;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: $text-primary;
}

.resume-list {
  display: flex;
  flex-direction: column;
  gap: $spacing-md;
}

.resume-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $spacing-md $spacing-lg;
  background: $color-bg;
  border-radius: 8px;
  border: 1px solid $color-border-light;

  .resume-info {
    flex: 1;
    min-width: 0;
  }
  .resume-title {
    font-size: 14px;
    font-weight: 600;
    color: $text-primary;
  }
  .resume-target {
    font-size: 12px;
    color: $color-accent;
    margin-top: 2px;
  }
  .resume-time {
    font-size: 11px;
    color: $text-placeholder;
    margin-top: 2px;
  }
}
.resume-actions {
  display: flex;
  gap: $spacing-xs;
}

.empty-resume {
  text-align: center;
  padding: 40px 20px;
  color: $text-placeholder;
  font-size: 13px;
  background: $color-bg;
  border-radius: 8px;
}

.entry-group {
  margin-bottom: $spacing-lg;
  .entry-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: $spacing-sm;
    font-size: 13px;
    color: $text-regular;
  }
}
.entry-row {
  display: flex;
  gap: $spacing-sm;
  margin-bottom: $spacing-sm;
  :deep(.el-input) {
    flex: 1;
  }
}
</style>
