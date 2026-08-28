import { defineStore } from 'pinia'
import { ApiError } from '../api/client'
import { modeFromBackend } from '../config/agents'
import { normalizeRecommendations, normalizeReferences, reduceAgentEvent } from '../stream/reducer'
import type {
  AgentMode,
  AssistantMessage,
  Conversation,
  FileAttachment,
  StreamError,
  ToolActivity,
  UserMessage,
} from '../types/agent'
import type { SessionDetail, StoredMessage } from '../types/api'
import type { AgentEvent } from '../types/sse'

function id(prefix: string): string {
  const value = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
  return `${prefix}-${value}`
}

function timestamp(value?: string | null): number {
  const parsed = value ? Date.parse(value) : Number.NaN
  return Number.isNaN(parsed) ? Date.now() : parsed
}

function storedTools(value?: string | null): ToolActivity[] {
  if (!value?.trim()) return []
  return value
    .split(',')
    .map((tool) => tool.trim())
    .filter(Boolean)
    .map((toolName, index) => ({ id: `stored-${index}-${toolName}`, toolName, status: 'complete' as const }))
}

function streamError(error: unknown): StreamError {
  if (error instanceof ApiError) {
    return {
      code: error.code !== undefined ? String(error.code) : error.status ? `HTTP ${error.status}` : undefined,
      message: error.message || 'The request failed.',
      detail: error.detail,
    }
  }
  if (error instanceof Error) return { message: error.message || 'The request failed.' }
  if (typeof error === 'string' && error.trim()) return { message: error.trim() }
  return { message: 'The request failed.' }
}

function storedAssistant(message: StoredMessage, mode: AgentMode): AssistantMessage | null {
  if (!message.answer && !message.thinking) return null
  return {
    id: `assistant-${message.id}`,
    role: 'assistant',
    content: message.answer || '',
    thinking: message.thinking || '',
    tools: storedTools(message.tools),
    references: normalizeReferences(message.reference),
    recommendations: normalizeRecommendations(message.recommend),
    errors: [],
    state: 'complete',
    agentMode: mode,
    createdAt: timestamp(message.createTime),
  }
}

export const useConversationStore = defineStore('conversation', {
  state: () => ({
    current: null as Conversation | null,
    isStreaming: false,
    loadError: '' as string,
  }),
  getters: {
    conversationId: (state) => state.current?.id || '',
    mode: (state): AgentMode => state.current?.mode || 'chat',
  },
  actions: {
    create(mode: AgentMode = 'chat', conversationId = id('conversation')) {
      this.current = { id: conversationId, mode, messages: [], attachment: null }
      this.isStreaming = false
      this.loadError = ''
      return conversationId
    },
    switchMode(mode: AgentMode): { conversationId: string; created: boolean } {
      if (!this.current) {
        return { conversationId: this.create(mode), created: true }
      }
      if (this.current.mode === mode) {
        return { conversationId: this.current.id, created: false }
      }
      if (this.current.messages.length > 0) {
        return { conversationId: this.create(mode), created: true }
      }
      this.current.mode = mode
      return { conversationId: this.current.id, created: false }
    },
    load(detail: SessionDetail) {
      const mode = modeFromBackend(detail.agentType)
      const messages: Conversation['messages'] = []
      for (const stored of detail.messages) {
        if (stored.question) {
          const user: UserMessage = {
            id: `user-${stored.id}`,
            role: 'user',
            content: stored.question,
            createdAt: timestamp(stored.createTime),
            attachment: stored.fileid ? { fileId: stored.fileid, name: 'Attached file' } : undefined,
          }
          messages.push(user)
        }
        const assistant = storedAssistant(stored, mode)
        if (assistant) messages.push(assistant)
      }
      this.current = {
        id: detail.conversationId,
        mode,
        messages,
        attachment: detail.fileid
          ? { fileId: detail.fileid, name: 'Attached file', status: 'ready', progress: 100 }
          : null,
      }
      this.isStreaming = false
      this.loadError = ''
    },
    addTurn(content: string): { user: UserMessage; assistant: AssistantMessage } {
      if (!this.current) this.create()
      const conversation = this.current!
      const attachment = conversation.attachment?.status === 'ready' ? conversation.attachment : null
      const user: UserMessage = {
        id: id('user'),
        role: 'user',
        content,
        createdAt: Date.now(),
        attachment: attachment
          ? { fileId: attachment.fileId, name: attachment.name, size: attachment.size, type: attachment.type }
          : undefined,
      }
      const assistant: AssistantMessage = {
        id: id('assistant'),
        role: 'assistant',
        content: '',
        thinking: '',
        tools: [],
        references: [],
        recommendations: [],
        errors: [],
        state: 'streaming',
        agentMode: conversation.mode,
        createdAt: Date.now(),
      }
      conversation.messages.push(user, assistant)
      this.isStreaming = true
      return { user, assistant }
    },
    applyEvent(messageId: string, event: AgentEvent) {
      const message = this.current?.messages.find(
        (item): item is AssistantMessage => item.role === 'assistant' && item.id === messageId,
      )
      if (!message) return
      reduceAgentEvent(message, event)
      if (event.type === 'complete') this.isStreaming = false
    },
    fail(messageId: string, error: unknown) {
      const message = this.current?.messages.find(
        (item): item is AssistantMessage => item.role === 'assistant' && item.id === messageId,
      )
      if (!message) return
      message.errors.push(streamError(error))
      message.state = 'error'
      this.isStreaming = false
    },
    prepareRetry(messageId: string) {
      const messages = this.current?.messages
      if (!messages || this.isStreaming) return null
      const index = messages.findIndex((item) => item.role === 'assistant' && item.id === messageId)
      if (index <= 0) return null
      const assistant = messages[index]
      const user = messages[index - 1]
      if (assistant.role !== 'assistant' || user.role !== 'user') return null

      assistant.content = ''
      assistant.thinking = ''
      assistant.tools = []
      assistant.references = []
      assistant.recommendations = []
      assistant.errors = []
      assistant.state = 'streaming'
      assistant.createdAt = Date.now()
      this.isStreaming = true

      return {
        assistant,
        query: user.content,
        mode: assistant.agentMode,
        fileId: user.attachment?.fileId,
      }
    },
    markStopped(messageId?: string) {
      const assistants = this.current?.messages.filter((item): item is AssistantMessage => item.role === 'assistant') || []
      const message = messageId ? assistants.find((item) => item.id === messageId) : assistants.at(-1)
      if (message?.state === 'streaming') message.state = 'stopped'
      this.isStreaming = false
    },
    setAttachment(attachment: FileAttachment | null) {
      if (!this.current) this.create('file')
      this.current!.attachment = attachment
    },
    patchAttachment(patch: Partial<FileAttachment>) {
      if (this.current?.attachment) Object.assign(this.current.attachment, patch)
    },
    hydrateFileMetadata(
      fileId: string,
      metadata: Pick<FileAttachment, 'name' | 'size' | 'type'>,
    ) {
      if (!this.current) return
      if (this.current.attachment?.fileId === fileId) {
        Object.assign(this.current.attachment, metadata)
      }
      for (const message of this.current.messages) {
        if (message.role === 'user' && message.attachment?.fileId === fileId) {
          Object.assign(message.attachment, metadata)
        }
      }
    },
  },
})
