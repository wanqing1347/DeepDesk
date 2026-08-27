import type { AgentEvent, AgentEventType } from '../types/sse'

const EVENT_TYPES = new Set<AgentEventType>([
  'text',
  'thinking',
  'tool_start',
  'tool_end',
  'reference',
  'recommend',
  'error',
  'complete',
])

function decodeBlock(block: string): AgentEvent | null {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n')
    .trim()

  if (!data || data === '[DONE]') return null
  const parsed = JSON.parse(data) as Partial<AgentEvent>
  if (!parsed.type || !EVENT_TYPES.has(parsed.type)) {
    throw new Error(`Unknown SSE event type: ${String(parsed.type)}`)
  }
  return parsed as AgentEvent
}

export async function parseAgentEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: AgentEvent) => void | Promise<void>,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const consume = async (flush = false) => {
    if (flush && buffer.trim()) buffer += '\n\n'
    while (true) {
      const match = buffer.match(/\r?\n\r?\n/)
      if (!match || match.index === undefined) return
      const block = buffer.slice(0, match.index)
      buffer = buffer.slice(match.index + match[0].length)
      const event = decodeBlock(block)
      if (event) await onEvent(event)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      await consume()
    }
    buffer += decoder.decode()
    await consume(true)
  } finally {
    reader.releaseLock()
  }
}
