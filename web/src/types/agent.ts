export type AgentMode = 'chat' | 'file' | 'skills' | 'research' | 'ppt'
export type MessageState = 'streaming' | 'complete' | 'error' | 'stopped'
export type ToolStatus = 'running' | 'complete' | 'error'

export interface SourceReference {
  url: string
  title: string
  content?: string
  domain: string
}

export interface ToolActivity {
  id: string
  toolName: string
  status: ToolStatus
  arguments?: unknown
  result?: unknown
}

export interface StreamError {
  code?: string
  message: string
  detail?: string
  transient?: boolean
}

export interface FileAttachment {
  fileId?: string
  name: string
  size?: number
  type?: string
  status: 'uploading' | 'processing' | 'ready' | 'error'
  progress: number
  error?: string
  retryable?: boolean
}

export interface UserMessage {
  id: string
  role: 'user'
  content: string
  createdAt: number
  attachment?: Pick<FileAttachment, 'fileId' | 'name' | 'size' | 'type'>
}

export interface AssistantMessage {
  id: string
  role: 'assistant'
  content: string
  thinking: string
  tools: ToolActivity[]
  references: SourceReference[]
  recommendations: string[]
  errors: StreamError[]
  state: MessageState
  agentMode: AgentMode
  createdAt: number
}

export type ConversationMessage = UserMessage | AssistantMessage

export interface Conversation {
  id: string
  mode: AgentMode
  messages: ConversationMessage[]
  attachment: FileAttachment | null
}

export interface AgentDefinition {
  id: AgentMode
  label: string
  shortLabel: string
  description: string
  headline: string
  placeholder: string
  suggestions: string[]
  capabilities: string[]
}
