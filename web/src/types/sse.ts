export type AgentEventType =
  | 'text'
  | 'thinking'
  | 'tool_start'
  | 'tool_end'
  | 'reference'
  | 'recommend'
  | 'error'
  | 'complete'

export interface AgentEvent {
  type: AgentEventType
  content?: unknown
  count?: number
  toolName?: string
  toolCallId?: string
  arguments?: unknown
  result?: unknown
  code?: string
  message?: string
  detail?: string
}
