import type { PageResult, SessionDetail, SessionListItem } from '../types/api'
import { requestJson, requestResult } from './client'
import type { BaseResult } from '../types/api'

export function listSessions(pageNum = 1, pageSize = 100): Promise<PageResult<SessionListItem>> {
  return requestResult<PageResult<SessionListItem>>('/session/list', {
    method: 'GET',
    params: { pageNum, pageSize },
  })
}

export function getSession(conversationId: string): Promise<SessionDetail> {
  return requestResult<SessionDetail>(`/session/${encodeURIComponent(conversationId)}`, {
    method: 'GET',
  })
}

export async function deleteSession(conversationId: string): Promise<string> {
  const result = await requestJson<BaseResult<string>>(`/session/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE',
  })
  if (result.code !== 200) throw new Error(result.message || 'Unable to delete conversation.')
  return result.message
}
