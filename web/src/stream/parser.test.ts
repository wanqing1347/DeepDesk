import { describe, expect, it } from 'vitest'
import { parseAgentEventStream } from './parser'
import type { AgentEvent } from '../types/sse'

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

describe('parseAgentEventStream', () => {
  it('parses canonical SSE events split across arbitrary chunks', async () => {
    const events: AgentEvent[] = []
    const body = streamFromChunks([
      'data: {"type":"thinking","content":"ana',
      'lyzing"}\n\n',
      'data: {"type":"tool_start","toolName":"web_search","toolCallId":"call-1","arguments":"{\\"query\\":\\"FastAPI\\"}"}\n\n',
      'data: {"type":"text","content":"Hello"}\n',
      '\ndata: {"type":"complete"}\n\n',
    ])

    await parseAgentEventStream(body, (event) => {
      events.push(event)
    })

    expect(events).toEqual([
      { type: 'thinking', content: 'analyzing' },
      {
        type: 'tool_start',
        toolName: 'web_search',
        toolCallId: 'call-1',
        arguments: '{"query":"FastAPI"}',
      },
      { type: 'text', content: 'Hello' },
      { type: 'complete' },
    ])
  })

  it('flushes the last event even when the stream has no trailing blank line', async () => {
    const events: AgentEvent[] = []
    const body = streamFromChunks(['data: {"type":"text","content":"final"}'])

    await parseAgentEventStream(body, (event) => {
      events.push(event)
    })

    expect(events).toEqual([{ type: 'text', content: 'final' }])
  })

  it('rejects unknown event types instead of silently dropping them', async () => {
    const body = streamFromChunks(['data: {"type":"mystery"}\n\n'])

    await expect(parseAgentEventStream(body, () => undefined)).rejects.toThrow('Unknown SSE event type')
  })
})
