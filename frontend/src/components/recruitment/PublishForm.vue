<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { publishRecruitment } from '@/api/recruitment'
import { useUserStore } from '@/stores/useUserStore'

// =====================================================================
// 发布招募表单（文档 §6.3 POST /api/recruitments）
// =====================================================================

const userStore = useUserStore()
const dialogVisible = ref(false)
const publishing = ref(false)

const form = ref({
  publisher_id: '',
  type: '招生',
  title: '',
  req: '',
  major: '',
  deadline: '',
  is_urgent: false,
})

const types = ['招生', '实习', '科研助理']

function open() {
  form.value = {
    publisher_id: userStore.profile.name || '',
    type: '招生',
    title: '',
    req: '',
    major: '',
    deadline: '',
    is_urgent: false,
  }
  dialogVisible.value = true
}

async function publish() {
  if (!form.value.title || !form.value.req) {
    ElMessage.warning('请填写标题与要求')
    return
  }
  publishing.value = true
  try {
    await publishRecruitment(form.value)
    ElMessage.success('招募发布成功')
    dialogVisible.value = false
  } catch {
    // 错误提示由拦截器处理
  } finally {
    publishing.value = false
  }
}
</script>

<template>
  <div class="publish-form">
    <el-button type="primary" plain @click="open">
      <el-icon><EditPen /></el-icon>
      发布招募
    </el-button>

    <el-dialog v-model="dialogVisible" title="发布招募信息" width="500px">
      <el-form :model="form" label-width="80px" label-position="left">
        <el-form-item label="发布者">
          <el-input v-model="form.publisher_id" placeholder="导师姓名 / 学长学姐" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type">
            <el-option v-for="t in types" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="招募标题" />
        </el-form-item>
        <el-form-item label="要求">
          <el-input v-model="form.req" type="textarea" :rows="3" placeholder="招募要求与职责" />
        </el-form-item>
        <el-form-item label="专业板块">
          <el-input v-model="form.major" placeholder="相关专业领域" />
        </el-form-item>
        <el-form-item label="截止日期">
          <el-date-picker v-model="form.deadline" type="date" value-format="YYYY-MM-DD" placeholder="选择截止日期" />
        </el-form-item>
        <el-form-item label="急招">
          <el-switch v-model="form.is_urgent" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="publishing" @click="publish">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.publish-form {
  display: inline-flex;
}
</style>
