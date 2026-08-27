import { defineStore } from 'pinia'

export type ThemePreference = 'system' | 'light' | 'dark'

function storedTheme(): ThemePreference {
  const value = localStorage.getItem('deepdesk.theme')
  return value === 'light' || value === 'dark' ? value : 'system'
}

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    theme: storedTheme() as ThemePreference,
    sidebarCollapsed: localStorage.getItem('deepdesk.sidebarCollapsed') === 'true',
    mobileSidebarOpen: false,
    apiKey: localStorage.getItem('deepdesk.apiKey') || '',
  }),
  actions: {
    setTheme(theme: ThemePreference) {
      this.theme = theme
      localStorage.setItem('deepdesk.theme', theme)
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
      localStorage.setItem('deepdesk.sidebarCollapsed', String(this.sidebarCollapsed))
    },
    setMobileSidebar(open: boolean) {
      this.mobileSidebarOpen = open
    },
    setApiKey(value: string) {
      this.apiKey = value.trim()
      if (this.apiKey) localStorage.setItem('deepdesk.apiKey', this.apiKey)
      else localStorage.removeItem('deepdesk.apiKey')
    },
  },
})
