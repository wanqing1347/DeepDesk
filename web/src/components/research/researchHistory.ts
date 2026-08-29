import type { SessionListItem } from '../../types/api'
import { filterWorkspaceSessions } from '../layout/workspaceNavigation'

function sessionTimestamp(session: SessionListItem): number {
  const raw = session.updateTime || session.createTime
  if (!raw) return 0
  const parsed = Date.parse(raw)
  return Number.isNaN(parsed) ? 0 : parsed
}

export function researchHistoryItems(
  sessions: SessionListItem[],
  query = '',
): SessionListItem[] {
  return [...filterWorkspaceSessions(sessions, 'research', query)].sort(
    (a, b) => sessionTimestamp(b) - sessionTimestamp(a),
  )
}

export function researchHistoryStatus(session: SessionListItem): 'Complete' | 'In progress' {
  return session.answer?.trim() ? 'Complete' : 'In progress'
}

export function researchHistoryTitle(session: SessionListItem): string {
  return session.question?.trim() || 'Untitled research'
}
