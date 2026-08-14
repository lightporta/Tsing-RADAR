<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteDocument,
  fetchApplications,
  fetchDocuments,
  generateMatchReport,
  issuePrivateDownload,
  redeemPrivateDownload,
  uploadDocument,
  withdrawApplication,
  type ApplicationRecord,
  type PrivateDocument,
} from '@/api/actions'
import { generateResume } from '@/api/resume'
import { newIdempotencyKey } from '@/api/request'
import { useChatStore } from '@/stores/useChatStore'
import { useUserStore } from '@/stores/useUserStore'

const chatStore = useChatStore()
const userStore = useUserStore()
const documents = ref<PrivateDocument[]>([])
const applications = ref<ApplicationRecord[]>([])
const loading = ref(false)
const uploading = ref(false)
const generating = ref<'resume' | 'report' | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const outputFormat = ref<'pdf' | 'docx'>('pdf')
const confirmGeneration = ref(false)
const projectDetail = ref('')
const awardsText = ref('')
const positionsText = ref('')
const targetAdvisor = ref('')
const downloadingDocumentId = ref<string | null>(null)
const deletingDocumentId = ref<string | null>(null)
const MAX_PRIVATE_FILE_BYTES = 8 * 1024 * 1024
type PendingIntent = { fingerprint: string; key: string }
const resumeIntent = ref<PendingIntent | null>(null)
const reportIntent = ref<PendingIntent | null>(null)
const downloadIntents = new Map<string, PendingIntent>()
const deleteIntents = new Map<string, PendingIntent>()

function ensureIntent(
  current: PendingIntent | null,
  operation: string,
  payload: unknown,
) {
  const fingerprint = JSON.stringify(payload)
  return current?.fingerprint === fingerprint
    ? current
    : { fingerprint, key: newIdempotencyKey(operation) }
}

const canGenerateResume = computed(
  () => Boolean(userStore.profile.name.trim()) && confirmGeneration.value,
)
const canGenerateReport = computed(
  () =>
    Boolean(chatStore.sessionId) &&
    chatStore.recommendReady &&
    confirmGeneration.value,
)

