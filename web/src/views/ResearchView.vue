<script setup lang="ts">
import { ArrowRight, Clock3, Menu, Plus, Search, Telescope } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import SidebarNav from '../components/layout/SidebarNav.vue'
import SettingsDialog from '../components/layout/SettingsDialog.vue'
import type { WorkspaceSection } from '../components/layout/workspaceNavigation'
import {
  researchHistoryItems,
  researchHistoryStatus,
  researchHistoryTitle,
} from '../components/research/researchHistory'
import { useConversationStore } from '../stores/conversation'
import { useSessionStore } from '../stores/session'
import { useSettingsStore } from '../stores/settings'
import type { SessionListItem } from '../types/api'

const router = useRouter()
const conversation = useConversationStore()
const sessions = useSessionStore()
const settings = useSettingsStore()
const { sessions: sessionItems, loading, error } = storeToRefs(sessions)

const searchQuery = ref('')
const settingsOpen = ref(false)
const settingsOpenedFromMobile = ref(false)
const mobileSidebarDialog = ref<HTMLDialogElement | null>(null)
const mobileSidebarTrigger = ref<HTMLButtonElement | null>(null)

const researchItems = computed(() => researchHistoryItems(sessionItems.value, searchQuery.value))

function formatTime(session: SessionListItem): string {
  const raw = session.updateTime || session.createTime
  if (!raw) return 'Time unavailable'
  const parsed = new Date(raw)
  if (Number.isNaN(parsed.getTime())) return 'Time unavailable'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(parsed)
}

async function startNewChat() {
  conversation.create('chat')
  settings.setMobileSidebar(false)
  await router.push('/')
}

async function startResearch() {
  conversation.create('research')
  settings.setMobileSidebar(false)
  await router.push('/')
}

async function openResearch(conversationId: string) {
  settings.setMobileSidebar(false)
  await router.push(`/c/${encodeURIComponent(conversationId)}`)
}

async function removeSession(conversationId: string) {
  const item = sessionItems.value.find((session) => session.conversationId === conversationId)
  const label = researchHistoryTitle(item || { conversationId })
  if (!window.confirm(`Delete “${label}”? This cannot be undone.`)) return
  await sessions.remove(conversationId)
}

async function openWorkspace(section: WorkspaceSection) {
  settings.setMobileSidebar(false)
  if (section === 'chats') await startNewChat()
}

function openSettings(fromMobile = false) {
  settingsOpenedFromMobile.value = fromMobile
  settingsOpen.value = true
  if (fromMobile) settings.setMobileSidebar(false)
}

async function closeSettings() {
  settingsOpen.value = false
  if (!settingsOpenedFromMobile.value) return
  settingsOpenedFromMobile.value = false
  await nextTick()
  mobileSidebarTrigger.value?.focus()
}

async function syncMobileSidebar(open: boolean) {
  if (open) {
    await nextTick()
    const dialog = mobileSidebarDialog.value
    if (dialog && !dialog.open) dialog.showModal()
    await nextTick()
    dialog?.querySelector<HTMLButtonElement>('[aria-label="Close sidebar"]')?.focus()
    return
  }

  const dialog = mobileSidebarDialog.value
  if (dialog?.open) dialog.close()
  await nextTick()
  if (!document.querySelector('dialog[open]')) mobileSidebarTrigger.value?.focus()
}

function closeMobileSidebarFromBackdrop(event: MouseEvent) {
  if (event.target === event.currentTarget) settings.setMobileSidebar(false)
}

watch(() => settings.mobileSidebarOpen, (open) => void syncMobileSidebar(open))
onMounted(() => void sessions.load())
</script>

