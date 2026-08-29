<script setup lang="ts">
import { FilePlus2, FileText, Paperclip, RefreshCw, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { listFiles } from '../../api/file'
import type { FileInfo } from '../../types/api'
import { filePickerItems, filePickerSelectable } from './filePicker'

const props = defineProps<{
  disabled?: boolean
  currentFileId?: string
}>()

const emit = defineEmits<{
  file: [file: File]
  select: [file: FileInfo]
}>()

const root = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const open = ref(false)
const loading = ref(false)
const error = ref('')
const files = ref<FileInfo[]>([])

const readyFiles = computed(() => files.value.filter(filePickerSelectable))

function formatSize(bytes?: number | null): string {
  if (bytes === undefined || bytes === null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function statusLabel(file: FileInfo): string {
  const normalized = file.status.trim().toUpperCase()
  if (normalized === 'SUCCESS') return formatSize(file.fileSize) || 'Ready'
  if (normalized === 'PROCESSING') return 'Processing'
  if (normalized === 'FAILED') return 'Failed'
  return file.status || 'Unavailable'
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const list = await listFiles()
    files.value = filePickerItems(list)
  } catch (cause) {
    files.value = []
    error.value = cause instanceof Error ? cause.message : 'Could not load existing files.'
  } finally {
    loading.value = false
  }
}

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}

function chooseUpload() {
  fileInput.value?.click()
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  open.value = false
  emit('file', file)
}

function chooseExisting(file: FileInfo) {
  if (!filePickerSelectable(file)) return
  open.value = false
  emit('select', file)
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!open.value) return
  const target = event.target
  if (target instanceof Node && !root.value?.contains(target)) open.value = false
}

watch(open, (value) => {
  if (value) void refresh()
})

onMounted(() => document.addEventListener('pointerdown', onDocumentPointerDown))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocumentPointerDown))
</script>

<template>
  <div ref="root" class="relative shrink-0" @keydown.esc="open = false">
    <input
      ref="fileInput"
      class="sr-only"
      type="file"
      name="file"
      accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/png,image/jpeg"
      aria-label="Choose a new file"
      @change="onFileChange"
    />

    <button
      type="button"
      class="relative inline-flex size-12 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-40 sm:size-8"
      aria-label="Attach or choose file"
      :aria-expanded="open"
      aria-haspopup="menu"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
      <Paperclip class="size-4" aria-hidden="true" />
    </button>

    <div
      v-if="open"
      class="absolute bottom-[calc(100%+0.5rem)] left-0 z-30 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--surface-raised)] shadow-[var(--shadow-float)]"
      role="menu"
      aria-label="File options"
    >
      <div class="border-b border-[var(--line)] p-2">
        <button
          type="button"
          class="flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-[var(--ink)] hover:bg-[var(--surface-muted)]"
          role="menuitem"
          @click="chooseUpload"
        >
          <FilePlus2 class="size-4 text-[var(--accent)]" aria-hidden="true" />
          Upload new file
        </button>
      </div>

      <div class="flex items-center justify-between px-3 pb-1 pt-2.5">
        <span class="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-[var(--ink-faint)]">Existing files</span>
        <button
          type="button"
          class="inline-flex size-8 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] disabled:opacity-40"
          aria-label="Refresh file list"
          :disabled="loading"
          @click="refresh"
        >
          <RefreshCw class="size-3.5" :class="{ 'animate-spin': loading }" aria-hidden="true" />
        </button>
      </div>

      <div class="max-h-64 overflow-y-auto p-2 pt-1">
        <div v-if="loading && files.length === 0" class="px-3 py-5 text-center text-xs text-[var(--ink-faint)]">
          Loading files…
        </div>

        <div v-else-if="error" class="rounded-lg bg-[var(--surface-muted)] px-3 py-3 text-xs leading-5 text-[var(--ink-secondary)]">
          <div class="flex items-start gap-2">
            <X class="mt-0.5 size-3.5 shrink-0 text-[var(--danger)]" aria-hidden="true" />
            <span>{{ error }}</span>
          </div>
        </div>

        <div v-else-if="files.length === 0" class="px-3 py-5 text-center text-xs text-[var(--ink-faint)]">
          No existing files yet.
        </div>

        <button
          v-for="file in files"
          v-else
          :key="file.fileId"
          type="button"
          class="flex min-h-12 w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45"
          :class="file.fileId === currentFileId ? 'bg-[var(--accent-soft)]' : 'hover:bg-[var(--surface-muted)]'"
          role="menuitem"
          :disabled="!filePickerSelectable(file)"
          @click="chooseExisting(file)"
        >
          <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-[var(--surface)] text-[var(--ink-secondary)]">
            <FileText class="size-4" aria-hidden="true" />
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm font-medium text-[var(--ink)]">{{ file.fileName }}</span>
            <span class="mt-0.5 block text-xs text-[var(--ink-faint)]">
              {{ file.fileId === currentFileId ? 'Attached' : statusLabel(file) }}
            </span>
          </span>
        </button>
      </div>

      <div v-if="readyFiles.length > 0" class="border-t border-[var(--line)] px-3 py-2 text-[0.6875rem] text-[var(--ink-faint)]">
        {{ readyFiles.length }} ready {{ readyFiles.length === 1 ? 'file' : 'files' }}
      </div>
    </div>
  </div>
</template>