function formatBytes(value: number) {
  return value < 1024 * 1024
    ? `${Math.ceil(value / 1024)} KB`
    : `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function loadPrivateData() {
  loading.value = true
  try {
    ;[documents.value, applications.value] = await Promise.all([
      fetchDocuments(),
      fetchApplications(),
    ])
  } finally {
    loading.value = false
  }
}

function chooseFile() {
  fileInput.value?.click()
}

async function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!/\.(pdf|docx)$/i.test(file.name)) {
    ElMessage.warning('仅支持 PDF 或 DOCX 文件')
    return
  }
  if (file.size > MAX_PRIVATE_FILE_BYTES) {
    ElMessage.warning('文件不能超过 8 MB，请压缩后重新上传')
    return
  }
  uploading.value = true
  try {
    await uploadDocument(file)
    ElMessage.success('文件已私有上传并完成本地解析')
    await loadPrivateData()
  } finally {
    uploading.value = false
  }
}

async function removeFile(item: PrivateDocument) {
  if (deletingDocumentId.value) return
  deletingDocumentId.value = item.document_id
  try {
    await ElMessageBox.confirm(
      `删除私有文件「${item.original_name}」？此操作不可恢复。`,
      '删除文件',
      { type: 'warning' },
    )
    const intent = ensureIntent(
      deleteIntents.get(item.document_id) || null,
      'delete-document',
      { document_id: item.document_id, confirm_delete: true },
    )
    deleteIntents.set(item.document_id, intent)
    await deleteDocument(item.document_id, intent.key)
    deleteIntents.delete(item.document_id)
    ElMessage.success('私有对象、交付授权与元数据已同步清理')
  } finally {
    deletingDocumentId.value = null
    await loadPrivateData()
  }
}

async function download(item: PrivateDocument) {
  if (downloadingDocumentId.value) return
  downloadingDocumentId.value = item.document_id
  try {
    await ElMessageBox.confirm(
      `为「${item.original_name}」生成一次性私有下载链接？链接仅属于当前会话，不会公开或发送给第三方。`,
      '确认私有下载',
      { type: 'warning', confirmButtonText: '确认并下载' },
    )
    const intent = ensureIntent(
      downloadIntents.get(item.document_id) || null,
      'private-download',
      { document_id: item.document_id, confirm_private_download: true },
    )
    downloadIntents.set(item.document_id, intent)
    const grant = await issuePrivateDownload(item.document_id, intent.key)
    const downloaded = await redeemPrivateDownload(grant.download_url)
    const objectUrl = URL.createObjectURL(downloaded.blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = downloaded.filename
    anchor.rel = 'noopener'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
    downloadIntents.delete(item.document_id)
  } finally {
    downloadingDocumentId.value = null
  }
}

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function createResume() {
  if (generating.value) return
  if (!userStore.profile.name.trim()) {
    ElMessage.warning('请先在上方填写姓名并保存到当前页面内存')
    return
  }
  if (!confirmGeneration.value) {
    ElMessage.warning('请先确认生成范围')
    return
  }
  generating.value = 'resume'
  try {
    const request = {
      student_name: userStore.profile.name.trim(),
      dept: userStore.profile.dept,
      email: userStore.profile.email,
      phone: userStore.profile.phone || '',
      education: `${userStore.profile.category} · ${userStore.profile.grade}`,
      research_interests: userStore.profile.interest_tags,
      projects: projectDetail.value.trim()
        ? [{ name: '用户填写的项目或科研经历', detail: projectDetail.value.trim() }]
        : [],
      awards: splitLines(awardsText.value),
      positions: splitLines(positionsText.value),
      target_advisor: targetAdvisor.value.trim() || undefined,
      format: outputFormat.value,
      confirm_generation: true as const,
    }
    resumeIntent.value = ensureIntent(
      resumeIntent.value,
      'generate-resume',
      request,
    )
    await generateResume(request, resumeIntent.value.key)
    resumeIntent.value = null
    ElMessage.success('真实文档已生成、扫描并保存到当前私有会话')
    confirmGeneration.value = false
    await loadPrivateData()
  } finally {
    generating.value = null
  }
}

async function createReport() {
  if (generating.value) return
  if (!chatStore.sessionId || !chatStore.recommendReady) {
    ElMessage.warning('请先在访谈中逐项确认画像并完成匹配')
    return
  }
  if (!confirmGeneration.value) {
    ElMessage.warning('请先确认生成范围')
    return
  }
  generating.value = 'report'
  try {
    const request = {
      session_id: chatStore.sessionId,
      format: outputFormat.value,
      confirm_generation: true,
    }
    reportIntent.value = ensureIntent(
      reportIntent.value,
      'generate-match-report',
      request,
    )
    await generateMatchReport(
      chatStore.sessionId,
      outputFormat.value,
      reportIntent.value.key,
    )
    reportIntent.value = null
    ElMessage.success('匹配报告已按已确认画像与治理数据生成并私有保存')
    confirmGeneration.value = false
    await loadPrivateData()
  } finally {
    generating.value = null
  }
}

async function withdraw(item: ApplicationRecord) {
  await withdrawApplication(item.app_id)
  ElMessage.success('站内投递已撤回；系统从未向第三方发送文件')
  await loadPrivateData()
}

onMounted(loadPrivateData)
</script>

<template>
  <section class="resume-manager" aria-labelledby="private-documents-title">
    <div class="manager-head">
      <div>
        <h3 id="private-documents-title" class="section-title">私有简历与行动记录</h3>
        <p class="privacy-note">
          仅支持 PDF/DOCX，本地私有解析；当前不会向导师、邮箱或第三方发送文件。
        </p>
      </div>
      <input
        ref="fileInput"
        class="sr-only"
        type="file"
        aria-label="选择要私有上传的 PDF 或 DOCX 文件"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        @change="onFileSelected"
      />
      <el-button type="primary" :loading="uploading" @click="chooseFile">
        上传私有文件
      </el-button>
    </div>

    <section class="artifact-builder" aria-labelledby="artifact-builder-title">
      <div>
        <h3 id="artifact-builder-title" class="section-title">生成真实文档</h3>
        <p class="privacy-note">
          简历只排版你明确填写的信息，不调用模型补写经历；匹配报告只使用已确认画像与审核数据。
        </p>
      </div>
      <div class="builder-grid">
        <label>
          输出格式
          <el-select v-model="outputFormat" aria-label="输出格式">
            <el-option label="PDF" value="pdf" />
            <el-option label="DOCX" value="docx" />
          </el-select>
        </label>
        <label>
          目标导师（可选，不作事实核验）
          <el-input
            v-model="targetAdvisor"
            aria-label="目标导师"
            placeholder="仅原样排版你的输入"
          />
        </label>
      </div>
      <label>
        项目或科研经历（可选）
        <el-input
          v-model="projectDetail"
          type="textarea"
          :rows="2"
          aria-label="项目或科研经历"
          placeholder="只写你愿意确认并放入简历的事实"
        />
      </label>
      <div class="builder-grid">
        <label>
          奖项（可选，每行一项）
          <el-input
            v-model="awardsText"
            type="textarea"
            :rows="2"
            aria-label="奖项，每行一项"
          />
        </label>
        <label>
          职务（可选，每行一项）
          <el-input
            v-model="positionsText"
            type="textarea"
            :rows="2"
            aria-label="职务，每行一项"
          />
        </label>
      </div>
      <el-checkbox v-model="confirmGeneration" aria-label="确认信息并同意生成私有文件">
        我确认以上内容及当前页面个人信息由我提供，并同意在当前私有会话生成文件
      </el-checkbox>
      <div class="builder-actions">
        <el-button
          type="primary"
          :disabled="!canGenerateResume"
          :loading="generating === 'resume'"
          @click="createResume"
        >
          生成简历
        </el-button>
        <el-button
          :disabled="!canGenerateReport"
          :loading="generating === 'report'"
          @click="createReport"
        >
          生成匹配报告
        </el-button>
        <span v-if="!chatStore.recommendReady" class="inline-hint">
          匹配报告需先完成动态访谈、画像确认与匹配
        </span>
      </div>
    </section>

    <div v-loading="loading" class="private-grid">
      <article v-for="item in documents" :key="item.document_id" class="private-card">
        <div>
          <h4>{{ item.original_name }}</h4>
          <p>
            {{ formatBytes(item.size_bytes) }} · {{ item.document_kind }} ·
            状态 {{ item.status }} · SHA-256 {{ item.sha256.slice(0, 12) }}…
          </p>
          <p>
            扫描：
            {{
              item.scan_scope === 'full_antivirus'
                ? '完整反病毒 + 结构检查'
                : '结构与已知特征检查（非完整反病毒）'
            }}
          </p>
          <p v-if="item.text_preview" class="preview">{{ item.text_preview }}</p>
        </div>
        <div class="card-actions">
          <el-button
            v-if="item.status === 'ready' && item.scan_status === 'clean'"
            size="small"
            :loading="downloadingDocumentId === item.document_id"
            @click="download(item)"
          >
            私有下载
          </el-button>
          <el-button
            type="danger"
            plain
            size="small"
            :loading="deletingDocumentId === item.document_id"
            @click="removeFile(item)"
          >
            {{ item.status === 'delete_failed' || item.status === 'deleting' ? '重试删除' : '删除' }}
          </el-button>
        </div>
      </article>
      <p v-if="!loading && !documents.length" class="empty">
        尚未上传私有简历。上传后可在已审核招募下创建站内投递记录。
      </p>
    </div>

    <h3 class="section-title records-title">站内投递状态</h3>
    <div class="record-list">
      <article v-for="item in applications" :key="item.app_id" class="record-card">
        <div>
          <strong>{{ item.status === 'withdrawn' ? '已撤回' : '仅站内已记录' }}</strong>
          <p>招募 {{ item.recruit_id }} · 未向外发送</p>
        </div>
        <el-button
          v-if="item.status !== 'withdrawn'"
          size="small"
          @click="withdraw(item)"
        >
          撤回
        </el-button>
      </article>
      <p v-if="!applications.length" class="empty">暂无站内投递记录。</p>
    </div>
  </section>
</template>

<style scoped lang="scss">
.resume-manager {
  max-width: 800px;
  margin: $spacing-xl auto 0;
  padding: $spacing-xl;
  background: $color-bg-card;
  border-radius: 10px;
  box-shadow: $shadow-card;
}

.manager-head,
.private-card,
.record-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: $spacing-md;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
}

.privacy-note,
.private-card p,
.record-card p {
  margin-top: 4px;
  color: $text-secondary;
  font-size: 12px;
}

.private-grid,
.record-list {
  display: grid;
  gap: $spacing-sm;
  margin-top: $spacing-lg;
}

.artifact-builder {
  display: grid;
  gap: $spacing-md;
  margin-top: $spacing-xl;
  padding: $spacing-lg;
  border: 1px solid $color-border-light;
  border-radius: 8px;
  background: $color-bg;

  label {
    display: grid;
    min-width: 0;
    gap: 6px;
    color: $text-secondary;
    font-size: 12px;
  }
}

.builder-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: $spacing-md;
}

.artifact-builder :deep(.el-input),
.artifact-builder :deep(.el-select),
.artifact-builder :deep(.el-textarea) {
  width: 100%;
  min-width: 0;
}

.builder-actions,
.card-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $spacing-sm;
}

.inline-hint {
  color: $text-placeholder;
  font-size: 12px;
}

.private-card,
.record-card {
  padding: $spacing-md;
  border: 1px solid $color-border-light;
  border-radius: 8px;
}

.preview {
  max-width: 620px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.records-title {
  margin-top: $spacing-xl;
}

.empty {
  padding: $spacing-lg;
  text-align: center;
  color: $text-placeholder;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: $bp-tablet) {
  .manager-head,
  .private-card,
  .record-card {
    align-items: flex-start;
    flex-direction: column;
  }
  .builder-grid {
    grid-template-columns: 1fr;
  }
}
</style>
