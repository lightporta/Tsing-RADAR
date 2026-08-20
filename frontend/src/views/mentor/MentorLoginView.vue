<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SubPageLayout from '@/layouts/SubPageLayout.vue'
import { mentorLogin, sendMentorEmailCode } from '@/api/mentor'
import { useMentorStore } from '@/stores/useMentorStore'

// =====================================================================
// 导师登录页：清华邮箱验证码登录。
// 验证码通过后把当前 Web 会话绑定到导师账号（后端 opaque 会话）。
// =====================================================================

const router = useRouter()
const mentorStore = useMentorStore()

const email = ref('')
const code = ref('')
const sending = ref(false)
const loggingIn = ref(false)
const countdown = ref(0)
const emailTouched = ref(false)
const codeTouched = ref(false)

function validateEmail() {
  const value = email.value.trim()
  if (!value) return '请输入邮箱'
  if (!/^[^@\s]+@tsinghua\.edu\.cn$/i.test(value)) return '仅支持 @tsinghua.edu.cn 邮箱'
  return ''
}

function validateCode() {
  if (!/^\d{6}$/.test(code.value.trim())) return '请输入 6 位验证码'
  return ''
}

let timer: ReturnType<typeof setInterval> | null = null

async function sendCode() {
  const error = validateEmail()
  if (error) {
    ElMessage.warning(error)
    return
  }
  sending.value = true
  try {
    await sendMentorEmailCode(email.value.trim())
    ElMessage.success('验证码已发送，请查收邮箱（60 秒后可重发）')
    countdown.value = 60
    if (timer) clearInterval(timer)
    timer = setInterval(() => {
      countdown.value -= 1
      if (countdown.value <= 0 && timer) {
        clearInterval(timer)
        timer = null
      }
    }, 1000)
  } finally {
    sending.value = false
  }
}

async function login() {
  if (loggingIn.value) return
  const emailErrorText = validateEmail()
  const codeErrorText = validateCode()
  if (emailErrorText) {
    ElMessage.warning(emailErrorText)
    return
  }
  if (codeErrorText) {
    ElMessage.warning(codeErrorText)
    return
  }
  loggingIn.value = true
  try {
    const result = await mentorLogin(email.value.trim(), code.value.trim())
    mentorStore.status = result
    ElMessage.success('登录成功')
    if (result.status === 'claimed') {
      router.push('/mentor/dashboard')
    } else {
      router.push('/mentor/claim')
    }
  } finally {
    loggingIn.value = false
  }
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <SubPageLayout title="导师登录 · Tsing-RADAR">
    <div class="login-view">
      <div class="login-card">
        <h1 class="login-title">导师服务</h1>
        <p class="login-desc">
          使用清华邮箱验证码登录，认领并维护您的公开档案。
        </p>
        <el-form label-position="top" @submit.prevent="login">
          <el-form-item label="清华邮箱">
            <el-input
              v-model="email"
              placeholder="name@tsinghua.edu.cn"
              autocomplete="email"
              @blur="emailTouched = true"
            >
              <template #prefix><el-icon aria-hidden="true">✉</el-icon></template>
            </el-input>
            <p v-if="emailTouched && validateEmail()" class="form-error">
              {{ validateEmail() }}
            </p>
          </el-form-item>
          <el-form-item label="验证码">
            <div class="code-row">
              <el-input
                v-model="code"
                placeholder="6 位验证码"
                maxlength="6"
                @blur="codeTouched = true"
              />
              <el-button :disabled="countdown > 0" :loading="sending" @click="sendCode">
                {{ countdown > 0 ? `${countdown}s 后重发` : '发送验证码' }}
              </el-button>
            </div>
            <p v-if="codeTouched && validateCode()" class="form-error">
              {{ validateCode() }}
            </p>
          </el-form-item>
          <el-button
            type="primary"
            class="login-submit"
            :loading="loggingIn"
            native-type="submit"
          >
            登录
          </el-button>
        </el-form>
      </div>
    </div>
  </SubPageLayout>
</template>

<style scoped lang="scss">
.login-view {
  padding: $spacing-xl $spacing-lg;
}
.login-card {
  max-width: 420px;
  margin: $spacing-xl auto;
  padding: $spacing-xl;
  border: 1px solid $color-border-light;
  border-radius: 14px;
  background: $color-bg-card;
}
.login-title {
  color: $text-primary;
  font-size: 20px;
  font-weight: 700;
}
.login-desc {
  margin: $spacing-sm 0 $spacing-lg;
  color: $text-secondary;
  font-size: 12px;
  line-height: 1.6;
}
.code-row {
  display: flex;
  gap: $spacing-sm;
  width: 100%;
}
.form-error {
  margin-top: 6px;
  color: #b4442e;
  font-size: 12px;
}
.login-submit {
  width: 100%;
  margin-top: $spacing-sm;
}
</style>
