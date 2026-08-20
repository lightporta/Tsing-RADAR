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
import {
  analyzePrivateDocument,
  interpretSelectedDocumentText,
  type DocumentFactField,
  type ParsedDocumentFact,
} from '@/api/documentAnalysis'
import { newIdempotencyKey } from '@/api/request'
import { formatBytes } from '@/utils/format'
import { useChatStore } from '@/stores/useChatStore'
import { useUserStore } from '@/stores/useUserStore'
import type { StudentProfile } from '@/types/user'

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
const analyzingDocumentId = ref<string | null>(null)
const analysisDocument = ref<PrivateDocument | null>(null)
const analysisFacts = ref<ParsedDocumentFact[]>([])
const selectedDiffFields = ref<DocumentFactField[]>([])
const selectedGlmFields = ref<DocumentFactField[]>([])
const glmDrafts = ref<Partial<Record<DocumentFactField, string>>>({})
const glmConsent = ref(false)
const interpreting = ref(false)
const glmInterpretation = ref('')
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

function displayFactValue(value: string | string[]) {
  return Array.isArray(value) ? value.join('、') : value
}

function currentProfileValue(field: DocumentFactField) {
  if (field === 'awards') return splitLines(awardsText.value).join('、')
  if (field === 'positions') return splitLines(positionsText.value).join('、')
  if (field === 'research_experience') {
    return projectDetail.value.trim() || userStore.profile.research_experience || ''
  }
  const value = userStore.profile[field]
  return Array.isArray(value) ? value.join('、') : String(value || '')
}

