import type { AssistantMessage, SourceReference } from '../types/agent'
import type { AgentEvent } from '../types/sse'

function asText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJson(value: unknown): unknown {
  if (typeof value !== 'string') return value
  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function toolResultFailed(value: unknown): boolean {
  const parsed = parseJson(value)
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const record = parsed as Record<string, unknown>
    if (record.success === false) return true
    if (record.error && record.success !== true) return true
    return false
  }
  if (typeof parsed !== 'string') return false
  const normalized = parsed.trim().toLowerCase()
  return (
    normalized.startsWith('error:') ||
    normalized.startsWith('工具执行失败') ||
    normalized.startsWith('工具未找到') ||
    normalized.includes('restricted bash is disabled')
  )
}

function unwrapReferencePayload(value: unknown): unknown {
  let current = parseJson(value)
  if (current && typeof current === 'object' && !Array.isArray(current)) {
    const record = current as Record<string, unknown>
    if (record.data && typeof record.data === 'object') {
      const nested = record.data as Record<string, unknown>
      if ('content' in nested) current = parseJson(nested.content)
    }
  }
  if (current && typeof current === 'object' && !Array.isArray(current)) {
    const record = current as Record<string, unknown>
    if (record.type === 'reference' && 'content' in record) current = parseJson(record.content)
  }
  return current
}

function normalizeUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null
  const input = value.trim()
  const withScheme = /^https?:\/\//i.test(input) ? input : `https://${input}`
  try {
    const url = new URL(withScheme)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

export function normalizeReferences(value: unknown): SourceReference[] {
  const payload = unwrapReferencePayload(value)
  if (!Array.isArray(payload)) return []

  const unique = new Map<string, SourceReference>()
  for (const item of payload) {
    let candidate: Record<string, unknown>
    if (typeof item === 'string') {
      const parsed = parseJson(item)
      candidate = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : { url: item }
    } else if (item && typeof item === 'object' && !Array.isArray(item)) {
      candidate = item as Record<string, unknown>
    } else {
      continue
    }

    const url = normalizeUrl(candidate.url ?? candidate.link)
    if (!url || unique.has(url)) continue
    const parsedUrl = new URL(url)
    const titleValue = candidate.title ?? candidate.name
    unique.set(url, {
      url,
      title: typeof titleValue === 'string' && titleValue.trim() ? titleValue.trim() : parsedUrl.hostname,
      content: typeof candidate.content === 'string' ? candidate.content : undefined,
      domain: parsedUrl.hostname.replace(/^www\./, ''),
    })
  }
  return [...unique.values()]
}

export function normalizeRecommendations(value: unknown): string[] {
  const payload = parseJson(value)
  if (!Array.isArray(payload)) return []
  return [...new Set(payload.filter((item): item is string => typeof item === 'string').map((item) => item.trim()).filter(Boolean))]
}

export function reduceAgentEvent(message: AssistantMessage, event: AgentEvent): void {
  switch (event.type) {
    case 'text':
      message.content += asText(event.content)
      break
    case 'thinking':
      message.thinking += asText(event.content)
      break
    case 'tool_start': {
      const id = event.toolCallId || `${event.toolName || 'tool'}-${message.tools.length}`
      const existing = message.tools.find((tool) => tool.id === id)
      if (existing) {
        existing.status = 'running'
        existing.arguments = event.arguments
      } else {
        message.tools.push({
          id,
          toolName: event.toolName || 'unknown',
          status: 'running',
          arguments: event.arguments,
        })
      }
      break
    }
    case 'tool_end': {
      const id = event.toolCallId || `${event.toolName || 'tool'}-${message.tools.length}`
      const existing = message.tools.find((tool) => tool.id === id)
      const status = toolResultFailed(event.result) ? 'error' : 'complete'
      if (existing) {
        existing.status = status
        existing.result = event.result
      } else {
        message.tools.push({
          id,
          toolName: event.toolName || 'unknown',
          status,
          result: event.result,
        })
      }
      break
    }
    case 'reference':
      message.references = normalizeReferences(event.content)
      break
    case 'recommend':
      message.recommendations = normalizeRecommendations(event.content)
      break
    case 'error': {
      const errorMessage = event.message || asText(event.content) || 'Agent request failed.'
      const transient =
        event.code === 'LLM_CALL_FAILED' && /正在重试|retrying/i.test(errorMessage)
      message.errors.push({
        code: event.code,
        message: errorMessage,
        detail: event.detail,
        ...(transient ? { transient: true } : {}),
      })
      break
    }
    case 'complete':
      message.state = message.errors.length > 0 && !message.content.trim() ? 'error' : 'complete'
      break
  }
}
