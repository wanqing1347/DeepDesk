<script setup lang="ts">
import { ExternalLink } from 'lucide-vue-next'
import type { SourceReference } from '../../types/agent'

defineProps<{ sources: SourceReference[] }>()
</script>

<template>
  <section v-if="sources.length" class="mt-6 border-t border-[var(--line)] pt-4" aria-labelledby="sources-heading">
    <h3 id="sources-heading" class="mb-2.5 text-xs font-medium text-[var(--ink-secondary)]">Sources</h3>
    <div class="grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
      <a
        v-for="(source, index) in sources"
        :key="source.url"
        :href="source.url"
        target="_blank"
        rel="noopener noreferrer"
        class="group flex min-w-0 items-start gap-2.5 rounded-lg px-1 py-2 text-left hover:bg-[var(--surface-muted)] focus-visible:outline-offset-1"
      >
        <span
          class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md bg-[var(--surface-muted)] text-xs font-medium text-[var(--ink-secondary)]"
          aria-hidden="true"
        >
          {{ index + 1 }}
        </span>
        <span class="min-w-0 flex-1">
          <span class="line-clamp-2 block text-sm font-medium leading-5 text-[var(--ink-secondary)] group-hover:text-[var(--ink)]">{{ source.title }}</span>
          <span class="mt-0.5 flex items-center gap-1 text-xs text-[var(--ink-faint)]">
            <span class="truncate">{{ source.domain }}</span>
            <ExternalLink class="size-3 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
          </span>
        </span>
      </a>
    </div>
  </section>
</template>
