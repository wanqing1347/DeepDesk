import { describe, expect, it } from 'vitest'
import type { AssistantMessage } from '../types/agent'
import { normalizeReferences, reduceAgentEvent } from './reducer'

function message(): AssistantMessage {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: '',
    thinking: '',
    tools: [],
    references: [],
    recommendations: [],
    errors: [],
    state: 'streaming',
    agentMode: 'chat',
    createdAt: 0,
  }
}

describe('reduceAgentEvent', () => {
  it('reduces the real chat tool/reference/recommend event sequence', () => {
    const target = message()

    reduceAgentEvent(target, { type: 'thinking', content: '正在分析问题...\n' })
    reduceAgentEvent(target, {
      type: 'tool_start',
      toolName: 'web_search',
      toolCallId: 'call-1',
      arguments: '{"query":"FastAPI"}',
    })
    reduceAgentEvent(target, {
      type: 'tool_end',
      toolName: 'web_search',
      toolCallId: 'call-1',
      result: '{"results":[]}',
    })
    reduceAgentEvent(target, { type: 'text', content: 'FastAPI' })
    reduceAgentEvent(target, {
      type: 'reference',
      content: [{ title: 'FastAPI', url: 'https://fastapi.tiangolo.com/', content: 'Docs' }],
      count: 1,
    })
    reduceAgentEvent(target, { type: 'recommend', content: ['What is FastAPI?', 'What is FastAPI?'], count: 2 })
    reduceAgentEvent(target, { type: 'complete' })

    expect(target.thinking).toContain('正在分析问题')
    expect(target.content).toBe('FastAPI')
    expect(target.tools).toEqual([
      {
        id: 'call-1',
        toolName: 'web_search',
        status: 'complete',
        arguments: '{"query":"FastAPI"}',
        result: '{"results":[]}',
      },
    ])
    expect(target.references).toEqual([
      {
        title: 'FastAPI',
        url: 'https://fastapi.tiangolo.com/',
        content: 'Docs',
        domain: 'fastapi.tiangolo.com',
      },
    ])
    expect(target.recommendations).toEqual(['What is FastAPI?'])
    expect(target.state).toBe('complete')
  })

  it('keeps a recovered retry stream complete when final text arrives', () => {
    const target = message()

    reduceAgentEvent(target, {
      type: 'error',
      code: 'LLM_CALL_FAILED',
      message: 'LLM 调用失败，正在重试 (1/2)',
    })
    expect(target.state).toBe('streaming')
    expect(target.errors[0]?.transient).toBe(true)

    reduceAgentEvent(target, { type: 'text', content: 'Recovered answer' })
    reduceAgentEvent(target, { type: 'complete' })

    expect(target.state).toBe('complete')
    expect(target.errors).toHaveLength(1)
  })

  it('keeps tool timeline order based on tool_start even when completions arrive later', () => {
    const target = message()

    reduceAgentEvent(target, {
      type: 'tool_start',
      toolName: 'read_skill',
      toolCallId: 'call-skill',
      arguments: '{"skill":"code-review"}',
    })
    reduceAgentEvent(target, {
      type: 'tool_start',
      toolName: 'read_file',
      toolCallId: 'call-read',
      arguments: '{"filePath":"input.txt"}',
    })
    reduceAgentEvent(target, {
      type: 'tool_end',
      toolName: 'read_file',
      toolCallId: 'call-read',
      result: 'workspace content',
    })
    reduceAgentEvent(target, {
      type: 'tool_end',
      toolName: 'read_skill',
      toolCallId: 'call-skill',
      result: '{"success":true}',
    })

    expect(target.tools.map((tool) => tool.id)).toEqual(['call-skill', 'call-read'])
    expect(target.tools.map((tool) => tool.status)).toEqual(['complete', 'complete'])
  })

  it('marks a terminal error with no answer as error on complete', () => {
    const target = message()

    reduceAgentEvent(target, { type: 'error', code: 'AGENT_ERROR', message: 'Failed' })
    reduceAgentEvent(target, { type: 'complete' })

    expect(target.state).toBe('error')
  })
})

describe('normalizeReferences', () => {
  it('keeps large research source sets readable and de-duplicates exact URLs', () => {
    const payload = [
      ...Array.from({ length: 12 }, (_, index) => ({
        title: `Source ${index + 1}`,
        url: `https://research.example.com/source-${index + 1}`,
        content: `Evidence ${index + 1}`,
      })),
      { title: 'Duplicate', url: 'https://research.example.com/source-4', content: 'duplicate' },
      { title: 'Invalid', url: 'javascript:alert(1)' },
    ]

    const sources = normalizeReferences(payload)

    expect(sources).toHaveLength(12)
    expect(sources[3]).toEqual({
      title: 'Source 4',
      url: 'https://research.example.com/source-4',
      content: 'Evidence 4',
      domain: 'research.example.com',
    })
  })

  it('supports persisted nested reference payloads and de-duplicates URLs', () => {
    const nested = JSON.stringify({
      type: 'reference',
      content: JSON.stringify([
        { title: 'One', url: 'example.com/path' },
        { title: 'Duplicate', url: 'https://example.com/path' },
      ]),
    })

    expect(normalizeReferences(nested)).toEqual([
      {
        title: 'One',
        url: 'https://example.com/path',
        domain: 'example.com',
      },
    ])
  })
})
