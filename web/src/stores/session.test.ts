import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  listSessions: vi.fn(),
  deleteSession: vi.fn(),
}))

vi.mock('../api/session', () => api)

import { useSessionStore } from './session'

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.listSessions.mockReset()
    api.deleteSession.mockReset()
  })

  it('loads persisted sessions and clears a previous load error', async () => {
    api.listSessions.mockResolvedValue({
      pageNum: 1,
      pageSize: 100,
      total: 1,
      records: [
        {
          conversationId: 'conv-1',
          question: 'Persisted question',
          answer: 'Persisted answer',
        },
      ],
    })

    const store = useSessionStore()
    store.error = 'old error'

    await store.load()

    expect(store.loading).toBe(false)
    expect(store.error).toBe('')
    expect(store.sessions).toHaveLength(1)
    expect(store.sessions[0]?.conversationId).toBe('conv-1')
  })

  it('keeps the current sidebar items when refresh fails', async () => {
    api.listSessions.mockRejectedValue(new Error('database unavailable'))

    const store = useSessionStore()
    store.sessions = [{ conversationId: 'conv-existing', question: 'Existing' }]

    await store.load()

    expect(store.loading).toBe(false)
    expect(store.error).toBe('database unavailable')
    expect(store.sessions.map((item) => item.conversationId)).toEqual(['conv-existing'])
  })

  it('removes a session only after the backend delete succeeds', async () => {
    const store = useSessionStore()
    store.sessions = [{ conversationId: 'conv-delete', question: 'Delete me' }]

    api.deleteSession.mockRejectedValueOnce(new Error('delete failed'))
    await expect(store.remove('conv-delete')).rejects.toThrow('delete failed')
    expect(store.sessions).toHaveLength(1)

    api.deleteSession.mockResolvedValueOnce('会话删除成功')
    await store.remove('conv-delete')
    expect(store.sessions).toEqual([])
  })
})
