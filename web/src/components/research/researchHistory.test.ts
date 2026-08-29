import { describe, expect, it } from 'vitest'
import type { SessionListItem } from '../../types/api'
import {
  researchHistoryItems,
  researchHistoryStatus,
  researchHistoryTitle,
} from './researchHistory'

const sessions: SessionListItem[] = [
  {
    conversationId: 'chat-1',
    agentType: 'websearch',
    question: 'General chat',
    answer: 'Done',
    updateTime: '2026-08-29T08:00:00',
  },
  {
    conversationId: 'research-old',
    agentType: 'plan-execute',
    question: 'Older research',
    answer: 'Older report',
    updateTime: '2026-08-28T08:00:00',
  },
  {
    conversationId: 'research-new',
    agentType: 'plan-execute',
    question: 'Newer research',
    answer: null,
    updateTime: '2026-08-29T09:00:00',
  },
]

describe('research history', () => {
  it('keeps only Deep Research sessions and sorts newest first', () => {
    expect(researchHistoryItems(sessions).map((item) => item.conversationId)).toEqual([
      'research-new',
      'research-old',
    ])
  })

  it('searches within research history only', () => {
    expect(researchHistoryItems(sessions, 'older').map((item) => item.conversationId)).toEqual([
      'research-old',
    ])
    expect(researchHistoryItems(sessions, 'general')).toEqual([])
  })

  it('derives status and safe titles from list data without inventing source counts', () => {
    expect(researchHistoryStatus(sessions[1])).toBe('Complete')
    expect(researchHistoryStatus(sessions[2])).toBe('In progress')
    expect(researchHistoryTitle({ conversationId: 'untitled', agentType: 'plan-execute' })).toBe(
      'Untitled research',
    )
  })
})
