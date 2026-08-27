<script setup lang="ts">
import { FileText, LoaderCircle, RotateCcw, X } from 'lucide-vue-next'
import { computed } from 'vue'
import type { FileAttachment } from '../../types/agent'

const props = defineProps<{ attachment: FileAttachment }>()
const emit = defineEmits<{ remove: []; retry: [] }>()

const canRemove = computed(() => props.attachment.status !== 'processing')
const removeLabel = computed(() =>
  props.attachment.status === 'uploading'
    ? 'Cancel file upload'
    : props.attachment.status === 'processing'
      ? 'File is being processed'
      : 'Remove attached file',
)

function formatSize(bytes?: number): string {
  if (bytes === undefined) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<template>
  <div class="mx-3 mt-3 flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-3 py-2.5">
    <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-[var(--surface)] text-[var(--ink-secondary)]">
      <LoaderCircle
        v-if="props.attachment.status === 'uploading' || props.attachment.status === 'processing'"
        class="size-4 animate-spin"
        aria-hidden="true"
      />
      <FileText v-else class="size-4" aria-hidden="true" />
    </span>
    <div class="min-w-0 flex-1">
      <div class="truncate text-sm font-medium text-[var(--ink)]">{{ props.attachment.name }}</div>
      <div class="mt-0.5 flex items-center gap-2 text-xs text-[var(--ink-faint)]" aria-live="polite">
        <span v-if="props.attachment.status === 'uploading'">Uploading {{ props.attachment.progress }}%</span>
        <span v-else-if="props.attachment.status === 'processing'">Processing file…</span>
        <span v-else-if="props.attachment.status === 'error'" class="text-[var(--danger)]">{{ props.attachment.error || 'Upload failed' }}</span>
        <span v-else>{{ formatSize(props.attachment.size) || 'Ready' }}</span>
      </div>
      <div v-if="props.attachment.status === 'uploading'" class="mt-2 h-1 overflow-hidden rounded-full bg-[var(--line)]">
        <div
          class="h-full rounded-full bg-[var(--accent)] transition-[width]"
          :style="{ width: `${props.attachment.progress}%` }"
          aria-hidden="true"
        />
      </div>
    </div>
    <button
      v-if="props.attachment.status === 'error' && props.attachment.retryable"
      type="button"
      class="relative inline-flex size-12 shrink-0 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] sm:size-8"
      aria-label="Retry file upload"
      @click="emit('retry')"
    >
      <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
      <RotateCcw class="size-4" aria-hidden="true" />
    </button>
    <button
      type="button"
      class="relative inline-flex size-12 shrink-0 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-35 sm:size-8"
      :aria-label="removeLabel"
      :disabled="!canRemove"
      @click="emit('remove')"
    >
      <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
      <X class="size-4" aria-hidden="true" />
    </button>
  </div>
</template>
