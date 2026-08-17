<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getHardConstraintCapabilities } from '@/api/interview'
import { useChatStore } from '@/stores/useChatStore'
import type {
  HardConstraintField,
  HardConstraintCapability,
  HardConstraintOperator,
  InterviewPortrait,
} from '@/types/interview'

const chatStore = useChatStore()
const saving = ref(false)
const capabilityLoading = ref(false)
const constraintCapabilities = ref<HardConstraintCapability[]>([])
const capabilityError = ref('')
const interestsText = ref('')
const unresolvedConstraintsText = ref('')
const draftConstraints = ref<InterviewPortrait['draft_hard_constraints']>([])
interface ConstraintRow {
  field: HardConstraintField
  operator: HardConstraintOperator
  valueText: string
  source_text?: string | null
}
const constraintRows = ref<ConstraintRow[]>([])
const form = reactive<
  Pick<
    InterviewPortrait,
    'research_mode' | 'mentorship_style' | 'career_orientation' | 'innovation_risk'
  >
>({
  research_mode: 'undecided',
  mentorship_style: 'undecided',
  career_orientation: 'undecided',
  innovation_risk: 'undecided',
})

const availableCapabilities = computed(() =>
  constraintCapabilities.value.filter((item) => item.available),
)

function capabilityFor(field: HardConstraintField) {
  return constraintCapabilities.value.find((item) => item.field === field)
}

function operatorsFor(field: HardConstraintField) {
  return capabilityFor(field)?.operators || []
}

function operatorLabel(operator: HardConstraintOperator) {
  return {
    equals: '等于',
    one_of: '任一',
    excludes: '排除',
    contains: '包含',
    minimum: '至少',
    maximum: '至多',
  }[operator]
}

function changeConstraintField(row: ConstraintRow) {
  const operators = operatorsFor(row.field)
  if (!operators.includes(row.operator)) row.operator = operators[0] || 'equals'
}

watch(
  () => chatStore.profile,
  (profile) => {
    if (!profile) return
    interestsText.value = profile.research_interests.join('、')
    unresolvedConstraintsText.value = (profile.unresolved_hard_constraints || []).join('；')
    draftConstraints.value = (profile.draft_hard_constraints || []).map((draft) => ({
      ...draft,
      proposed_constraint: draft.proposed_constraint
        ? { ...draft.proposed_constraint, value: [...draft.proposed_constraint.value] }
        : null,
    }))
    constraintRows.value = (profile.hard_constraints || []).map((constraint) => ({
      field: constraint.field,
      operator: constraint.operator,
      valueText: constraint.value.join('、'),
      source_text: constraint.source_text,
    }))
    form.research_mode = profile.research_mode || 'undecided'
    form.mentorship_style = profile.mentorship_style || 'undecided'
    form.career_orientation = profile.career_orientation || 'undecided'
    form.innovation_risk = profile.innovation_risk || 'undecided'
  },
  { immediate: true, deep: true },
)

