import { modeFromBackend } from '../../config/agents'
import type { AgentMode } from '../../types/agent'
import type { SessionListItem } from '../../types/api'

export type WorkspaceSection = 'chats' | 'research' | 'presentations'

const SECTION_BY_MODE: Record<AgentMode, WorkspaceSection> = {
  chat: 'chats',
  research: 'research',
  file: 'chats',
  skills: 'chats',
  ppt: 'presentations',
}

export function workspaceSectionForSession(session: SessionListItem): WorkspaceSection {
  return SECTION_BY_MODE[modeFromBackend(session.agentType)]
}

export function filterWorkspaceSessions(
  sessions: SessionListItem[],
  section: WorkspaceSection,
  query = '',
): SessionListItem[] {
  const normalizedQuery = query.trim().toLocaleLowerCase()

  return sessions.filter((session) => {
    if (workspaceSectionForSession(session) !== section) return false
    if (!normalizedQuery) return true

    const searchable = [session.question, session.answer]
      .filter((value): value is string => Boolean(value?.trim()))
      .join(' ')
      .toLocaleLowerCase()

    return searchable.includes(normalizedQuery)
  })
}
