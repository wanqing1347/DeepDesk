import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConversationStore } from './conversation'

describe('conversation retry behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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
