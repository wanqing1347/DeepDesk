import type { BaseResult, PresentationInfo, PresentationList } from '../types/api'
import { requestJson, requestResult } from './client'

export function listPresentations(): Promise<PresentationList> {
  return requestResult<PresentationList>('/ppt/list', { method: 'GET' })
}

export function getPresentation(id: number): Promise<PresentationInfo> {
  return requestResult<PresentationInfo>(`/ppt/${id}`, { method: 'GET' })
}

export async function deletePresentation(id: number): Promise<string> {
  const result = await requestJson<BaseResult<string>>(`/ppt/${id}`, { method: 'DELETE' })
  if (result.code !== 200) throw new Error(result.message || 'Unable to delete presentation.')
  return result.message
}
