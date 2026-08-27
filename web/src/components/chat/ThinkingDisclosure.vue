<script setup lang="ts">
import { ChevronDown, LoaderCircle } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import MarkdownContent from './MarkdownContent.vue'

const props = defineProps<{
  content: string
  streaming: boolean
  keepOpen?: boolean
}>()

const open = ref(props.streaming || props.keepOpen === true)
watch(
  () => props.streaming,
  (streaming, previous) => {
    if (streaming) open.value = true
    else if (previous && !props.keepOpen) open.value = false
  },
)
</script>

<template>
  <details
    v-if="content"
    :open="open"
    class="group mb-4 text-[var(--ink-faint)]"
    @toggle="open = ($event.currentTarget as HTMLDetailsElement).open"
  >
    <summary
      class="flex min-h-10 cursor-pointer list-none items-center gap-1.5 rounded-md text-sm font-normal select-none sm:min-h-8"
    >
      <LoaderCircle v-if="streaming" class="size-3.5 animate-spin text-[var(--accent)]" aria-hidden="true" />
      <span>Thinking</span>
      <ChevronDown
        class="size-3.5 transition-transform group-open:rotate-180"
        aria-hidden="true"
      />
    </summary>
    <div class="border-l border-[var(--line)] pb-1 pl-4 pt-1 text-[var(--ink-secondary)] [&_.prose]:text-[0.9375rem] [&_.prose]:leading-7">
      <MarkdownContent :content="content" />
    </div>
  </details>
</template>
