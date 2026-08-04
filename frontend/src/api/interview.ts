import { get, patch, post } from './request'
import type {
  InterviewProfilePatch,
  InterviewState,
} from '@/types/interview'

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
