import { post } from './request'

export type DocumentFactField =
  | 'name'
  | 'email'
  | 'phone'
  | 'dept'
  | 'grade'
  | 'gpa'
  | 'research_interest'
  | 'research_experience'
  | 'interest_tags'
  | 'awards'
  | 'positions'

export interface ParsedDocumentFact {
  field: DocumentFactField
  label: string
  value: string | string[]
  source_excerpt: string
}

export interface LocalDocumentAnalysis {
  document_id: string
  facts: ParsedDocumentFact[]
  retention: 'not_stored'
  external_model_called: false
}

export function analyzePrivateDocument(documentId: string) {
  return post<LocalDocumentAnalysis>(`/api/documents/${documentId}/analysis`, {
    confirm_private_parse: true,
  })
}

export interface SelectedDocumentText {
  field: DocumentFactField
  selected_text: string
}

export interface DocumentInterpretation {
  interpretation: string
  provider: 'glm'
  retention: 'not_stored'
}

export function interpretSelectedDocumentText(
  documentId: string,
  selections: SelectedDocumentText[],
) {
  return post<DocumentInterpretation>(
    `/api/documents/${documentId}/interpretation`,
    { confirm_single_use: true, selections },
  )
}
