<script setup lang="ts">
import { Check, CirclePause, LoaderCircle } from 'lucide-vue-next'
import { computed } from 'vue'
import { researchProgressState } from './researchProgress'

const props = defineProps<{ thinking: string; content: string; streaming: boolean }>()
const progress = computed(() => researchProgressState(props.thinking, props.content, props.streaming))
</script>

<template>
  <section
    v-if="progress.steps.length"
    class="mb-6 border-b border-[var(--line)] pb-5 transition-opacity"
    :class="progress.subdued ? 'opacity-55' : ''"
    aria-label="Research progress"
    aria-live="polite"
  >
    <div class="mb-3 text-sm font-medium" :class="progress.paused ? 'text-[var(--ink-secondary)]' : 'text-[var(--ink)]'">
      {{ progress.heading }}
    </div>
    <ol class="space-y-2">
      <li
        v-for="step in progress.steps"
        :key="step.label"
        class="flex items-center gap-2.5 text-sm"
        :class="step.status === 'running' ? 'text-[var(--ink)]' : 'text-[var(--ink-secondary)]'"
      >
        <Check v-if="step.status === 'complete'" class="size-4 text-[var(--ink-faint)]" aria-hidden="true" />
        <LoaderCircle v-else-if="step.status === 'running'" class="size-4 animate-spin text-[var(--accent)]" aria-hidden="true" />
        <CirclePause v-else class="size-4 text-[var(--ink-faint)]" aria-hidden="true" />
        <span>{{ step.label }}</span>
      </li>
    </ol>
  </section>
</template>
