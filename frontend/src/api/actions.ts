import service, { get, patch, post, postPrivateBlob, remove } from './request'

export interface PrivateDocument {
  document_id: string
  original_name: string
  media_type: string
  size_bytes: number
  sha256: string
  status: string
  document_kind: 'upload' | 'resume' | 'match_report' | string
  scan_status: string
  scan_scope: 'full_antivirus' | 'structural_signature_only'
  scan_checked_at?: string | null
  text_preview: string
  created_at?: string
}

export interface PrivateDownloadGrant {
  download_url: string
  expires_at: string
  audience: 'web_private'
}

export interface ApplicationRecord {
  app_id: string
  recruit_id: string
  document_id: string
  status: string
  delivery: 'in_app_only_no_external_delivery'
  created_at?: string
  updated_at?: string
}

export async function uploadDocument(file: File) {
  const data = new FormData()
  data.append('file', file)
  return service.post<unknown, PrivateDocument>('/api/documents', data)
}

export function fetchDocuments() {
  return get<PrivateDocument[]>('/api/documents')
}

export function deleteDocument(documentId: string, idempotencyKey: string) {
  return remove<{ status: string; idempotent: boolean }>(
    `/api/documents/${documentId}`,
    {
      data: { confirm_delete: true },
      headers: { 'Idempotency-Key': idempotencyKey },
    },
  )
}

export function issuePrivateDownload(documentId: string, idempotencyKey: string) {
  return post<PrivateDownloadGrant>(
    `/api/artifacts/${documentId}/download-grant`,
    { confirm_private_download: true },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function generateMatchReport(
  sessionId: string,
  format: 'pdf' | 'docx',
  idempotencyKey: string,
) {
  return post<PrivateDocument>(
    '/api/artifacts/match-report',
    {
      session_id: sessionId,
      format,
      confirm_generation: true,
    },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function createApplication(
  recruitId: string,
  documentId: string,
  idempotencyKey: string,
) {
  return post<ApplicationRecord>(
    '/api/applications',
    {
      recruit_id: recruitId,
      document_id: documentId,
      confirm_in_app_only: true,
    },
    { headers: { 'Idempotency-Key': idempotencyKey } },
  )
}

export function redeemPrivateDownload(downloadUrl: string) {
  return postPrivateBlob(downloadUrl)
}

export function fetchApplications() {
  return get<ApplicationRecord[]>('/api/applications')
}

export function withdrawApplication(appId: string) {
  return patch<ApplicationRecord>(`/api/applications/${appId}`, {
    status: 'withdrawn',
  })
}
