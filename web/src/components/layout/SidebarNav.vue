<script setup lang="ts">
import {
  Menu,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Settings,
  Trash2,
  X,
} from 'lucide-vue-next'
import { computed } from 'vue'
import type { SessionListItem } from '../../types/api'

const props = defineProps<{
  sessions: SessionListItem[]
  currentId?: string
  collapsed?: boolean
  mobile?: boolean
  loading?: boolean
  error?: string
}>()

const emit = defineEmits<{
  new: []
  select: [id: string]
  delete: [id: string]
  toggle: []
  settings: []
  close: []
  retry: []
}>()

interface SessionGroup {
  label: string
  items: SessionListItem[]
}

const groups = computed<SessionGroup[]>(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const buckets = new Map<string, SessionListItem[]>()

  for (const item of props.sessions) {
    const date = item.updateTime || item.createTime ? new Date(item.updateTime || item.createTime || '') : null
    const time = date && !Number.isNaN(date.getTime()) ? date.getTime() : 0
    const label = time >= today.getTime() ? 'Today' : time >= yesterday.getTime() ? 'Yesterday' : 'Previous'
    if (!buckets.has(label)) buckets.set(label, [])
    buckets.get(label)!.push(item)
  }

  return ['Today', 'Yesterday', 'Previous']
    .filter((label) => buckets.has(label))
    .map((label) => ({ label, items: buckets.get(label)! }))
})

function title(item: SessionListItem): string {
  return item.question?.trim() || 'Untitled conversation'
}
</script>

<template>
  <aside
    class="flex h-full shrink-0 flex-col border-r border-[var(--line)] bg-[var(--surface)] transition-[width]"
    :class="mobile ? 'w-[min(88vw,292px)]' : collapsed ? 'w-16' : 'w-[236px]'"
    aria-label="Conversation sidebar"
  >
    <div class="flex h-14 items-center gap-2 px-2.5">
      <button
        v-if="mobile"
        type="button"
        class="relative inline-flex size-12 items-center justify-center rounded-lg text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]"
        aria-label="Close sidebar"
        @click="emit('close')"
      >
        <X class="size-4" aria-hidden="true" />
      </button>
      <div v-else-if="!collapsed" class="px-1 font-[var(--font-display)] text-[15px] font-semibold tracking-[-0.02em] text-[var(--ink)]">
        DeepDesk
      </div>
      <div class="ml-auto">
        <button
          v-if="!mobile"
          type="button"
          class="relative inline-flex size-9 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)]"
          :aria-label="collapsed ? 'Expand sidebar' : 'Collapse sidebar'"
          @click="emit('toggle')"
        >
          <PanelLeftOpen v-if="collapsed" class="size-4" aria-hidden="true" />
          <PanelLeftClose v-else class="size-4" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div class="px-2 pb-2">
      <button
        type="button"
        class="relative flex h-12 w-full items-center gap-2 rounded-lg px-2.5 text-base font-medium text-[var(--ink)] hover:bg-[var(--surface-muted)] md:h-9 md:text-sm"
        :class="collapsed && !mobile ? 'justify-center px-0' : ''"
        @click="emit('new')"
      >
        <PenLine class="size-4 shrink-0" aria-hidden="true" />
        <span v-if="!collapsed || mobile">New chat</span>
        <span v-if="collapsed && !mobile" class="sr-only">New chat</span>
      </button>
    </div>

    <div
      v-if="!collapsed || mobile"
      class="min-h-0 flex-1 overflow-y-auto px-2 pb-4"
      :aria-busy="loading ? 'true' : undefined"
    >
      <div v-if="loading && !sessions.length" class="space-y-2 px-2 py-3" aria-label="Loading conversations">
        <div v-for="index in 4" :key="index" class="flex h-9 items-center gap-2" aria-hidden="true">
          <div class="size-3.5 shrink-0 animate-pulse rounded bg-[var(--surface-hover)]" />
          <div class="h-3 animate-pulse rounded bg-[var(--surface-hover)]" :class="index % 2 ? 'w-28' : 'w-36'" />
        </div>
      </div>
      <div v-else-if="error && !sessions.length" class="px-2 py-3 text-xs leading-5 text-[var(--ink-faint)]">
        <div>History is unavailable. New chats still work.</div>
        <button
          type="button"
          class="relative mt-2 inline-flex min-h-12 items-center rounded-md px-2 text-base font-medium text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] sm:min-h-8 sm:text-xs"
          @click="emit('retry')"
        >
          Try again
        </button>
      </div>
      <template v-for="group in groups" :key="group.label">
        <div class="mb-1 mt-3.5 px-2 text-[0.6875rem] font-medium tracking-[0.01em] text-[var(--ink-faint)] first:mt-1">{{ group.label }}</div>
        <div class="space-y-0.5">
          <div v-for="session in group.items" :key="session.conversationId" class="group relative">
            <button
              type="button"
              class="flex h-12 w-full items-center gap-2 rounded-lg px-2 text-left text-base text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] md:h-9 md:text-sm"
              :class="session.conversationId === currentId ? 'bg-[var(--surface-muted)] text-[var(--ink)]' : ''"
              :aria-current="session.conversationId === currentId ? 'page' : undefined"
              @click="emit('select', session.conversationId)"
            >
              <MessageSquare class="size-3.5 shrink-0 text-[var(--ink-faint)]" aria-hidden="true" />
              <span class="truncate pr-7">{{ title(session) }}</span>
            </button>
            <button
              type="button"
              class="absolute right-0 top-1/2 inline-flex size-12 -translate-y-1/2 items-center justify-center rounded-md text-[var(--ink-faint)] opacity-100 hover:bg-[var(--surface-hover)] hover:text-[var(--danger)] md:right-1 md:size-7 md:opacity-0 md:focus:opacity-100 md:group-hover:opacity-100"
              :aria-label="`Delete ${title(session)}`"
              @click.stop="emit('delete', session.conversationId)"
            >
              <Trash2 class="size-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </template>
    </div>
    <div v-else class="min-h-0 flex-1">
      <div class="flex justify-center pt-1 text-[var(--ink-faint)]" aria-hidden="true">
        <Menu class="size-4" />
      </div>
    </div>

    <div class="border-t border-[var(--line)] p-2" :class="mobile ? 'pb-[calc(8px+env(safe-area-inset-bottom))]' : ''">
      <button
        type="button"
        class="relative flex h-12 w-full items-center gap-2 rounded-lg px-2.5 text-base text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] md:h-9 md:text-sm"
        :class="collapsed && !mobile ? 'justify-center px-0' : ''"
        @click="emit('settings')"
      >
        <Settings class="size-4 shrink-0" aria-hidden="true" />
        <span v-if="!collapsed || mobile">Settings</span>
        <span v-if="collapsed && !mobile" class="sr-only">Settings</span>
      </button>
    </div>
  </aside>
</template>