<template>
  <div class="flex h-[100dvh] w-full overflow-hidden bg-[var(--canvas)]">
    <div class="hidden h-full md:block">
      <SidebarNav
        :sessions="sessionItems"
        active-workspace="research"
        :collapsed="settings.sidebarCollapsed"
        :loading="loading"
        :error="error"
        @new="startNewChat"
        @select="openResearch"
        @delete="removeSession"
        @toggle="settings.toggleSidebar()"
        @settings="openSettings()"
        @retry="sessions.load"
        @workspace="openWorkspace"
      />
    </div>

    <Teleport to="body">
      <dialog
        v-if="settings.mobileSidebarOpen"
        ref="mobileSidebarDialog"
        class="fixed inset-0 m-0 h-[100dvh] max-h-none w-full max-w-none overflow-hidden border-0 bg-transparent p-0 md:hidden backdrop:bg-black/25 dark:backdrop:bg-black/55"
        aria-label="Mobile navigation"
        @cancel.prevent="settings.setMobileSidebar(false)"
        @click="closeMobileSidebarFromBackdrop"
      >
        <div class="relative h-full w-fit shadow-[var(--shadow-float)]" @click.stop>
          <SidebarNav
            mobile
            :sessions="sessionItems"
            active-workspace="research"
            :loading="loading"
            :error="error"
            @new="startNewChat"
            @select="openResearch"
            @delete="removeSession"
            @settings="openSettings(true)"
            @close="settings.setMobileSidebar(false)"
            @retry="sessions.load"
            @workspace="openWorkspace"
          />
        </div>
      </dialog>
    </Teleport>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-14 shrink-0 items-center border-b border-[var(--line)] bg-[var(--canvas)] px-3 md:hidden">
        <button
          ref="mobileSidebarTrigger"
          type="button"
          class="relative inline-flex size-12 items-center justify-center rounded-lg text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]"
          aria-label="Open sidebar"
          @click="settings.setMobileSidebar(true)"
        >
          <Menu class="size-4" aria-hidden="true" />
        </button>
        <div class="ml-2 min-w-0 flex-1 truncate text-sm font-medium text-[var(--ink)]">DeepDesk</div>
        <div class="text-xs text-[var(--ink-faint)]">Research</div>
      </header>

      <main class="min-h-0 flex-1 overflow-y-auto">
        <div class="mx-auto w-full max-w-[1040px] px-4 pb-14 pt-8 sm:px-8 sm:pt-12">
          <div class="flex flex-col gap-5 border-b border-[var(--line)] pb-7 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div class="mb-2 flex items-center gap-2 text-sm font-medium text-[var(--accent)]">
                <Telescope class="size-4" aria-hidden="true" />
                Deep Research
              </div>
              <h1 class="font-[var(--font-display)] text-3xl font-semibold tracking-[-0.035em] text-[var(--ink)]">
                Research history
              </h1>
              <p class="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-faint)]">
                Reopen saved research conversations, final reports, and their cited sources.
              </p>
            </div>
            <button
              type="button"
              class="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[var(--ink)] px-4 text-sm font-medium text-[var(--surface)] hover:opacity-90"
              @click="startResearch"
            >
              <Plus class="size-4" aria-hidden="true" />
              New research
            </button>
          </div>

          <div class="mt-6 flex items-center gap-3">
            <label class="relative block w-full max-w-md">
              <span class="sr-only">Search research history</span>
              <Search
                class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--ink-faint)]"
                aria-hidden="true"
              />
              <input
                v-model="searchQuery"
                type="search"
                class="h-11 w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] pl-9 pr-3 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)] focus:border-[var(--line-strong)]"
                placeholder="Search research"
                aria-label="Search research history"
              />
            </label>
            <div class="shrink-0 text-xs text-[var(--ink-faint)]">
              {{ researchItems.length }} {{ researchItems.length === 1 ? 'research' : 'researches' }}
            </div>
          </div>

          <div v-if="loading && !sessionItems.length" class="mt-8 space-y-3" aria-label="Loading research history">
            <div
              v-for="index in 4"
              :key="index"
              class="h-24 animate-pulse rounded-xl border border-[var(--line)] bg-[var(--surface)]"
              aria-hidden="true"
            />
          </div>

          <div
            v-else-if="error && !sessionItems.length"
            class="mt-8 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-5 py-6"
          >
            <div class="text-sm font-medium text-[var(--ink)]">Research history is unavailable.</div>
            <p class="mt-1 text-sm text-[var(--ink-faint)]">{{ error }}</p>
            <button
              type="button"
              class="mt-4 min-h-10 rounded-lg border border-[var(--line-strong)] px-3 text-sm font-medium text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]"
              @click="sessions.load"
            >
              Try again
            </button>
          </div>

          <div
            v-else-if="!researchItems.length"
            class="mt-8 flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-[var(--line-strong)] px-6 py-12 text-center"
          >
            <Telescope class="size-7 text-[var(--ink-faint)]" aria-hidden="true" />
            <h2 class="mt-4 text-base font-medium text-[var(--ink)]">
              {{ searchQuery ? 'No matching research' : 'No research history yet' }}
            </h2>
            <p class="mt-1 max-w-md text-sm leading-6 text-[var(--ink-faint)]">
              {{
                searchQuery
                  ? 'Try a different topic or keyword.'
                  : 'Start a Deep Research conversation and completed reports will appear here.'
              }}
            </p>
            <button
              v-if="!searchQuery"
              type="button"
              class="mt-5 inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--line-strong)] px-3 text-sm font-medium text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]"
              @click="startResearch"
            >
              <Plus class="size-4" aria-hidden="true" />
              Start research
            </button>
          </div>

          <div v-else class="mt-8 divide-y divide-[var(--line)] border-y border-[var(--line)]">
            <article
              v-for="item in researchItems"
              :key="item.conversationId"
              class="group py-1"
            >
              <button
                type="button"
                class="flex min-h-24 w-full items-center gap-4 rounded-lg px-3 py-4 text-left transition-colors hover:bg-[var(--surface-muted)] sm:px-4"
                :aria-label="`Open research: ${researchHistoryTitle(item)}`"
                @click="openResearch(item.conversationId)"
              >
                <div class="hidden size-10 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)] sm:flex">
                  <Telescope class="size-4" aria-hidden="true" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <h2 class="truncate text-sm font-medium text-[var(--ink)]">
                      {{ researchHistoryTitle(item) }}
                    </h2>
                    <span
                      class="rounded-full px-2 py-0.5 text-[0.6875rem] font-medium"
                      :class="
                        researchHistoryStatus(item) === 'Complete'
                          ? 'bg-[var(--accent-soft)] text-[var(--accent)]'
                          : 'bg-[var(--surface-hover)] text-[var(--ink-faint)]'
                      "
                    >
                      {{ researchHistoryStatus(item) }}
                    </span>
                  </div>
                  <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--ink-faint)]">
                    <span class="inline-flex items-center gap-1.5">
                      <Clock3 class="size-3.5" aria-hidden="true" />
                      {{ formatTime(item) }}
                    </span>
                    <span v-if="item.messageCount">{{ item.messageCount }} turns</span>
                  </div>
                </div>
                <ArrowRight
                  class="size-4 shrink-0 text-[var(--ink-faint)] transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--ink-secondary)]"
                  aria-hidden="true"
                />
              </button>
            </article>
          </div>
        </div>
      </main>
    </div>

    <SettingsDialog :open="settingsOpen" @close="closeSettings" />
  </div>
</template>
