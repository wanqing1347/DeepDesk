<script setup lang="ts">
import {
  Bot,
  FileText,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Presentation,
  Search,
  Settings,
  Telescope,
  Trash2,
  X,
} from 'lucide-vue-next'
import { computed, nextTick, ref, watch } from 'vue'
import { modeFromBackend } from '../../config/agents'
import type { AgentMode } from '../../types/agent'
import type { SessionListItem } from '../../types/api'
import {
  filterWorkspaceSessions,
  workspaceSectionForSession,
  type WorkspaceSection,
} from './workspaceNavigation'

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

const workspaceSection = ref<WorkspaceSection>('chats')
const searchOpen = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
let lastSyncedConversationId = ''

const workspaceItems: Array<{
  id: WorkspaceSection
  label: string
  icon: typeof MessageSquare
}> = [
  { id: 'chats', label: 'Chats', icon: MessageSquare },
  { id: 'research', label: 'Research', icon: Telescope },
  { id: 'presentations', label: 'Presentations', icon: Presentation },
]

const sectionLabels: Record<WorkspaceSection, string> = {
  chats: 'chat',
  research: 'research',
  presentations: 'presentation',
}

const filteredSessions = computed(() =>
  filterWorkspaceSessions(props.sessions, workspaceSection.value, searchQuery.value),
)

const groups = computed<SessionGroup[]>(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const buckets = new Map<string, SessionListItem[]>()

  for (const item of filteredSessions.value) {
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

const sessionIcons: Record<AgentMode, typeof MessageSquare> = {
  chat: MessageSquare,
  research: Telescope,
  file: FileText,
  skills: Bot,
  ppt: Presentation,
}

function title(item: SessionListItem): string {
  return item.question?.trim() || 'Untitled conversation'
}

function sessionIcon(item: SessionListItem) {
  return sessionIcons[modeFromBackend(item.agentType)]
}

function startNewChat() {
  workspaceSection.value = 'chats'
  searchQuery.value = ''
  emit('new')
}

function selectWorkspace(section: WorkspaceSection) {
  workspaceSection.value = section
  searchQuery.value = ''
}

async function openSearch() {
  if (props.collapsed && !props.mobile) emit('toggle')
  searchOpen.value = true
  await nextTick()
  searchInput.value?.focus()
}

function closeSearch() {
  searchQuery.value = ''
  searchOpen.value = false
}

watch(
  () => [props.currentId, props.sessions] as const,
  ([currentId, sessions]) => {
    if (!currentId || currentId === lastSyncedConversationId) return
    const currentSession = sessions.find((session) => session.conversationId === currentId)
    if (!currentSession) return
    workspaceSection.value = workspaceSectionForSession(currentSession)
    lastSyncedConversationId = currentId
  },
  { immediate: true },
)
</script>

<template>
  <aside
    class="flex h-full shrink-0 flex-col border-r border-[var(--line)] bg-[var(--surface)] transition-[width]"
    :class="mobile ? 'w-[min(88vw,292px)]' : collapsed ? 'w-16' : 'w-[236px]'"
    aria-label="DeepDesk workspace sidebar"
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

    <div class="space-y-0.5 px-2 pb-2">
      <button
        type="button"
        class="relative flex h-12 w-full items-center gap-2 rounded-lg px-2.5 text-base font-medium text-[var(--ink)] hover:bg-[var(--surface-muted)] md:h-9 md:text-sm"
        :class="collapsed && !mobile ? 'justify-center px-0' : ''"
        @click="startNewChat"
      >
        <PenLine class="size-4 shrink-0" aria-hidden="true" />
        <span v-if="!collapsed || mobile">New chat</span>
        <span v-if="collapsed && !mobile" class="sr-only">New chat</span>
      </button>

      <button
        v-if="!searchOpen || (collapsed && !mobile)"
        type="button"
        class="relative flex h-12 w-full items-center gap-2 rounded-lg px-2.5 text-base text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] md:h-9 md:text-sm"
        :class="collapsed && !mobile ? 'justify-center px-0' : ''"
        @click="openSearch"
      >
        <Search class="size-4 shrink-0" aria-hidden="true" />
        <span v-if="!collapsed || mobile">Search</span>
        <span v-if="collapsed && !mobile" class="sr-only">Search</span>
      </button>

      <div
        v-else
        class="flex h-12 items-center gap-1 rounded-lg bg-[var(--surface-muted)] px-2 md:h-9"
      >
        <Search class="size-4 shrink-0 text-[var(--ink-faint)]" aria-hidden="true" />
        <input
          ref="searchInput"
          v-model="searchQuery"
          type="search"
          class="min-w-0 flex-1 bg-transparent text-base text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)] md:text-sm"
          placeholder="Search recent"
          aria-label="Search recent conversations"
          @keydown.esc="closeSearch"
        />
        <button
          type="button"
          class="relative inline-flex size-8 shrink-0 items-center justify-center rounded-md text-[var(--ink-faint)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]"
          aria-label="Close search"
          @click="closeSearch"
        >
          <X class="size-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>

    <nav class="px-2" aria-label="Workspace">
      <div
        v-if="!collapsed || mobile"
        class="mb-1 px-2 pt-2 text-[0.65rem] font-semibold tracking-[0.12em] text-[var(--ink-faint)]"
      >
        WORKSPACE
      </div>
      <div class="space-y-0.5">
        <button
          v-for="item in workspaceItems"
          :key="item.id"
          type="button"
          class="relative flex h-12 w-full items-center gap-2 rounded-lg px-2.5 text-left text-base text-[var(--ink-secondary)] transition-colors hover:bg-[var(--surface-muted)] hover:text-[var(--ink)] md:h-9 md:text-sm"
          :class="[
            collapsed && !mobile ? 'justify-center px-0' : '',
            workspaceSection === item.id ? 'bg-[var(--accent-soft)] text-[var(--ink)]' : '',
          ]"
          :aria-pressed="workspaceSection === item.id"
          :aria-label="collapsed && !mobile ? item.label : undefined"
          @click="selectWorkspace(item.id)"
        >
          <component
            :is="item.icon"
            class="size-4 shrink-0"
            :class="workspaceSection === item.id ? 'text-[var(--accent)]' : 'text-[var(--ink-faint)]'"
            aria-hidden="true"
          />
          <span v-if="!collapsed || mobile" class="truncate">{{ item.label }}</span>
        </button>
      </div>
    </nav>

    <div
      v-if="!collapsed || mobile"
      class="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-4"
      :aria-busy="loading ? 'true' : undefined"
    >
      <div class="mb-1 flex items-center justify-between px-2">
        <div class="text-[0.65rem] font-semibold tracking-[0.12em] text-[var(--ink-faint)]">RECENT</div>
        <div
          v-if="searchQuery"
          class="max-w-[8rem] truncate text-[0.6875rem] text-[var(--ink-faint)]"
          :title="searchQuery"
        >
          “{{ searchQuery }}”
        </div>
      </div>
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
      <div
        v-else-if="!filteredSessions.length"
        class="px-2 py-3 text-xs leading-5 text-[var(--ink-faint)]"
      >
        <template v-if="searchQuery">No matching {{ sectionLabels[workspaceSection] }} conversations.</template>
        <template v-else>No recent {{ sectionLabels[workspaceSection] }} conversations.</template>
      </div>
      <template v-for="group in groups" v-else :key="group.label">
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
              <component
                :is="sessionIcon(session)"
                class="size-3.5 shrink-0 text-[var(--ink-faint)]"
                aria-hidden="true"
              />
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
    <div v-else class="min-h-0 flex-1" />

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
