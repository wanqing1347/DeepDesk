<script setup lang="ts">
import { Bot, FileText, MessageCircle, Presentation, Telescope } from 'lucide-vue-next'
import { AGENTS } from '../../config/agents'
import type { AgentMode } from '../../types/agent'

const props = defineProps<{ modelValue: AgentMode; compact?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [mode: AgentMode] }>()

const icons = {
  chat: MessageCircle,
  research: Telescope,
  file: FileText,
  skills: Bot,
  ppt: Presentation,
}
</script>

<template>
  <div
    class="flex max-w-full items-center gap-1 overflow-x-auto pb-0.5"
    role="group"
    aria-label="Agent mode"
  >
    <button
      v-for="agent in AGENTS"
      :key="agent.id"
      type="button"
      :aria-pressed="props.modelValue === agent.id"
      :disabled="props.disabled"
      class="relative inline-flex h-12 shrink-0 items-center gap-1.5 rounded-lg px-3 text-base transition-colors focus-visible:outline-offset-1 disabled:cursor-not-allowed disabled:opacity-45 sm:h-8 sm:px-2.5 sm:text-sm"
      :class="
        props.modelValue === agent.id
          ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
          : 'text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink-secondary)]'
      "
      :title="agent.description"
      @click="emit('update:modelValue', agent.id)"
    >
      <component :is="icons[agent.id]" class="size-5 shrink-0 sm:size-4" aria-hidden="true" />
      <span>{{ compact ? agent.shortLabel : agent.label }}</span>
      <span class="absolute left-1/2 top-1/2 size-[max(100%,3rem)] -translate-x-1/2 -translate-y-1/2 pointer-fine:hidden" aria-hidden="true" />
    </button>
  </div>
</template>
