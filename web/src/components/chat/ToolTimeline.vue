<script setup lang="ts">
import { Check, ChevronDown, CircleAlert, LoaderCircle } from 'lucide-vue-next'
import type { StreamError, ToolActivity } from '../../types/agent'
import { isTransientRetry, prettyToolValue, toolLabel } from './toolPresentation'

const props = withDefaults(defineProps<{
  tools: ToolActivity[]
  errors: StreamError[]
  streaming?: boolean
  terminal?: boolean
}>(), { streaming: false, terminal: false })

function retryRunning(error: StreamError): boolean {
  return props.streaming && isTransientRetry(error)
}

</script>

<template>
  <div v-if="props.tools.length || props.errors.length" class="mb-4 min-w-0 space-y-0.5" aria-label="Agent activity" aria-live="polite">
    <details
      v-for="tool in props.tools"
      :key="tool.id"
      class="group text-sm text-[var(--ink-secondary)]"
    >
      <summary class="flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-md focus-visible:outline-offset-1 sm:min-h-8">
        <span class="flex size-4 shrink-0 items-center justify-center" aria-hidden="true">
          <LoaderCircle v-if="tool.status === 'running'" class="size-3.5 animate-spin text-[var(--accent)]" />
          <CircleAlert v-else-if="tool.status === 'error'" class="size-3.5 text-[var(--danger)]" />
          <Check v-else class="size-3.5 text-[var(--accent)]" />
        </span>
        <span
          class="min-w-0 flex-1 truncate"
          :class="tool.status === 'error' ? 'text-[var(--danger)]' : ''"
          :title="tool.toolName"
        >{{ toolLabel(tool.toolName) }}</span>
        <span v-if="tool.status === 'error'" class="shrink-0 text-xs font-medium text-[var(--danger)]">Failed</span>
        <ChevronDown
          v-if="tool.arguments !== undefined || tool.result !== undefined"
          class="size-3.5 text-[var(--ink-faint)] transition-transform group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div
        v-if="tool.arguments !== undefined || tool.result !== undefined"
        class="ml-5 mt-0.5 grid min-w-0 max-w-full gap-1.5 border-l border-[var(--line)] pl-3 text-xs text-[var(--ink-faint)]"
      >
        <div v-if="tool.arguments !== undefined">
          <div class="mb-1 font-medium text-[var(--ink-secondary)]">Parameters</div>
          <pre class="max-h-44 max-w-full overflow-auto whitespace-pre-wrap break-all font-mono leading-5">{{ prettyToolValue(tool.arguments) }}</pre>
        </div>
        <div v-if="tool.result !== undefined">
          <div class="mb-1 font-medium text-[var(--ink-secondary)]">Result</div>
          <pre class="max-h-44 max-w-full overflow-auto whitespace-pre-wrap break-all font-mono leading-5">{{ prettyToolValue(tool.result) }}</pre>
        </div>
      </div>
    </details>

    <details
      v-for="(error, index) in props.errors"
      :key="`${error.code || 'error'}-${index}`"
      class="group min-w-0 rounded-lg px-2.5 py-1.5 text-sm"
      :class="props.terminal && !isTransientRetry(error) ? 'bg-[var(--danger-soft)] text-[var(--danger)]' : 'bg-[var(--surface-muted)] text-[var(--ink-secondary)]'"
    >
      <summary class="flex cursor-pointer list-none items-center gap-2 rounded-md font-medium">
        <LoaderCircle v-if="retryRunning(error)" class="size-4 shrink-0 animate-spin text-[var(--accent)]" aria-hidden="true" />
        <Check v-else-if="isTransientRetry(error)" class="size-4 shrink-0 text-[var(--accent)]" aria-hidden="true" />
        <CircleAlert v-else class="size-4 shrink-0" aria-hidden="true" />
        <span class="min-w-0 flex-1">{{ error.message }}</span>
        <ChevronDown v-if="error.detail || error.code" class="size-4 shrink-0 transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div v-if="error.detail || error.code" class="mt-2 min-w-0 pl-6 text-xs leading-5 opacity-80">
        <div v-if="error.code">Code: {{ error.code }}</div>
        <pre v-if="error.detail" class="mt-1 max-h-36 max-w-full overflow-auto whitespace-pre-wrap break-all font-mono">{{ error.detail }}</pre>
      </div>
    </details>
  </div>
</template>
