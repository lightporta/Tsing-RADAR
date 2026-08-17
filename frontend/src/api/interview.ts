import { get, patch, post } from './request'
import type {
  HardConstraintCapabilities,
  InterviewEnhancementRetryResult,
  InterviewProfilePatch,
  InterviewState,
} from '@/types/interview'

export function getHardConstraintCapabilities() {
  return get<HardConstraintCapabilities>('/api/interviews/hard-constraint-capabilities')
}

export function getInterview(sessionId: string) {
  return get<InterviewState>(`/api/interviews/${sessionId}`)
}

export function editInterviewProfile(
  sessionId: string,
  expectedVersion: number,
  profilePatch: InterviewProfilePatch,
) {
  return patch<InterviewState>(`/api/interviews/${sessionId}/profile`, {
    expected_version: expectedVersion,
    ...profilePatch,
  })
}

export function confirmInterviewProfile(
  sessionId: string,
  expectedVersion: number,
) {
  return post<InterviewState>(`/api/interviews/${sessionId}/confirm`, {
    expected_version: expectedVersion,
  })
}

export function retryInterviewEnhancement(sessionId: string) {
  return post<InterviewEnhancementRetryResult>(
    `/api/interviews/${sessionId}/enhancement-retry`,
    {},
  )
}
