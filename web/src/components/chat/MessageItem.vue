<script setup lang="ts">
import { Check, Copy, FileText, RefreshCw, Send } from 'lucide-vue-next'
import { ref } from 'vue'
import type { ConversationMessage } from '../../types/agent'
import PptProgress from '../ppt/PptProgress.vue'
import ResearchProgress from '../research/ResearchProgress.vue'
import MarkdownContent from './MarkdownContent.vue'
import SourcesList from './SourcesList.vue'
import ThinkingDisclosure from './ThinkingDisclosure.vue'
import ToolTimeline from './ToolTimeline.vue'

const props = withDefaults(defineProps<{ message: ConversationMessage; busy?: boolean }>(), { busy: false })
const emit = defineEmits<{
  recommend: [question: string]
  retry: [messageId: string]
  resend: [content: string]
}>()
const answerCopied = ref(false)
const userCopied = ref(false)

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.append(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

async function copyAnswer() {
  if (!props.message.content) return
  await writeClipboard(props.message.content)
  answerCopied.value = true
  window.setTimeout(() => (answerCopied.value = false), 1600)
}

async function copyUserMessage() {
  if (props.message.role !== 'user' || !props.message.content) return
  await writeClipboard(props.message.content)
  userCopied.value = true
  window.setTimeout(() => (userCopied.value = false), 1600)
}
</script>

<template>
  <article v-if="message.role === 'user'" class="group flex justify-end pb-2 pt-4 sm:pb-2.5 sm:pt-5">
    <div class="max-w-[88%] sm:max-w-[76%]">
      <div
        v-if="message.attachment"
        class="mb-2 ml-auto flex w-fit max-w-full items-center gap-2 text-xs text-[var(--ink-faint)]"
      >
        <FileText class="size-3.5 shrink-0" aria-hidden="true" />
        <span class="truncate">{{ message.attachment.name }}</span>
      </div>
      <div class="rounded-[12px] bg-[var(--surface-muted)] px-4 py-2.5 text-base leading-7 text-[var(--ink)]">
        {{ message.content }}
      </div>
      <div class="message-actions mt-1 flex justify-end gap-1" aria-label="Message actions">
        <button
          type="button"
          class="relative inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-45"
          :aria-label="userCopied ? 'Copied message' : 'Copy message'"
          @click="copyUserMessage"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          <Check v-if="userCopied" class="size-3.5" aria-hidden="true" />
          <Copy v-else class="size-3.5" aria-hidden="true" />
          <span>{{ userCopied ? 'Copied' : 'Copy' }}</span>
        </button>
        <button
          type="button"
          class="relative inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-45"
          :disabled="busy"
          aria-label="Resend message"
          @click="emit('resend', message.content)"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          <Send class="size-3.5" aria-hidden="true" />
          <span>Resend</span>
        </button>
      </div>
    </div>
  </article>

  <article v-else class="pb-7 pt-3 sm:pb-9 sm:pt-3.5">
    <p
      v-if="message.state !== 'error'"
      class="sr-only"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{
        message.state === 'streaming'
          ? 'Assistant response is streaming.'
          : message.state === 'stopped'
            ? 'Assistant response stopped.'
            : 'Assistant response complete.'
      }}
    </p>
    <div class="max-w-[72ch]">
      <ResearchProgress
        v-if="message.agentMode === 'research'"
        :thinking="message.thinking"
        :content="message.content"
        :streaming="message.state === 'streaming'"
      />
      <PptProgress
        v-if="message.agentMode === 'ppt'"
        :thinking="message.thinking"
        :content="message.content"
        :state="message.state"
      />

      <ThinkingDisclosure
        :content="message.thinking"
        :streaming="message.state === 'streaming'"
        :keep-open="message.errors.length > 0"
      />
      <ToolTimeline
        :tools="message.tools"
        :errors="message.errors"
        :streaming="message.state === 'streaming'"
        :terminal="message.state === 'error'"
      />

      <div v-if="message.agentMode === 'research' && message.content" class="mb-3 text-sm font-medium text-[var(--ink-secondary)]">
        Final report
      </div>
      <MarkdownContent v-if="message.content" :content="message.content" />

      <div
        v-else-if="message.state === 'streaming'"
        class="flex items-center gap-2 text-sm text-[var(--ink-faint)]"
        aria-live="polite"
      >
        <span class="size-1.5 animate-pulse rounded-full bg-[var(--accent)]" aria-hidden="true" />
        Working…
      </div>

      <div v-if="message.state === 'stopped'" class="mt-3 text-sm text-[var(--ink-faint)]">Generation stopped.</div>

      <div
        v-if="message.state === 'error'"
        class="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg bg-[var(--danger-soft)] px-3 py-2 text-base text-[var(--danger)] sm:text-sm"
        role="alert"
      >
        <span class="font-medium">Generation failed.</span>
        <button
          type="button"
          class="relative min-h-8 rounded-md px-2 font-medium underline decoration-current/35 underline-offset-4 hover:decoration-current disabled:cursor-not-allowed disabled:opacity-45"
          :disabled="busy"
          @click="emit('retry', message.id)"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          Try again
        </button>
      </div>

      <SourcesList :sources="message.references" />

      <div v-if="message.recommendations.length" class="mt-5 flex flex-wrap gap-2" aria-label="Suggested follow-up questions">
        <button
          v-for="question in message.recommendations"
          :key="question"
          type="button"
          class="min-h-12 rounded-lg border border-[var(--line)] px-3 py-2 text-left text-base text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] sm:min-h-9 sm:py-1.5 sm:text-sm"
          @click="emit('recommend', question)"
        >
          {{ question }}
        </button>
      </div>

      <div
        v-if="message.state !== 'streaming' && (message.content || message.state === 'complete' || message.state === 'stopped')"
        class="mt-3.5 flex items-center gap-1"
        aria-label="Response actions"
      >
        <button
          v-if="message.content"
          type="button"
          class="relative inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)]"
          :aria-label="answerCopied ? 'Copied response' : 'Copy response'"
          @click="copyAnswer"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          <Check v-if="answerCopied" class="size-3.5" aria-hidden="true" />
          <Copy v-else class="size-3.5" aria-hidden="true" />
          <span>{{ answerCopied ? 'Copied' : 'Copy' }}</span>
        </button>
        <button
          v-if="message.state === 'complete' || message.state === 'stopped'"
          type="button"
          class="relative inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-45"
          :disabled="busy"
          aria-label="Regenerate response"
          title="Run the same question again as a new server attempt"
          @click="emit('retry', message.id)"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          <RefreshCw class="size-3.5" aria-hidden="true" />
          <span>Regenerate</span>
        </button>
      </div>
    </div>
  </article>
</template>
