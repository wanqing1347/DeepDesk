<script setup lang="ts">
import {
  Bot,
  Check,
  FileText,
  MessageCircle,
  Presentation,
  Telescope,
  UploadCloud,
} from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { AGENT_BY_ID } from '../../config/agents'
import type { AgentMode, FileAttachment } from '../../types/agent'

const props = defineProps<{
  mode: AgentMode
  attachment: FileAttachment | null
}>()

const emit = defineEmits<{
  suggestion: [value: string]
  file: [file: File]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const icons = {
  chat: MessageCircle,
  research: Telescope,
  file: FileText,
  skills: Bot,
  ppt: Presentation,
}

const agent = computed(() => AGENT_BY_ID[props.mode])
const modeIcon = computed(() => icons[props.mode])

const attachmentStatus = computed(() => {
  if (!props.attachment) return ''
  if (props.attachment.status === 'uploading') return `Uploading · ${Math.round(props.attachment.progress)}%`
  if (props.attachment.status === 'processing') return 'Processing file…'
  if (props.attachment.status === 'ready') return 'Ready to ask'
  return props.attachment.error || 'Upload failed'
})

function acceptFile(file?: File) {
  if (!file) return
  dragging.value = false
  emit('file', file)
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  acceptFile(event.dataTransfer?.files?.[0])
}
</script>

<template>
  <section class="w-full max-w-[800px]" :aria-labelledby="`agent-heading-${mode}`">
    <div class="text-center">
      <div
        class="mx-auto flex size-11 items-center justify-center rounded-xl border border-[var(--line)] bg-[var(--surface-raised)] text-[var(--accent)] shadow-sm"
        aria-hidden="true"
      >
        <component :is="modeIcon" class="size-5" />
      </div>
      <p class="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--ink-faint)]">
        {{ agent.label }}
      </p>
      <h1
        :id="`agent-heading-${mode}`"
        class="mt-1.5 font-[var(--font-display)] text-[clamp(1.75rem,5vw,2.2rem)] font-semibold tracking-[-0.035em] text-[var(--ink)]"
      >
        {{ agent.headline }}
      </h1>
      <p class="mx-auto mt-2 max-w-[620px] text-sm leading-6 text-[var(--ink-secondary)] sm:text-[0.95rem]">
        {{ agent.description }}
      </p>
    </div>

    <div
      v-if="mode === 'file'"
      class="mt-6"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop="onDrop"
    >
      <input
        ref="fileInput"
        type="file"
        class="sr-only"
        accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/png,image/jpeg"
        aria-label="Choose a file from File mode"
        @change="acceptFile(($event.target as HTMLInputElement).files?.[0]); ($event.target as HTMLInputElement).value = ''"
      />

      <button
        v-if="!attachment"
        type="button"
        class="group flex w-full flex-col items-center justify-center rounded-2xl border border-dashed px-5 py-7 text-center transition-colors focus-visible:outline-offset-2 sm:py-8"
        :class="
          dragging
            ? 'border-[var(--accent)] bg-[var(--accent-soft)]'
            : 'border-[var(--line-strong)] bg-[var(--surface)] hover:border-[var(--accent)] hover:bg-[var(--surface-raised)]'
        "
        @click="fileInput?.click()"
      >
        <span class="flex size-10 items-center justify-center rounded-xl bg-[var(--surface-muted)] text-[var(--accent)]">
          <UploadCloud class="size-5" aria-hidden="true" />
        </span>
        <span class="mt-3 text-sm font-semibold text-[var(--ink)]">Drop a file here or browse</span>
        <span class="mt-1 text-xs leading-5 text-[var(--ink-faint)]">
          PDF, DOCX, TXT, PNG, JPG, or JPEG · up to 50 MB
        </span>
      </button>

      <div
        v-else
        class="flex items-center gap-3 rounded-2xl border border-[var(--line)] bg-[var(--surface)] px-4 py-3 text-left"
        aria-live="polite"
      >
        <span class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
          <FileText class="size-5" aria-hidden="true" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-[var(--ink)]">{{ attachment.name }}</p>
          <p class="mt-0.5 text-xs text-[var(--ink-faint)]">{{ attachmentStatus }}</p>
        </div>
      </div>
    </div>

    <div class="mt-5 flex flex-wrap justify-center gap-2" :aria-label="`${agent.label} capabilities`">
      <span
        v-for="capability in agent.capabilities"
        :key="capability"
        class="inline-flex min-h-8 items-center gap-1.5 rounded-full border border-[var(--line)] bg-[var(--surface)] px-3 text-xs font-medium text-[var(--ink-secondary)]"
      >
        <Check class="size-3.5 text-[var(--accent)]" aria-hidden="true" />
        {{ capability }}
      </span>
    </div>

    <div class="mt-6">
      <p class="mb-2 px-1 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--ink-faint)]">
        Try a prompt
      </p>
      <div class="grid gap-2 sm:grid-cols-3">
        <button
          v-for="suggestion in agent.suggestions"
          :key="suggestion"
          type="button"
          class="min-h-[72px] rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3.5 py-3 text-left text-sm leading-5 text-[var(--ink-secondary)] transition-colors hover:border-[var(--line-strong)] hover:bg-[var(--surface-raised)] hover:text-[var(--ink)]"
          @click="emit('suggestion', suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>
    </div>
  </section>
</template>
