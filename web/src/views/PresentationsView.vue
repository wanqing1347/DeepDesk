<script setup lang="ts">
import {
  Clock3,
  Download,
  ExternalLink,
  Menu,
  MessageSquareText,
  Plus,
  Presentation,
  Search,
  Trash2,
} from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { deletePresentation, listPresentations } from '../api/ppt'
import SidebarNav from '../components/layout/SidebarNav.vue'
import SettingsDialog from '../components/layout/SettingsDialog.vue'
import type { WorkspaceSection } from '../components/layout/workspaceNavigation'
import {
  presentationFileName,
  presentationLibraryItems,
  presentationStatusLabel,
  presentationStatusTone,
  presentationTitle,
} from '../components/ppt/presentationLibrary'
import { useConversationStore } from '../stores/conversation'
import { useSessionStore } from '../stores/session'
import { useSettingsStore } from '../stores/settings'
import type { PresentationInfo } from '../types/api'

const router = useRouter()
const conversation = useConversationStore()
const sessions = useSessionStore()
const settings = useSettingsStore()
const { sessions: sessionItems, loading: sessionsLoading, error: sessionsError } = storeToRefs(sessions)

const presentations = ref<PresentationInfo[]>([])
const loading = ref(false)
const error = ref('')
const deletingId = ref<number | null>(null)
const searchQuery = ref('')
const settingsOpen = ref(false)
const settingsOpenedFromMobile = ref(false)
const mobileSidebarDialog = ref<HTMLDialogElement | null>(null)
const mobileSidebarTrigger = ref<HTMLButtonElement | null>(null)

const presentationItems = computed(() => presentationLibraryItems(presentations.value, searchQuery.value))

async function loadPresentationLibrary() {
  loading.value = true
  error.value = ''
  try {
    const result = await listPresentations()
    presentations.value = result.presentations
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Unable to load presentations.'
  } finally {
    loading.value = false
  }
}

