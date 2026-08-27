<script setup lang="ts">
import { Monitor, Moon, Sun, X } from 'lucide-vue-next'
import { onMounted, ref, watch } from 'vue'
import { useSettingsStore, type ThemePreference } from '../../stores/settings'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const settings = useSettingsStore()
const dialog = ref<HTMLDialogElement | null>(null)
const apiKey = ref(settings.apiKey)

const themes: Array<{ id: ThemePreference; label: string; icon: typeof Sun }> = [
  { id: 'system', label: 'System', icon: Monitor },
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'dark', label: 'Dark', icon: Moon },
]

function sync() {
  if (!dialog.value) return
  if (props.open && !dialog.value.open) {
    apiKey.value = settings.apiKey
    dialog.value.showModal()
  } else if (!props.open && dialog.value.open) {
    dialog.value.close()
  }
}

function save() {
  settings.setApiKey(apiKey.value)
  emit('close')
}

watch(() => props.open, sync)
onMounted(sync)
</script>

<template>
  <dialog
    ref="dialog"
    class="m-auto w-[min(92vw,460px)] rounded-[14px] bg-[var(--surface-raised)] p-0 text-[var(--ink)] shadow-[var(--shadow-float)] backdrop:bg-black/25 dark:backdrop:bg-black/55"
    aria-labelledby="settings-title"
    @cancel.prevent="emit('close')"
    @close="props.open && emit('close')"
  >
    <form method="dialog" class="p-5 sm:p-6" @submit.prevent="save">
      <div class="flex items-center justify-between gap-4">
        <h2 id="settings-title" class="font-[var(--font-display)] text-lg font-semibold tracking-[-0.02em]">Settings</h2>
        <button
          type="button"
          class="relative inline-flex size-12 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] sm:size-8"
          aria-label="Close settings"
          @click="emit('close')"
        >
          <X class="size-4" aria-hidden="true" />
        </button>
      </div>

      <section class="mt-6">
        <h3 class="text-sm font-medium">Appearance</h3>
        <div class="mt-2 grid grid-cols-3 gap-2" role="group" aria-label="Appearance">
          <button
            v-for="theme in themes"
            :key="theme.id"
            type="button"
            :aria-pressed="settings.theme === theme.id"
            class="flex h-12 items-center justify-center gap-2 rounded-lg border text-base sm:h-10 sm:text-sm"
            :class="
              settings.theme === theme.id
                ? 'border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]'
                : 'border-[var(--line)] text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]'
            "
            @click="settings.setTheme(theme.id)"
          >
            <component :is="theme.icon" class="size-4" aria-hidden="true" />
            {{ theme.label }}
          </button>
        </div>
      </section>

      <section class="mt-6 border-t border-[var(--line)] pt-5">
        <label for="api-key" class="text-sm font-medium">API key</label>
        <p class="mt-1 text-sm leading-6 text-[var(--ink-faint)]">
          Optional. Used only when the backend enables Bearer API key authentication.
        </p>
        <input
          id="api-key"
          v-model="apiKey"
          name="apiKey"
          type="password"
          autocomplete="off"
          placeholder="Leave blank when auth is off"
          class="mt-3 h-12 w-full rounded-lg bg-[var(--surface)] px-3 text-base ring-1 ring-[var(--line-strong)] placeholder:text-[var(--ink-faint)] focus-visible:-outline-offset-1 sm:h-10 sm:text-sm"
        />
      </section>

      <div class="mt-6 flex justify-end gap-2">
        <button
          type="button"
          class="h-12 rounded-lg px-3 text-base font-medium text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)] sm:h-9 sm:text-sm"
          @click="emit('close')"
        >
          Cancel
        </button>
        <button type="submit" class="h-12 rounded-lg bg-[var(--ink)] px-3 text-base font-medium text-[var(--surface)] hover:opacity-90 sm:h-9 sm:text-sm">
          Save changes
        </button>
      </div>
    </form>
  </dialog>
</template>
