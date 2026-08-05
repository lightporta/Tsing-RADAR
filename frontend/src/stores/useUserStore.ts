import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { StudentProfile, Resume } from '@/types/user'
import type { TraitKey } from '@/types/advisor'
import { TRAITS } from '@/types/advisor'

// =====================================================================
// 学生信息 Store（文档 §7.1 useUserStore）
// 会话级内存持有，不持久化敏感数据（隐私合规）
// =====================================================================

const DEFAULT_WEIGHTS = (): Record<TraitKey, number> =>
  TRAITS.reduce(
    (acc, t) => {
      const defaults: Record<TraitKey, number> = {
        acumen: 85,
        network: 60,
        mentorship: 90,
        tolerance: 70,
        funding: 50,
        efficiency: 75,
      }
      acc[t.key] = defaults[t.key]
      return acc
    },
    {} as Record<TraitKey, number>,
  )

export const useUserStore = defineStore('user', () => {
  const profile = ref<StudentProfile>({
    name: '',
    email: '',
    dept: '自动化系',
    category: '本科大三',
    grade: '2023级',
    phone: '',
    gpa: '',
    research_experience: '',
    research_interest: '',
    interest_tags: ['自然语言处理', '机器学习'],
    weights: DEFAULT_WEIGHTS(),
  })

  const resumes = ref<Resume[]>([])

  /** 是否已完善基本信息（用于匹配前提示） */
  const isProfileComplete = computed(
    () => !!profile.value.name && !!profile.value.dept && profile.value.interest_tags.length > 0,
  )

  /** 更新个人信息 */
  function updateProfile(patch: Partial<StudentProfile>) {
    profile.value = { ...profile.value, ...patch }
  }

  /** 设置某维度权重（归一化由后端处理，前端原值存储） */
  function setWeight(key: TraitKey, value: number) {
    profile.value.weights[key] = value
  }

  /** 新增 / 更新简历 */
  function upsertResume(resume: Resume) {
    const idx = resumes.value.findIndex((r) => r.resume_id === resume.resume_id)
    if (idx >= 0) resumes.value[idx] = resume
    else resumes.value.unshift(resume)
  }

  function removeResume(id: string) {
    resumes.value = resumes.value.filter((r) => r.resume_id !== id)
  }

  return {
    profile,
    resumes,
    isProfileComplete,
    updateProfile,
    setWeight,
    upsertResume,
    removeResume,
  }
})
