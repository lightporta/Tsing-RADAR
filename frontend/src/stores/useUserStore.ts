import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { Resume, StudentProfile } from '@/types/user'
import type { TraitKey } from '@/types/advisor'
import { TRAITS } from '@/types/advisor'
import {
  readVersionedLocalData,
  removeLocalData,
  USER_PROFILE_STORAGE_KEY,
  writeVersionedLocalData,
} from '@/utils/browserStorage'

const DEFAULT_WEIGHTS = (): Record<TraitKey, number> =>
  TRAITS.reduce(
    (acc, trait) => {
      acc[trait.key] = 50
      return acc
    },
    {} as Record<TraitKey, number>,
  )

function defaultProfile(): StudentProfile {
  return {
    name: '',
    avatarUrl: '',
    email: '',
    dept: '',
    category: '',
    grade: '',
    phone: '',
    gpa: '',
    research_experience: '',
    research_interest: '',
    interest_tags: [],
    weights: DEFAULT_WEIGHTS(),
  }
}

function cloneProfile(profile: StudentProfile): StudentProfile {
  return {
    ...profile,
    interest_tags: [...profile.interest_tags],
    weights: { ...profile.weights },
  }
}

function isStoredProfile(value: unknown): value is StudentProfile {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<StudentProfile>
  const requiredStringFields: Array<keyof StudentProfile> = [
    'name',
    'email',
    'dept',
    'category',
    'grade',
  ]
  const optionalStringFields: Array<keyof StudentProfile> = [
    'avatarUrl',
    'phone',
    'gpa',
    'research_experience',
    'research_interest',
  ]
  if (!requiredStringFields.every((key) => typeof candidate[key] === 'string')) return false
  if (!optionalStringFields.every((key) => candidate[key] === undefined || typeof candidate[key] === 'string')) {
    return false
  }
  if (typeof candidate.avatarUrl === 'string' && candidate.avatarUrl.length > 600_000) return false
  if (!Array.isArray(candidate.interest_tags)) return false
  if (
    candidate.interest_tags.length > 100 ||
    !candidate.interest_tags.every(
      (tag) => typeof tag === 'string' && Array.from(tag.trim()).length > 0 && Array.from(tag.trim()).length <= 20,
    )
  ) return false
  if (!candidate.weights || typeof candidate.weights !== 'object') return false
  return TRAITS.every(({ key }) => {
    const weight = candidate.weights?.[key]
    return typeof weight === 'number' && Number.isFinite(weight) && weight >= 0 && weight <= 100
  })
}

function loadProfile() {
  const stored = readVersionedLocalData(USER_PROFILE_STORAGE_KEY, isStoredProfile)
  return stored ? cloneProfile({ ...defaultProfile(), ...stored }) : defaultProfile()
}

export const useUserStore = defineStore('user', () => {
  const profile = ref<StudentProfile>(loadProfile())
  const resumes = ref<Resume[]>([])
  const storageError = ref('')

  /** 是否已完善基本信息（用于匹配前提示） */
  const isProfileComplete = computed(
    () => !!profile.value.name && !!profile.value.dept && profile.value.interest_tags.length > 0,
  )

  function persistProfile() {
    const result = writeVersionedLocalData(USER_PROFILE_STORAGE_KEY, cloneProfile(profile.value))
    storageError.value = result.ok
      ? ''
      : result.reason === 'quota'
        ? '浏览器本机存储空间不足，请移除较大的头像后重试。'
        : '浏览器禁止了本机存储，本次修改仅在当前页面有效。'
    return result
  }

  /** 兼容原接口：更新完整或部分资料，并同步到当前浏览器。 */
  function updateProfile(patch: Partial<StudentProfile>) {
    profile.value = cloneProfile({ ...profile.value, ...patch })
    return persistProfile()
  }

  /** 只保存“基本信息”区域，不覆盖尚未保存的兴趣与权重。 */
  function saveBasicProfile(source: StudentProfile) {
    return updateProfile({
      name: source.name,
      avatarUrl: source.avatarUrl,
      email: source.email,
      dept: source.dept,
      category: source.category,
      grade: source.grade,
      phone: source.phone,
      gpa: source.gpa,
      research_experience: source.research_experience,
    })
  }

  /** 只保存“兴趣与权重”区域，不覆盖尚未保存的基本信息。 */
  function savePreferenceProfile(source: StudentProfile) {
    return updateProfile({
      research_interest: source.research_interest,
      interest_tags: [...source.interest_tags],
      weights: { ...source.weights },
    })
  }

  /** 设置某维度权重（兼容现有调用，并持久化本机偏好）。 */
  function setWeight(key: TraitKey, value: number) {
    profile.value.weights[key] = value
    return persistProfile()
  }

  /** 清除资料的本机副本，并恢复内存默认值。 */
  function clearLocalProfile() {
    removeLocalData(USER_PROFILE_STORAGE_KEY)
    profile.value = defaultProfile()
    resumes.value = []
    storageError.value = ''
  }

  /** 新增 / 更新简历；简历仍由原私有文档流程管理。 */
  function upsertResume(resume: Resume) {
    const index = resumes.value.findIndex((item) => item.resume_id === resume.resume_id)
    if (index >= 0) resumes.value[index] = resume
    else resumes.value.unshift(resume)
  }

  function removeResume(id: string) {
    resumes.value = resumes.value.filter((resume) => resume.resume_id !== id)
  }

  return {
    profile,
    resumes,
    storageError,
    isProfileComplete,
    updateProfile,
    saveBasicProfile,
    savePreferenceProfile,
    setWeight,
    clearLocalProfile,
    upsertResume,
    removeResume,
  }
})
