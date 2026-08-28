import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConversationStore } from './conversation'

describe('conversation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps the same empty conversation when switching modes', () => {
    const store = useConversationStore()
    store.create('chat', 'conversation-empty')

    const result = store.switchMode('research')

    expect(result).toEqual({ conversationId: 'conversation-empty', created: false })
    expect(store.current).toMatchObject({
      id: 'conversation-empty',
      mode: 'research',
      messages: [],
      attachment: null,
    })
  })

  it('creates a fresh conversation when switching modes after messages exist', () => {
    const store = useConversationStore()
    store.create('chat', 'conversation-chat')
    const { assistant } = store.addTurn('Compare two approaches')
    store.applyEvent(assistant.id, { type: 'complete' })

    const result = store.switchMode('ppt')

    expect(result.created).toBe(true)
    expect(result.conversationId).not.toBe('conversation-chat')
    expect(store.current).toMatchObject({
      id: result.conversationId,
      mode: 'ppt',
      messages: [],
      attachment: null,
    })
  })

  it.each([
    ['plan-execute', 'research'],
    ['pptx', 'ppt'],
  ] as const)('restores %s history as %s mode', (agentType, expectedMode) => {
    const store = useConversationStore()
    store.load({
      conversationId: `conversation-${expectedMode}`,
      agentType,
      messages: [{ id: 11, question: 'Persisted question', answer: 'Persisted answer' }],
    })

    expect(store.current?.mode).toBe(expectedMode)
    expect(store.current?.messages[1]).toMatchObject({
      role: 'assistant',
      agentMode: expectedMode,
    })
  })

  it('reuses the original user question without inserting a duplicate user message', () => {
    const store = useConversationStore()
    store.create('chat', 'conversation-1')
    const { user, assistant } = store.addTurn('Explain SSE retries')
    store.applyEvent(assistant.id, { type: 'text', content: 'Original answer' })
    store.applyEvent(assistant.id, { type: 'complete' })

    const retry = store.prepareRetry(assistant.id)

    expect(retry).not.toBeNull()
    expect(store.current?.messages).toHaveLength(2)
    expect(store.current?.messages[0]).toMatchObject({ id: user.id, role: 'user', content: user.content })
    expect(retry?.query).toBe('Explain SSE retries')
    expect(retry?.mode).toBe('chat')
    expect(retry?.assistant.id).toBe(assistant.id)
    expect(assistant.content).toBe('')
    expect(assistant.thinking).toBe('')
    expect(assistant.errors).toEqual([])
    expect(assistant.state).toBe('streaming')
    expect(store.isStreaming).toBe(true)
  })

  it('keeps the original file id when retrying a file request', () => {
    const store = useConversationStore()
    store.create('file', 'conversation-file')
    store.setAttachment({
      fileId: 'file-123',
      name: 'notes.pdf',
      status: 'ready',
      progress: 100,
    })
    const { assistant } = store.addTurn('Summarize this file')
    store.applyEvent(assistant.id, { type: 'complete' })

    const retry = store.prepareRetry(assistant.id)

    expect(retry?.mode).toBe('file')
    expect(retry?.fileId).toBe('file-123')
  })

  it('hydrates persisted attachment names in both the composer and restored user messages', () => {
    const store = useConversationStore()
    store.load({
      conversationId: 'conversation-file-history',
      agentType: 'file',
      fileid: 'file-456',
      messages: [
        {
          id: 9,
          question: 'What is in the attachment?',
          answer: 'A report.',
          fileid: 'file-456',
        },
      ],
    })

    store.hydrateFileMetadata('file-456', {
      name: 'quarterly-report.pdf',
      size: 4096,
      type: 'pdf',
    })

    expect(store.current?.attachment).toMatchObject({
      fileId: 'file-456',
      name: 'quarterly-report.pdf',
      size: 4096,
      type: 'pdf',
    })
    expect(store.current?.messages[0]).toMatchObject({
      role: 'user',
      attachment: {
        fileId: 'file-456',
        name: 'quarterly-report.pdf',
        size: 4096,
        type: 'pdf',
      },
    })
  })
})
