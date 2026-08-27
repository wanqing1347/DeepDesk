import type { AgentMode } from '../types/agent'
import type { StopResponse } from '../types/api'
import { apiErrorFromResponse, apiUrl, authHeaders, requestJson } from './client'

const STREAM_PATHS: Record<AgentMode, string> = {
  chat: '/agent/chat/stream',
  file: '/agent/file/stream',
  skills: '/agent/skills/stream',
  research: '/agent/deep/stream',
  ppt: '/agent/pptx/stream',
}

export interface StreamRequest {
  mode: AgentMode
  query: string
  conversationId: string
  fileId?: string
  signal?: AbortSignal
}

export async function openAgentStream(request: StreamRequest): Promise<Response> {
  if (request.mode === 'file' && !request.fileId) {
    throw new Error('File mode requires an uploaded file.')
  }

  const url = apiUrl(STREAM_PATHS[request.mode], {
    query: request.query,
    conversationId: request.conversationId,
    fileId: request.mode === 'file' || request.mode === 'skills' ? request.fileId : undefined,
  })

  const response = await fetch(url, {
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
      ...authHeaders(),
    },
    signal: request.signal,
  })

  if (!response.ok) throw await apiErrorFromResponse(response, 'Unable to start the agent stream.')

  return response
}

export function stopAgent(conversationId: string): Promise<StopResponse> {
  return requestJson<StopResponse>('/agent/stop', {
    method: 'GET',
    params: { conversationId },
  })
}
