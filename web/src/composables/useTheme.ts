import { onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useSettingsStore } from '../stores/settings'

export function useTheme() {
  const settings = useSettingsStore()
  const { theme } = storeToRefs(settings)
  const media = window.matchMedia('(prefers-color-scheme: dark)')

  const apply = () => {
    const dark = theme.value === 'dark' || (theme.value === 'system' && media.matches)
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  }

  const onSystemChange = () => {
    if (theme.value === 'system') apply()
  }

  watch(theme, apply, { immediate: true })
  media.addEventListener('change', onSystemChange)
  onBeforeUnmount(() => media.removeEventListener('change', onSystemChange))

  return { theme }
}
