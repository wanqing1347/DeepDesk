<script setup lang="ts">
import { ArrowUp, Paperclip, Square } from 'lucide-vue-next'
import { computed, nextTick, ref, watch } from 'vue'
import { AGENT_BY_ID } from '../../config/agents'
import type { AgentMode, FileAttachment } from '../../types/agent'
import AgentModeSelector from './AgentModeSelector.vue'
import FileAttachmentBar from './FileAttachmentBar.vue'

const props = defineProps<{
  modelValue: string
  mode: AgentMode
  attachment: FileAttachment | null
  streaming: boolean
  disabled?: boolean
  hideModeSelector?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:mode': [mode: AgentMode]
  send: []
  stop: []
  file: [file: File]
  removeFile: []
  retryFile: []
}>()

const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const composing = ref(false)

const placeholder = computed(() => AGENT_BY_ID[props.mode].placeholder)

const canSend = computed(() => {
  if (
    props.disabled ||
    props.streaming ||
    props.attachment?.status === 'uploading' ||
    props.attachment?.status === 'processing'
  ) return false
  return props.modelValue.trim().length > 0 || (props.mode === 'file' && props.attachment?.status === 'ready')
})

function resize() {
  const element = textarea.value
  if (!element) return
  element.style.height = '0px'
  element.style.height = `${Math.min(element.scrollHeight, 220)}px`
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || composing.value) return
  event.preventDefault()
  if (canSend.value) emit('send')
}

function acceptFile(file?: File) {
  if (!file) return
  dragging.value = false
  emit('file', file)
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  acceptFile(event.dataTransfer?.files?.[0])
}

watch(() => props.modelValue, () => nextTick(resize), { immediate: true })

defineExpose({ focus: () => textarea.value?.focus() })
</script>

<template>
  <div
    class="relative mx-auto w-full max-w-[800px]"
    @dragenter.prevent="dragging = true"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop="onDrop"
  >
    <div
      class="overflow-hidden rounded-[14px] bg-[var(--surface-raised)] shadow-[var(--shadow-float)] ring-1 transition-[box-shadow]"
      :class="dragging ? 'ring-[var(--accent)]' : 'ring-[var(--line-strong)] focus-within:ring-[var(--ink-faint)]'"
    >
      <div
        v-if="dragging"
        class="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[14px] bg-[var(--surface-raised)]/95 text-sm font-medium text-[var(--accent)]"
      >
        Drop a PDF, DOCX, TXT, PNG, JPG, or JPEG
      </div>

      <FileAttachmentBar
        v-if="attachment"
        :attachment="attachment"
        @remove="emit('removeFile')"
        @retry="emit('retryFile')"
      />

      <label class="sr-only" for="agent-composer">Message</label>
      <textarea
        id="agent-composer"
        ref="textarea"
        name="message"
        :value="modelValue"
        rows="1"
        :disabled="disabled"
        :placeholder="placeholder"
        class="block max-h-[220px] min-h-[68px] w-full resize-none bg-transparent px-4 pb-1.5 pt-3.5 text-base leading-7 text-[var(--ink)] placeholder:text-[var(--ink-faint)] focus:outline-none focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 sm:min-h-[64px]"
        @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
        @keydown="onKeydown"
        @compositionstart="composing = true"
        @compositionend="composing = false"
      />

      <div class="flex min-w-0 items-end justify-between gap-2 px-2.5 pb-2">
        <div class="flex min-w-0 flex-1 items-center gap-1">
          <input
            ref="fileInput"
            class="sr-only"
            type="file"
            name="file"
            accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/png,image/jpeg"
            aria-label="Choose a file"
            @change="acceptFile(($event.target as HTMLInputElement).files?.[0]); ($event.target as HTMLInputElement).value = ''"
          />
          <button
            type="button"
            class="relative inline-flex size-12 shrink-0 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] disabled:opacity-40 sm:size-8"
            aria-label="Attach file"
            :disabled="streaming || attachment?.status === 'uploading' || attachment?.status === 'processing'"
            @click="fileInput?.click()"
          >
            <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
            <Paperclip class="size-4" aria-hidden="true" />
          </button>
          <AgentModeSelector
            v-if="!hideModeSelector"
            :model-value="mode"
            :disabled="disabled || streaming"
            compact
            @update:model-value="emit('update:mode', $event)"
          />
        </div>

        <button
          v-if="streaming"
          type="button"
          class="relative inline-flex size-12 shrink-0 items-center justify-center rounded-[10px] bg-[var(--ink)] text-[var(--surface)] hover:opacity-90 sm:size-9"
          aria-label="Stop generating"
          @click="emit('stop')"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          <Square class="size-3.5 fill-current" aria-hidden="true" />
        </button>
        <button
          v-else
          type="button"
          class="relative inline-flex size-12 shrink-0 items-center justify-center rounded-[10px] bg-[var(--ink)] text-[var(--surface)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-25 sm:size-9"
          aria-label="Send message"
          :disabled="!canSend"
          @click="emit('send')"
        >
          <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
          <ArrowUp class="size-4" aria-hidden="true" />
        </button>
      </div>
    </div>
    <p class="mt-1.5 px-3 text-center text-[0.6875rem] leading-5 text-[var(--ink-faint)]">
      Enter to send · Shift+Enter for a new line
    </p>
  </div>
</template>
