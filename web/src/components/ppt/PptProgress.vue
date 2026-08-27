<script setup lang="ts">
import { AlertTriangle, Check, Download, ExternalLink, LoaderCircle, PauseCircle, Square } from 'lucide-vue-next'
import { computed } from 'vue'
import type { MessageState } from '../../types/agent'
import { pptProgressState } from './pptProgress'

const props = defineProps<{ thinking: string; content: string; state: MessageState }>()

const progress = computed(() => pptProgressState(props.thinking, props.content, props.state))

const interruptedStep = computed(() =>
  progress.value.steps.find((step) => ['paused', 'failed', 'stopped'].includes(step.status)),
)

const statusDescription = computed(() => {
  const label = interruptedStep.value?.label
  if (progress.value.paused) return 'Waiting for clarification before continuing.'
  if (progress.value.failed) return label ? `Stopped at ${label}. You can retry or continue in this conversation.` : 'Presentation generation failed.'
  if (progress.value.stopped) return label ? `Stopped at ${label}.` : 'Presentation generation was stopped.'
  return ''
})
</script>

<template>
  <section
    v-if="progress.steps.length"
    class="mb-6 border-b border-[var(--line)] pb-5 transition-opacity"
    :class="progress.file ? 'opacity-70' : ''"
    aria-label="Presentation progress"
    aria-live="polite"
  >
    <div class="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <div class="text-sm font-medium text-[var(--ink)]">{{ progress.heading }}</div>
      <div v-if="statusDescription" class="text-xs text-[var(--ink-faint)]">{{ statusDescription }}</div>
    </div>
    <ol class="flex flex-wrap gap-x-5 gap-y-2">
      <li
        v-for="step in progress.steps"
        :key="step.label"
        class="flex items-center gap-2 text-sm"
        :class="step.status === 'failed' ? 'text-[var(--danger)]' : 'text-[var(--ink-secondary)]'"
      >
        <Check v-if="step.status === 'complete'" class="size-4 text-[var(--accent)]" aria-hidden="true" />
        <LoaderCircle v-else-if="step.status === 'running'" class="size-4 animate-spin text-[var(--accent)]" aria-hidden="true" />
        <PauseCircle v-else-if="step.status === 'paused'" class="size-4 text-[var(--ink-faint)]" aria-hidden="true" />
        <AlertTriangle v-else-if="step.status === 'failed'" class="size-4" aria-hidden="true" />
        <Square v-else class="size-3.5 text-[var(--ink-faint)]" aria-hidden="true" />
        <span>{{ step.label }}</span>
      </li>
    </ol>
  </section>

  <section
    v-if="progress.file && state === 'complete'"
    class="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--line)] pt-5"
    aria-label="Presentation file"
  >
    <div class="min-w-0">
      <div class="text-sm font-medium text-[var(--ink)]">Presentation ready</div>
      <div class="mt-0.5 flex items-center gap-1.5 text-xs text-[var(--ink-faint)]">
        <span class="max-w-[min(28rem,70vw)] truncate" :title="progress.file.name">{{ progress.file.name }}</span>
        <span aria-hidden="true">·</span>
        <span>Generated file</span>
      </div>
    </div>
    <div class="flex items-center gap-2">
      <a
        :href="progress.file.url"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex h-9 items-center gap-2 rounded-lg border border-[var(--line)] px-3 text-sm font-medium text-[var(--ink)] hover:bg-[var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]"
      >
        <ExternalLink class="size-4" aria-hidden="true" />
        Open PPT
      </a>
      <a
        :href="progress.file.url"
        :download="progress.file.name"
        class="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--ink)] px-3 text-sm font-medium text-[var(--surface)] hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]"
      >
        <Download class="size-4" aria-hidden="true" />
        Download
      </a>
    </div>
  </section>
</template>