function factChanged(fact: ParsedDocumentFact) {
  return currentProfileValue(fact.field).trim() !== displayFactValue(fact.value).trim()
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

async function analyzeDocument(item: PrivateDocument) {
  if (analyzingDocumentId.value) return
  analyzingDocumentId.value = item.document_id
  try {
    const result = await analyzePrivateDocument(item.document_id)
    analysisDocument.value = item
    analysisFacts.value = result.facts
    selectedDiffFields.value = []
    selectedGlmFields.value = []
    glmConsent.value = false
    glmInterpretation.value = ''
    glmDrafts.value = Object.fromEntries(
      result.facts.map((fact) => [
        fact.field,
        fact.source_excerpt,
      ]),
    ) as Partial<Record<DocumentFactField, string>>
    if (!result.facts.length) {
      ElMessage.info('未识别到带明确标签的个人事实，系统不会猜测或补写')
    }
  } finally {
    analyzingDocumentId.value = null
  }
}

function assignProfileFact(
  patch: Partial<StudentProfile>,
  fact: ParsedDocumentFact,
) {
  if (fact.field === 'interest_tags') {
    patch.interest_tags = Array.isArray(fact.value) ? fact.value : [fact.value]
    return
  }
  const value = Array.isArray(fact.value) ? fact.value.join('、') : fact.value
  if (fact.field === 'awards') {
    awardsText.value = Array.isArray(fact.value) ? fact.value.join('\n') : fact.value
    return
  }
  if (fact.field === 'positions') {
    positionsText.value = Array.isArray(fact.value) ? fact.value.join('\n') : fact.value
    return
  }
  if (fact.field === 'name') patch.name = value
  if (fact.field === 'email') patch.email = value
  if (fact.field === 'phone') patch.phone = value
  if (fact.field === 'dept') patch.dept = value
  if (fact.field === 'grade') patch.grade = value
  if (fact.field === 'gpa') patch.gpa = value
  if (fact.field === 'research_interest') patch.research_interest = value
  if (fact.field === 'research_experience') {
    patch.research_experience = value
    projectDetail.value = value
  }
}

async function applySelectedFacts() {
  const facts = analysisFacts.value.filter((fact) =>
    selectedDiffFields.value.includes(fact.field),
  )
  if (!facts.length) {
    ElMessage.warning('请逐项勾选需要回填的事实')
    return
  }
  try {
    await ElMessageBox.confirm(
      `仅将你勾选的 ${facts.length} 项事实写入个人信息？`,
      '确认逐项回填',
      { confirmButtonText: '确认回填', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  const patch: Partial<StudentProfile> = {}
  facts.forEach((fact) => assignProfileFact(patch, fact))
  userStore.updateProfile(patch)
  selectedDiffFields.value = []
  ElMessage.success('已回填所选事实；未勾选项保持不变')
}

async function interpretSelection() {
  if (interpreting.value) return
  if (!analysisDocument.value || !selectedGlmFields.value.length) {
    ElMessage.warning('请先选择要发送给 GLM 的文本')
    return
  }
  if (!glmConsent.value) {
    ElMessage.warning('请明确授权本次 GLM 解读')
    return
  }
  const selections = selectedGlmFields.value.map((field) => ({
    field,
    selected_text: (glmDrafts.value[field] || '').trim(),
  }))
  if (selections.some((item) => !item.selected_text)) {
    ElMessage.warning('选定文本不能为空')
    return
  }
  interpreting.value = true
  try {
    const result = await interpretSelectedDocumentText(
      analysisDocument.value.document_id,
      selections,
    )
    glmInterpretation.value = result.interpretation
    ElMessage.success('GLM 已完成本次解读；上下文未保存')
  } finally {
    // 授权仅限单次调用；成功或失败后的重试都必须再次确认。
    glmConsent.value = false
    interpreting.value = false
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
    if (analysisDocument.value?.document_id === item.document_id) {
      analysisDocument.value = null
      analysisFacts.value = []
      glmInterpretation.value = ''
    }
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
    ElMessage.warning('请先在上方填写姓名并保存基本信息')
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
        我确认以上内容及本机个人信息由我提供，并同意在当前私有会话生成文件
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
            v-if="item.document_kind === 'upload' && item.status === 'ready' && item.scan_status === 'clean'"
            size="small"
            plain
            :loading="analyzingDocumentId === item.document_id"
            @click="analyzeDocument(item)"
          >
            解析并对比
          </el-button>
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

    <section
      v-if="analysisDocument"
      class="analysis-panel"
      aria-labelledby="document-analysis-title"
    >
      <div>
        <h3 id="document-analysis-title" class="section-title">事实对比与确认回填</h3>
        <p class="privacy-note">
          {{ analysisDocument.original_name }} 仅在私有环境按需解析；抽取正文与本次分析结果不写入数据库，也未调用外部模型。
        </p>
      </div>
      <el-alert
        title="系统只提取带明确标签的事实，不会猜测缺失信息。请逐项勾选后再回填。"
        type="info"
        :closable="false"
        show-icon
      />
      <el-checkbox-group v-model="selectedDiffFields" class="diff-list" aria-label="选择要回填的事实">
        <article v-for="fact in analysisFacts" :key="fact.field" class="diff-item">
          <el-checkbox :value="fact.field" :aria-label="`确认回填${fact.label}`">
            {{ fact.label }}
          </el-checkbox>
          <dl>
            <div><dt>当前值</dt><dd>{{ currentProfileValue(fact.field) || '未填写' }}</dd></div>
            <div>
              <dt>解析值</dt>
              <dd :class="{ changed: factChanged(fact) }">{{ displayFactValue(fact.value) }}</dd>
            </div>
            <div class="source-row"><dt>来源片段</dt><dd>{{ fact.source_excerpt }}</dd></div>
          </dl>
        </article>
      </el-checkbox-group>
      <p v-if="!analysisFacts.length" class="empty">未识别到可安全回填的明确事实。</p>
      <div class="builder-actions">
        <el-button
          type="primary"
          :disabled="!selectedDiffFields.length"
          @click="applySelectedFacts"
        >
          确认所选并回填
        </el-button>
        <span class="inline-hint">未勾选字段不会更改。</span>
      </div>

      <div v-if="analysisFacts.length" class="glm-panel" aria-labelledby="glm-analysis-title">
        <h3 id="glm-analysis-title" class="section-title">可选：GLM 单次解读</h3>
        <p class="privacy-note">
          默认不发送文件。只有下面勾选且可编辑的文本会在本次授权后发送给 GLM；不会切换到其他模型，也不保存模型上下文。
        </p>
        <el-checkbox-group v-model="selectedGlmFields" class="glm-selections" aria-label="选择发送给 GLM 的文本">
          <div v-for="fact in analysisFacts" :key="`glm-${fact.field}`" class="glm-selection">
            <el-checkbox :value="fact.field">{{ fact.label }}</el-checkbox>
            <el-input
              v-if="selectedGlmFields.includes(fact.field)"
              v-model="glmDrafts[fact.field]"
              type="textarea"
              :rows="2"
              maxlength="1200"
              show-word-limit
              :aria-label="`本次发送给 GLM 的${fact.label}文本`"
            />
          </div>
        </el-checkbox-group>
        <el-checkbox v-model="glmConsent" aria-label="明确授权本次选定文本发送给 GLM">
          我明确授权仅将上方勾选并确认的文本发送给 GLM 进行一次解读
        </el-checkbox>
        <div class="builder-actions">
          <el-button
            type="primary"
            plain
            :loading="interpreting"
            :disabled="!selectedGlmFields.length || !glmConsent"
            @click="interpretSelection"
          >
            授权本次 GLM 解读
          </el-button>
          <span class="inline-hint">失败时会明确提示；重试必须重新勾选授权，不会切换模型。</span>
        </div>
        <div v-if="glmInterpretation" class="glm-result" role="status" aria-live="polite">
          <strong>GLM 本次解读</strong>
          <p>{{ glmInterpretation }}</p>
        </div>
      </div>
    </section>

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

.analysis-panel {
  display: grid;
  gap: $spacing-md;
  margin-top: $spacing-xl;
  padding: $spacing-lg;
  border: 1px solid rgba(64, 158, 255, 0.28);
  border-radius: 10px;
  background: rgba(64, 158, 255, 0.035);
}

.diff-list,
.glm-selections {
  display: grid;
  gap: $spacing-sm;
}

.diff-item {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: $spacing-sm;
  padding: $spacing-md;
  border: 1px solid $color-border-light;
  border-radius: 8px;
  background: $color-bg-card;
}

.diff-item dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px $spacing-md;
}

.diff-item .source-row { grid-column: 1 / -1; }
.diff-item dt { color: $text-placeholder; font-size: 10px; }
.diff-item dd { margin-top: 2px; color: $text-regular; font-size: 12px; overflow-wrap: anywhere; }
.diff-item dd.changed { color: $color-primary; font-weight: 600; }

.glm-panel {
  display: grid;
  gap: $spacing-md;
  margin-top: $spacing-md;
  padding-top: $spacing-lg;
  border-top: 1px solid $color-border-light;
}

.glm-selection {
  display: grid;
  gap: 6px;
}

.glm-result {
  padding: $spacing-md;
  border-radius: 8px;
  color: $text-regular;
  background: $color-bg-card;
  font-size: 12px;
  line-height: 1.7;
}

.glm-result p { margin-top: 4px; white-space: pre-wrap; }

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
  .analysis-panel { padding: $spacing-md; }
  .diff-item { grid-template-columns: 1fr; }
  .diff-item dl { grid-template-columns: 1fr; }
  .diff-item .source-row { grid-column: auto; }
}
</style>
