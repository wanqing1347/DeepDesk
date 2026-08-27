<script setup lang="ts">
import { ChevronDown, CircleAlert } from 'lucide-vue-next'
import type { StreamError } from '../../types/agent'

defineProps<{
  error: StreamError
  actionLabel?: string
  actionDisabled?: boolean
}>()

const emit = defineEmits<{ action: [] }>()
</script>

<template>
  <div
    class="rounded-lg bg-[var(--danger-soft)] px-3 py-2 text-base leading-6 text-[var(--danger)] sm:text-sm sm:leading-5"
    role="alert"
  >
    <div class="flex items-start gap-2">
      <CircleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <div class="font-medium">{{ error.message }}</div>
          <button
            v-if="actionLabel"
            type="button"
            class="relative inline-flex min-h-12 items-center rounded-md px-2 text-base font-medium text-[var(--danger)] hover:bg-[var(--surface-muted)] disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-8 sm:text-xs"
            :disabled="actionDisabled"
            @click="emit('action')"
          >
            {{ actionLabel }}
          </button>
        </div>
        <details v-if="error.code || error.detail" class="group mt-1">
          <summary class="flex min-h-12 w-fit cursor-pointer list-none items-center gap-1 rounded-md text-xs opacity-80 sm:min-h-8">
            Details
            <ChevronDown class="size-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <div class="pb-1 text-xs leading-5 opacity-80">
            <div v-if="error.code">Code: {{ error.code }}</div>
            <div v-if="error.detail" class="whitespace-pre-wrap break-words">{{ error.detail }}</div>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>