function splitValues(value: string): string[] {
  return value
    .split(/[，,、；;\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function addConstraint() {
  const capability = availableCapabilities.value[0]
  if (!capability) {
    ElMessage.warning('当前导师数据没有可用于硬约束的已核验证据字段')
    return
  }
  constraintRows.value.push({
    field: capability.field,
    operator: capability.operators[0],
    valueText: '',
  })
}

function resolveDraft(index: number, accept: boolean) {
  const draft = draftConstraints.value[index]
  if (accept && draft.proposed_constraint) {
    constraintRows.value.push({
      field: draft.proposed_constraint.field,
      operator: draft.proposed_constraint.operator,
      valueText: draft.proposed_constraint.value.join('、'),
      source_text: draft.source_text,
    })
  }
  const unresolved = splitValues(unresolvedConstraintsText.value).filter(
    (item) => item !== draft.source_text,
  )
  unresolvedConstraintsText.value = unresolved.join('；')
  draftConstraints.value.splice(index, 1)
}

async function save() {
  if (capabilityLoading.value) {
    ElMessage.warning('正在读取硬约束能力，请稍候')
    return
  }
  const invalidRow = constraintRows.value.find((row) => {
    const capability = capabilityFor(row.field)
    return (
      !splitValues(row.valueText).length ||
      !capability?.available ||
      !capability.operators.includes(row.operator)
    )
  })
  if (invalidRow) {
    ElMessage.error('硬约束不能为空，且字段与比较方式必须由当前证据能力支持')
    return
  }
  saving.value = true
  try {
    await chatStore.updateInterviewProfile({
      research_interests: splitValues(interestsText.value),
      interest_statement: interestsText.value.trim() || null,
      research_mode: form.research_mode,
      mentorship_style: form.mentorship_style,
      career_orientation: form.career_orientation,
      innovation_risk: form.innovation_risk,
      hard_constraints: constraintRows.value
        .filter((row) => splitValues(row.valueText).length)
        .map((row) => ({
          field: row.field,
          operator: row.operator,
          value: splitValues(row.valueText),
          source_text: row.source_text || null,
        })),
      draft_hard_constraints: draftConstraints.value,
      unresolved_hard_constraints: splitValues(unresolvedConstraintsText.value),
    })
    ElMessage.success('访谈画像已保存，请重新确认')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  capabilityLoading.value = true
  capabilityError.value = ''
  try {
    const response = await getHardConstraintCapabilities()
    constraintCapabilities.value = response.fields
  } catch {
    constraintCapabilities.value = []
    capabilityError.value = '硬约束能力读取失败，为避免无证据筛选，暂不能新增或保存硬约束。'
  } finally {
    capabilityLoading.value = false
  }
})

async function confirm() {
  saving.value = true
  try {
    await chatStore.confirmInterviewProfile()
    ElMessage.success('画像已确认')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <details v-if="chatStore.profile" class="profile-card">
    <summary>
      <span>访谈画像</span>
      <span class="status" :class="chatStore.interviewStatus">
        {{
          chatStore.interviewStatus === 'confirmed'
            ? '已确认'
            : chatStore.needsConfirmation
              ? '待确认'
              : '收集中'
        }}
      </span>
    </summary>

    <div class="form-grid">
      <label>
        <span>研究兴趣</span>
        <el-input v-model="interestsText" placeholder="用逗号分隔 1—3 个方向" />
      </label>
      <label>
        <span>研究方式</span>
        <el-select v-model="form.research_mode">
          <el-option label="理论与原理" value="theory" />
          <el-option label="工程与落地" value="engineering" />
          <el-option label="两者结合" value="mixed" />
          <el-option label="暂不确定" value="undecided" />
        </el-select>
      </label>
      <label>
        <span>指导偏好</span>
        <el-select v-model="form.mentorship_style">
          <el-option label="高频具体指导" value="high_guidance" />
          <el-option label="平衡" value="balanced" />
          <el-option label="自主探索" value="autonomous" />
          <el-option label="暂不确定" value="undecided" />
        </el-select>
      </label>
      <label>
        <span>生涯方向</span>
        <el-select v-model="form.career_orientation">
          <el-option label="学术深造" value="academic" />
          <el-option label="产业就业" value="industry" />
          <el-option label="国家任务" value="national_mission" />
          <el-option label="混合选择" value="mixed" />
          <el-option label="暂不确定" value="undecided" />
        </el-select>
      </label>
      <label>
        <span>创新风险</span>
        <el-select v-model="form.innovation_risk">
          <el-option label="高风险新方向" value="pioneering" />
          <el-option label="平衡" value="balanced" />
          <el-option label="成熟路径" value="mature" />
          <el-option label="暂不确定" value="undecided" />
        </el-select>
      </label>
      <div v-if="draftConstraints.length" class="draft-constraints">
        <span>待你确认的硬约束理解</span>
        <div v-for="(draft, index) in draftConstraints" :key="draft.draft_id" class="draft-row">
          <p>{{ draft.confirmation_prompt }}</p>
          <el-button
            size="small"
            type="primary"
            :disabled="!draft.proposed_constraint"
            @click="resolveDraft(index, true)"
          >
            确认并加入
          </el-button>
          <el-button size="small" @click="resolveDraft(index, false)">不作为硬约束</el-button>
        </div>
      </div>
      <div class="constraint-editor">
        <span>已确认的结构化硬约束</span>
        <p class="capability-note" aria-live="polite">
          {{
            capabilityError ||
              `当前 ${availableCapabilities.length}/${constraintCapabilities.length} 个字段有已核验证据`
          }}
        </p>
        <div v-for="(row, index) in constraintRows" :key="index" class="constraint-row">
          <el-select
            v-model="row.field"
            aria-label="约束字段"
            @change="changeConstraintField(row)"
          >
            <el-option
              v-for="capability in constraintCapabilities"
              :key="capability.field"
              :label="`${capability.label}${capability.available ? '' : '（暂无证据）'}`"
              :value="capability.field"
              :disabled="!capability.available"
            />
          </el-select>
          <el-select v-model="row.operator" aria-label="比较方式">
            <el-option
              v-for="operator in operatorsFor(row.field)"
              :key="operator"
              :label="operatorLabel(operator)"
              :value="operator"
            />
          </el-select>
          <el-input v-model="row.valueText" placeholder="多个值用逗号分隔" />
          <el-button text type="danger" @click="constraintRows.splice(index, 1)">删除</el-button>
        </div>
        <el-button
          size="small"
          :loading="capabilityLoading"
          :disabled="!availableCapabilities.length"
          @click="addConstraint"
        >
          添加结构化约束
        </el-button>
      </div>
      <label class="unresolved-constraints">
        <span>待澄清原文（清空表示明确放弃；保留则不能确认）</span>
        <el-input
          v-model="unresolvedConstraintsText"
          type="textarea"
          placeholder="请把每条原文转写到上方 field / operator / value 后清空"
        />
      </label>
    </div>

    <div class="actions">
      <el-button size="small" :loading="saving" @click="save">保存修改</el-button>
      <el-button
        v-if="chatStore.needsConfirmation"
        type="primary"
        size="small"
        :loading="saving"
        :disabled="Boolean(unresolvedConstraintsText.trim()) || draftConstraints.length > 0"
        @click="confirm"
      >
        确认画像
      </el-button>
    </div>
  </details>
</template>

<style scoped lang="scss">
.profile-card {
  flex-shrink: 0;
  border-top: 1px solid $color-border-light;
  background: rgba(64, 158, 255, 0.04);
  padding: $spacing-sm $spacing-lg;

  summary {
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    color: $text-primary;
    font-size: 13px;
    font-weight: 600;
  }
}

.status {
  font-size: 11px;
  font-weight: 500;
  color: $text-placeholder;

  &.awaiting_confirmation {
    color: $color-warning;
  }
  &.confirmed {
    color: $color-success;
  }
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: $spacing-sm;
  padding-top: $spacing-sm;

  label {
    min-width: 0;
    font-size: 11px;
    color: $text-secondary;

    > span {
      display: block;
      margin-bottom: 3px;
    }
  }
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: $spacing-sm;
  padding-top: $spacing-sm;
}

.constraint-editor {
  grid-column: 1 / -1;
  font-size: 11px;
  color: $text-secondary;
}

.capability-note {
  margin: 3px 0;
  color: $text-placeholder;
}

.draft-constraints {
  grid-column: 1 / -1;
  padding: $spacing-xs;
  border: 1px solid rgba(230, 162, 60, 0.35);
  border-radius: 6px;
  color: $color-warning;
}

.draft-row {
  display: flex;
  align-items: center;
  gap: $spacing-xs;
  margin-top: 4px;

  p {
    flex: 1;
    margin: 0;
  }
}

.constraint-row {
  display: grid;
  grid-template-columns: 1.1fr 0.8fr 1.4fr auto;
  gap: $spacing-xs;
  margin: 4px 0;
}

.unresolved-constraints {
  grid-column: 1 / -1;
  color: $color-warning !important;
}

@media (max-width: $bp-tablet) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .constraint-row {
    grid-template-columns: 1fr;
  }
}
</style>
