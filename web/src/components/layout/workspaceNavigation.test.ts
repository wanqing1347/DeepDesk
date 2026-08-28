import { describe, expect, it } from 'vitest'
import type { SessionListItem } from '../../types/api'
import {
  filterWorkspaceSessions,
  workspaceSectionForSession,
} from './workspaceNavigation'

const sessions: SessionListItem[] = [
  { conversationId: 'chat-1', agentType: 'websearch', question: 'Vue architecture' },
  { conversationId: 'research-1', agentType: 'plan-execute', question: 'Agent landscape' },
  { conversationId: 'file-1', agentType: 'file', question: 'Summarize paper' },
  { conversationId: 'skills-1', agentType: 'skills', question: 'Inspect repository' },
  { conversationId: 'ppt-1', agentType: 'pptx', question: 'Build interview deck' },
]

describe('workspace navigation', () => {
  it('maps persisted agent types to workspace sections', () => {
    expect(workspaceSectionForSession(sessions[0])).toBe('chats')
    expect(workspaceSectionForSession(sessions[1])).toBe('research')
    expect(workspaceSectionForSession(sessions[2])).toBe('chats')
    expect(workspaceSectionForSession(sessions[3])).toBe('chats')
    expect(workspaceSectionForSession(sessions[4])).toBe('presentations')
  })

  it('filters recent history by workspace section', () => {
    expect(filterWorkspaceSessions(sessions, 'research').map((item) => item.conversationId)).toEqual([
      'research-1',
    ])
    expect(filterWorkspaceSessions(sessions, 'presentations').map((item) => item.conversationId)).toEqual([
      'ppt-1',
    ])
  })

  it('keeps file and skills conversations inside Chats', () => {
    expect(filterWorkspaceSessions(sessions, 'chats').map((item) => item.conversationId)).toEqual([
      'chat-1',
      'file-1',
      'skills-1',
    ])
  })

  it('searches within the selected workspace section', () => {
    expect(filterWorkspaceSessions(sessions, 'chats', 'architecture')).toHaveLength(1)
    expect(filterWorkspaceSessions(sessions, 'research', 'architecture')).toHaveLength(0)
    expect(filterWorkspaceSessions(sessions, 'chats', 'repository')).toHaveLength(1)
  })
})
