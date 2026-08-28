<script setup lang="ts">
import { computed } from 'vue'
import { AGENT_BY_ID } from '../../config/agents'
import type { AgentMode } from '../../types/agent'

const props = defineProps<{
  mode: AgentMode
}>()

const agent = computed(() => AGENT_BY_ID[props.mode])

const helper = computed(() => {
  if (props.mode === 'research') return 'Uses multiple sources and returns a researched answer with citations.'
  if (props.mode === 'file') return 'Attach a file from the composer to ask about its contents.'
  if (props.mode === 'skills') return 'Use tools and skills when the task needs more than a direct answer.'
  if (props.mode === 'ppt') return 'Describe the audience, purpose, and slide count you want.'
  return ''
})
</script>

<template>
  <section class="w-full max-w-[800px] text-center" :aria-labelledby="`agent-heading-${mode}`">
    <h1
      :id="`agent-heading-${mode}`"
      class="font-[var(--font-display)] text-[clamp(1.55rem,4vw,2rem)] font-semibold tracking-[-0.035em] text-[var(--ink)]"
    >
      {{ agent.headline }}
    </h1>
    <p
      v-if="helper"
      class="mx-auto mt-1.5 max-w-[560px] text-sm leading-5 text-[var(--ink-faint)]"
    >
      {{ helper }}
    </p>
  </section>
</template>
