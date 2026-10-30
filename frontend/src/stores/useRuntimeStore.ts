import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type MentorPolicy =
  | 'formal_verified_profiles_only'
  | 'simulation_only_not_for_production'
  | string

export const useRuntimeStore = defineStore('runtime', () => {
  const isFrontendMock = import.meta.env.VITE_USE_MOCK === 'true'
  const llmMode = ref('local_rules')
  const mentorPolicy = ref<MentorPolicy>('formal_verified_profiles_only')
  const simulationMentors = ref(false)

  const isLocalRules = computed(() => llmMode.value === 'local_rules')
  const isSimulationMentors = computed(
    () =>
      simulationMentors.value ||
      mentorPolicy.value === 'simulation_only_not_for_production',
  )

  function applySessionMeta(meta: {
    llm_mode?: string
    mentor_policy?: string
    simulation_mentors?: boolean
  }) {
    if (meta.llm_mode) llmMode.value = meta.llm_mode
    if (meta.mentor_policy) mentorPolicy.value = meta.mentor_policy
    if (typeof meta.simulation_mentors === 'boolean') {
      simulationMentors.value = meta.simulation_mentors
    }
  }

  return {
    isFrontendMock,
    llmMode,
    mentorPolicy,
    simulationMentors,
    isLocalRules,
    isSimulationMentors,
    applySessionMeta,
  }
})
