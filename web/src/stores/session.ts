import { defineStore } from 'pinia'
import { deleteSession, listSessions } from '../api/session'
import type { SessionListItem } from '../types/api'

export const useSessionStore = defineStore('session', {
  state: () => ({
    sessions: [] as SessionListItem[],
    loading: false,
    error: '' as string,
  }),
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const page = await listSessions(1, 100)
        this.sessions = page.records
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Unable to load conversation history.'
      } finally {
        this.loading = false
      }
    },
    async remove(conversationId: string) {
      await deleteSession(conversationId)
      this.sessions = this.sessions.filter((item) => item.conversationId !== conversationId)
    },
  },
})
