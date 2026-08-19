import { get, patch, post } from './request'
import type {
  ActivityQuestion,
  HardConstraintCapabilities,
  InterviewEnhancementRetryResult,
  InterviewProfilePatch,
  InterviewState,
  InterestExplorationSuggestions,
} from '@/types/interview'

export function getHardConstraintCapabilities() {
  return get<HardConstraintCapabilities>('/api/interviews/hard-constraint-capabilities')
}

/** 兴趣探索：活动兴趣选择题定义（静态内容） */
export function getActivityQuestion() {
  return get<ActivityQuestion>('/api/interest-exploration/question')
}

/** 兴趣探索：从活动选择生成候选研究方向（确定性映射） */
export function suggestDirections(activities: string[]) {
  return post<InterestExplorationSuggestions>(
    '/api/interest-exploration/suggestions',
    { activities },
  )
}

/** 兴趣探索：把选定候选方向写回画像，继续推荐导师 */
export function applyDirections(
  sessionId: string,
  expectedVersion: number,
  directionKeys: string[],
  activities: string[] = [],
) {
  return post<InterviewState>(`/api/interest-exploration/${sessionId}/apply`, {
    direction_keys: directionKeys,
    activities,
    expected_version: expectedVersion,
  })
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