function formatTime(item: PresentationInfo): string {
  const raw = item.updateTime || item.createTime
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

function conversationLabel(item: PresentationInfo): string {
  if (!item.conversationId) return 'Conversation unavailable'
  const session = sessionItems.value.find((candidate) => candidate.conversationId === item.conversationId)
  return session?.question?.trim() || item.conversationId
}

function statusClass(item: PresentationInfo): string {
  const tone = presentationStatusTone(item.status)
  if (tone === 'ready') return 'bg-[var(--accent-soft)] text-[var(--accent)]'
  if (tone === 'failed') return 'bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] text-[var(--danger)]'
  return 'bg-[var(--surface-hover)] text-[var(--ink-secondary)]'
}

async function startNewChat() {
  conversation.create('chat')
  settings.setMobileSidebar(false)
  await router.push('/')
}

async function startPresentation() {
  conversation.create('ppt')
  settings.setMobileSidebar(false)
  await router.push('/')
}

async function openConversation(conversationId: string) {
  settings.setMobileSidebar(false)
  await router.push(`/c/${encodeURIComponent(conversationId)}`)
}

async function continueEditing(item: PresentationInfo) {
  if (!item.conversationId) return
  await openConversation(item.conversationId)
}

async function removePresentation(item: PresentationInfo) {
  const label = presentationTitle(item)
  if (!window.confirm(`Delete “${label}” from Presentations? The original conversation will remain.`)) return
  deletingId.value = item.id
  try {
    await deletePresentation(item.id)
    presentations.value = presentations.value.filter((candidate) => candidate.id !== item.id)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Unable to delete presentation.'
  } finally {
    deletingId.value = null
  }
}

async function removeSession(conversationId: string) {
  const session = sessionItems.value.find((candidate) => candidate.conversationId === conversationId)
  const label = session?.question?.trim() || 'this conversation'
  if (!window.confirm(`Delete “${label}”? This also removes its presentation records and cannot be undone.`)) return
  await sessions.remove(conversationId)
  await loadPresentationLibrary()
}

async function openWorkspace(section: WorkspaceSection) {
  settings.setMobileSidebar(false)
  if (section === 'chats') {
    await startNewChat()
    return
  }
  if (section === 'research') await router.push('/research')
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
onMounted(() => {
  void sessions.load()
  void loadPresentationLibrary()
})
</script>

<template>
  <div class="flex h-[100dvh] w-full overflow-hidden bg-[var(--canvas)]">
    <div class="hidden h-full md:block">
      <SidebarNav
        :sessions="sessionItems"
        active-workspace="presentations"
        :collapsed="settings.sidebarCollapsed"
        :loading="sessionsLoading"
        :error="sessionsError"
        @new="startNewChat"
        @select="openConversation"
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
            active-workspace="presentations"
            :loading="sessionsLoading"
            :error="sessionsError"
            @new="startNewChat"
            @select="openConversation"
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
        <div class="text-xs text-[var(--ink-faint)]">Presentations</div>
      </header>

      <main class="min-h-0 flex-1 overflow-y-auto">
        <div class="mx-auto w-full max-w-[1120px] px-4 pb-14 pt-8 sm:px-8 sm:pt-12">
          <div class="flex flex-col gap-5 border-b border-[var(--line)] pb-7 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div class="mb-2 flex items-center gap-2 text-sm font-medium text-[var(--accent)]">
                <Presentation class="size-4" aria-hidden="true" />
                PPT workspace
              </div>
              <h1 class="font-[var(--font-display)] text-2xl font-semibold tracking-[-0.035em] text-[var(--ink)]">
                Presentations
              </h1>
              <p class="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-faint)]">
                Reopen generated decks, download the latest file, or return to the original conversation to revise it.
              </p>
            </div>
            <button
              type="button"
              class="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[var(--ink)] px-4 text-sm font-medium text-[var(--surface)] hover:opacity-90"
              @click="startPresentation"
            >
              <Plus class="size-4" aria-hidden="true" />
              New presentation
            </button>
          </div>

          <div class="mt-6 flex items-center gap-3">
            <label class="relative block w-full max-w-md">
              <span class="sr-only">Search presentations</span>
              <Search
                class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--ink-faint)]"
                aria-hidden="true"
              />
              <input
                v-model="searchQuery"
                type="search"
                class="h-11 w-full rounded-lg border border-[var(--line)] bg-[var(--surface)] pl-9 pr-3 text-sm text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)] focus:border-[var(--line-strong)]"
                placeholder="Search presentations"
                aria-label="Search presentations"
              />
            </label>
            <div class="shrink-0 text-xs text-[var(--ink-faint)]">
              {{ presentationItems.length }} {{ presentationItems.length === 1 ? 'presentation' : 'presentations' }}
            </div>
          </div>

          <div v-if="loading && !presentations.length" class="mt-8 grid gap-4 lg:grid-cols-2" aria-label="Loading presentations">
            <div
              v-for="index in 4"
              :key="index"
              class="h-64 animate-pulse rounded-xl border border-[var(--line)] bg-[var(--surface)]"
              aria-hidden="true"
            />
          </div>

          <div
            v-else-if="error && !presentations.length"
            class="mt-8 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-5 py-6"
          >
            <div class="text-sm font-medium text-[var(--ink)]">Presentation library is unavailable.</div>
            <p class="mt-1 text-sm text-[var(--ink-faint)]">{{ error }}</p>
            <button
              type="button"
              class="mt-4 min-h-10 rounded-lg border border-[var(--line-strong)] px-3 text-sm font-medium text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]"
              @click="loadPresentationLibrary"
            >
              Try again
            </button>
          </div>

          <div
            v-else-if="!presentationItems.length"
            class="mt-8 flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-[var(--line-strong)] px-6 py-12 text-center"
          >
            <Presentation class="size-7 text-[var(--ink-faint)]" aria-hidden="true" />
            <h2 class="mt-4 text-base font-medium text-[var(--ink)]">
              {{ searchQuery ? 'No matching presentations' : 'No presentations yet' }}
            </h2>
            <p class="mt-1 max-w-md text-sm leading-6 text-[var(--ink-faint)]">
              {{
                searchQuery
                  ? 'Try a title, filename, conversation, or status.'
                  : 'Create a PPT conversation and generated presentation assets will appear here.'
              }}
            </p>
            <button
              v-if="!searchQuery"
              type="button"
              class="mt-5 inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--line-strong)] px-3 text-sm font-medium text-[var(--ink-secondary)] hover:bg-[var(--surface-muted)]"
              @click="startPresentation"
            >
              <Plus class="size-4" aria-hidden="true" />
              Create presentation
            </button>
          </div>

          <div v-else class="mt-8 grid gap-4 lg:grid-cols-2">
            <article
              v-for="item in presentationItems"
              :key="item.id"
              class="flex min-h-[17rem] flex-col rounded-xl border border-[var(--line)] bg-[var(--surface)] p-5 transition-colors hover:border-[var(--line-strong)]"
            >
              <div class="flex items-start gap-4">
                <div class="flex h-16 w-20 shrink-0 flex-col justify-between rounded-lg border border-[var(--line)] bg-[var(--canvas)] p-2.5">
                  <Presentation class="size-4 text-[var(--accent)]" aria-hidden="true" />
                  <span class="text-[0.625rem] font-semibold tracking-[0.12em] text-[var(--ink-faint)]">PPTX</span>
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-start justify-between gap-3">
                    <h2 class="line-clamp-2 text-sm font-medium leading-5 text-[var(--ink)]">
                      {{ presentationTitle(item) }}
                    </h2>
                    <span
                      class="shrink-0 rounded-full px-2 py-0.5 text-[0.6875rem] font-medium"
                      :class="statusClass(item)"
                    >
                      {{ presentationStatusLabel(item.status) }}
                    </span>
                  </div>
                  <div class="mt-2 flex items-center gap-1.5 text-xs text-[var(--ink-faint)]">
                    <Clock3 class="size-3.5 shrink-0" aria-hidden="true" />
                    <span>{{ formatTime(item) }}</span>
                  </div>
                </div>
              </div>

              <dl class="mt-5 space-y-3 border-t border-[var(--line)] pt-4 text-xs">
                <div class="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3">
                  <dt class="text-[var(--ink-faint)]">Conversation</dt>
                  <dd class="truncate text-[var(--ink-secondary)]" :title="conversationLabel(item)">
                    {{ conversationLabel(item) }}
                  </dd>
                </div>
                <div class="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3">
                  <dt class="text-[var(--ink-faint)]">File</dt>
                  <dd class="truncate text-[var(--ink-secondary)]" :title="presentationFileName(item)">
                    {{ presentationFileName(item) }}
                  </dd>
                </div>
                <div v-if="item.errorMsg" class="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3">
                  <dt class="text-[var(--ink-faint)]">Last error</dt>
                  <dd class="line-clamp-2 text-[var(--danger)]" :title="item.errorMsg">{{ item.errorMsg }}</dd>
                </div>
              </dl>

              <div class="mt-auto flex flex-wrap items-center gap-2 pt-5">
                <a
                  v-if="item.fileUrl"
                  :href="item.fileUrl"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex h-9 items-center gap-2 rounded-lg border border-[var(--line)] px-3 text-sm font-medium text-[var(--ink)] hover:bg-[var(--surface-muted)]"
                >
                  <ExternalLink class="size-4" aria-hidden="true" />
                  Open
                </a>
                <a
                  v-if="item.fileUrl"
                  :href="item.fileUrl"
                  :download="presentationFileName(item)"
                  class="inline-flex h-9 items-center gap-2 rounded-lg border border-[var(--line)] px-3 text-sm font-medium text-[var(--ink)] hover:bg-[var(--surface-muted)]"
                >
                  <Download class="size-4" aria-hidden="true" />
                  Download
                </a>
                <button
                  type="button"
                  class="inline-flex h-9 items-center gap-2 rounded-lg bg-[var(--ink)] px-3 text-sm font-medium text-[var(--surface)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                  :disabled="!item.conversationId"
                  @click="continueEditing(item)"
                >
                  <MessageSquareText class="size-4" aria-hidden="true" />
                  Continue editing
                </button>
                <button
                  type="button"
                  class="ml-auto inline-flex size-9 items-center justify-center rounded-lg text-[var(--ink-faint)] hover:bg-[var(--surface-muted)] hover:text-[var(--danger)] disabled:cursor-wait disabled:opacity-40"
                  :disabled="deletingId === item.id"
                  :aria-label="`Delete presentation: ${presentationTitle(item)}`"
                  @click="removePresentation(item)"
                >
                  <Trash2 class="size-4" aria-hidden="true" />
                </button>
              </div>
            </article>
          </div>

          <div
            v-if="error && presentations.length"
            class="mt-5 rounded-lg border border-[var(--line)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--danger)]"
          >
            {{ error }}
          </div>
        </div>
      </main>
    </div>

    <SettingsDialog :open="settingsOpen" @close="closeSettings" />
  </div>
</template>
