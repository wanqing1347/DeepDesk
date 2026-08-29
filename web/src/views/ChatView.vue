<script setup lang="ts">
import { ArrowDown, Menu } from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getFileInfo, uploadFile } from '../api/file'
import { getSession } from '../api/session'
import ComposerBar from '../components/composer/ComposerBar.vue'
import ComposerErrorNotice from '../components/composer/ComposerErrorNotice.vue'
import AgentEmptyState from '../components/chat/AgentEmptyState.vue'
import MessageList from '../components/chat/MessageList.vue'
import SettingsDialog from '../components/layout/SettingsDialog.vue'
import SidebarNav from '../components/layout/SidebarNav.vue'
import { AGENT_BY_ID } from '../config/agents'
import { useAgentStream } from '../composables/useAgentStream'
import { useConversationStore } from '../stores/conversation'
import { useSessionStore } from '../stores/session'
import { useSettingsStore } from '../stores/settings'
import type { AgentMode, AssistantMessage, StreamError } from '../types/agent'
import type { FileInfo } from '../types/api'

const route = useRoute()
const router = useRouter()
const conversation = useConversationStore()
const sessions = useSessionStore()
const settings = useSettingsStore()
const stream = useAgentStream()
const { current, isStreaming } = storeToRefs(conversation)
const { sessions: sessionItems, loading: sessionsLoading, error: sessionsError } = storeToRefs(sessions)

const draft = ref('')
const settingsOpen = ref(false)
const settingsOpenedFromMobile = ref(false)
const loadingConversation = ref(false)
const composerError = ref<StreamError | null>(null)
const activeAssistantId = ref('')
const scrollViewport = ref<HTMLElement | null>(null)
const mobileSidebarDialog = ref<HTMLDialogElement | null>(null)
const mobileSidebarTrigger = ref<HTMLButtonElement | null>(null)
const followLatest = ref(true)
const hasNewContentBelow = ref(false)
let abortUpload: (() => void) | null = null
let retryUploadFile: File | null = null
let routeRequest = 0

const messages = computed(() => current.value?.messages || [])
const isEmpty = computed(() => messages.value.length === 0)
const currentMode = computed(() => current.value?.mode || 'chat')
const currentId = computed(() => current.value?.id || '')
const messageSignature = computed(() =>
  messages.value
    .map((message) =>
      message.role === 'assistant'
        ? `${message.id}:${message.content.length}:${message.thinking.length}:${message.tools.length}:${message.errors.length}:${message.state}`
        : `${message.id}:${message.content.length}`,
    )
    .join('|'),
)

function uiError(error: unknown, fallback = 'Something went wrong.'): StreamError {
  if (error instanceof ApiError) {
    return {
      code: error.code !== undefined ? String(error.code) : error.status ? `HTTP ${error.status}` : undefined,
      message: error.message || fallback,
      detail: error.detail,
    }
  }
  if (error instanceof Error) return { message: error.message || fallback }
  if (typeof error === 'string' && error.trim()) return { message: error.trim() }
  return { message: fallback }
}

function showComposerError(error: unknown, fallback?: string) {
  composerError.value = uiError(error, fallback)
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

function resetScrollFollow() {
  followLatest.value = true
  hasNewContentBelow.value = false
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

function isNearBottom(viewport: HTMLElement): boolean {
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 96
}

function handleConversationScroll() {
  const viewport = scrollViewport.value
  if (!viewport) return
  const nearBottom = isNearBottom(viewport)
  followLatest.value = nearBottom
  if (nearBottom) hasNewContentBelow.value = false
}

async function scrollToLatest() {
  await nextTick()
  const viewport = scrollViewport.value
  if (!viewport) return
  viewport.scrollTop = viewport.scrollHeight
  resetScrollFollow()
}

async function hydrateAttachment(fileId: string) {
  try {
    const info = await getFileInfo(fileId)
    const metadata = {
      name: info.fileName,
      size: info.fileSize ?? undefined,
      type: info.fileType ?? undefined,
    }
    conversation.hydrateFileMetadata(fileId, metadata)
    if (current.value?.attachment?.fileId === fileId) {
      conversation.patchAttachment({
        ...metadata,
        status: info.status === 'SUCCESS' ? 'ready' : 'error',
        progress: 100,
        error: info.status === 'SUCCESS' ? undefined : `File status: ${info.status}`,
        retryable: false,
      })
    }
  } catch {
    // The persisted conversation remains readable even when its file service is unavailable.
  }
}

async function loadRouteConversation() {
  const request = ++routeRequest
  composerError.value = null
  resetScrollFollow()
  const routeId = typeof route.params.conversationId === 'string' ? route.params.conversationId : ''

  if (!routeId) {
    if (!current.value || current.value.messages.length > 0) conversation.create('chat')
    return
  }
  if (current.value?.id === routeId && !conversation.loadError) return

  loadingConversation.value = true
  try {
    const detail = await getSession(routeId)
    if (request !== routeRequest) return
    conversation.load(detail)
    const fileIds = new Set(
      [detail.fileid, ...detail.messages.map((message) => message.fileid)].filter(
        (fileId): fileId is string => Boolean(fileId),
      ),
    )
    for (const fileId of fileIds) void hydrateAttachment(fileId)
  } catch (error) {
    if (request !== routeRequest) return
    const failure = uiError(error, 'This conversation could not be loaded from history.')
    conversation.create('chat', routeId)
    conversation.loadError = failure.message
    composerError.value = failure
  } finally {
    if (request === routeRequest) loadingConversation.value = false
  }
}

async function newChat() {
  if (isStreaming.value) await stopGeneration()
  draft.value = ''
  composerError.value = null
  retryUploadFile = null
  resetScrollFollow()
  conversation.create('chat')
  settings.setMobileSidebar(false)
  if (route.path !== '/') await router.push('/')
}

async function selectSession(id: string) {
  if (id === currentId.value) {
    settings.setMobileSidebar(false)
    return
  }
  if (isStreaming.value) await stopGeneration()
  settings.setMobileSidebar(false)
  await router.push(`/c/${encodeURIComponent(id)}`)
}

async function removeSession(id: string) {
  const item = sessionItems.value.find((session) => session.conversationId === id)
  const label = item?.question?.trim() || 'this conversation'
  if (!window.confirm(`Delete “${label}”? This cannot be undone.`)) return
  try {
    await sessions.remove(id)
    if (id === currentId.value) await newChat()
  } catch (error) {
    showComposerError(error, 'Could not delete this conversation.')
  }
}

async function changeMode(mode: AgentMode): Promise<boolean> {
  composerError.value = null
  if (isStreaming.value || loadingConversation.value) return false
  if (mode === currentMode.value) return true

  const hasMessages = Boolean(current.value?.messages.length)
  if (!hasMessages && current.value?.attachment && mode !== 'file' && mode !== 'skills') {
    showComposerError('Remove the attached file before switching to this mode.')
    return false
  }

  const { created } = conversation.switchMode(mode)
  if (created) {
    retryUploadFile = null
    resetScrollFollow()
    if (route.path !== '/') await router.push('/')
  }
  return true
}

async function attachFile(file: File) {
  composerError.value = null
  if (isStreaming.value) return
  if (current.value?.attachment?.status === 'uploading' || current.value?.attachment?.status === 'processing') {
    showComposerError('Wait for the current file to finish before replacing it.')
    return
  }
  if (current.value?.attachment) conversation.setAttachment(null)

  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  const allowed = new Set(['pdf', 'docx', 'txt', 'png', 'jpg', 'jpeg'])
  if (!allowed.has(extension)) {
    const message = 'Unsupported file type. Use PDF, DOCX, TXT, PNG, JPG, or JPEG.'
    conversation.setAttachment({
      name: file.name,
      size: file.size,
      type: file.type,
      status: 'error',
      progress: 0,
      error: message,
      retryable: false,
    })
    composerError.value = { code: 'UNSUPPORTED_FILE_TYPE', message }
    return
  }
  if (file.size > 50 * 1024 * 1024) {
    const message = 'Files must be 50 MB or smaller.'
    conversation.setAttachment({
      name: file.name,
      size: file.size,
      type: file.type,
      status: 'error',
      progress: 0,
      error: message,
      retryable: false,
    })
    composerError.value = { code: 'FILE_TOO_LARGE', message }
    return
  }

  retryUploadFile = null
  if (currentMode.value !== 'file' && currentMode.value !== 'skills') {
    const changed = await changeMode('file')
    if (!changed) return
  }
  conversation.setAttachment({
    name: file.name,
    size: file.size,
    type: file.type,
    status: 'uploading',
    progress: 0,
    retryable: false,
  })

  const handle = uploadFile(
    file,
    (progress) => conversation.patchAttachment({ progress }),
    () => {
      if (current.value?.attachment?.status === 'uploading') {
        conversation.patchAttachment({ status: 'processing', progress: 100 })
      }
    },
  )
  abortUpload = handle.abort
  try {
    const info = await handle.promise
    conversation.patchAttachment({
      fileId: info.fileId,
      name: info.fileName,
      size: info.fileSize ?? file.size,
      type: info.fileType ?? file.type,
      status: 'ready',
      progress: 100,
      error: undefined,
      retryable: false,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      conversation.setAttachment(null)
    } else {
      const failure = uiError(error, 'File upload failed.')
      retryUploadFile = file
      conversation.patchAttachment({ status: 'error', error: failure.message, retryable: true })
      composerError.value = failure
    }
  } finally {
    abortUpload = null
  }
}

async function retryAttachmentUpload() {
  const file = retryUploadFile
  const attachment = current.value?.attachment
  if (!file || attachment?.status !== 'error' || !attachment.retryable || isStreaming.value) return
  conversation.setAttachment(null)
  await attachFile(file)
}

function selectExistingFile(info: FileInfo) {
  composerError.value = null
  if (isStreaming.value || loadingConversation.value) return
  if (currentMode.value !== 'file' && currentMode.value !== 'skills') return
  if (current.value?.attachment?.status === 'uploading' || current.value?.attachment?.status === 'processing') {
    showComposerError('Wait for the current file to finish before replacing it.')
    return
  }
  if (info.status.trim().toUpperCase() !== 'SUCCESS') {
    showComposerError('This file is not ready to use yet.')
    return
  }

  retryUploadFile = null
  conversation.setAttachment({
    fileId: info.fileId,
    name: info.fileName,
    size: info.fileSize ?? undefined,
    type: info.fileType ?? undefined,
    status: 'ready',
    progress: 100,
    retryable: false,
  })
}

async function removeAttachment() {
  composerError.value = null
  const attachment = current.value?.attachment
  if (!attachment) return
  if (attachment.status === 'uploading') {
    retryUploadFile = null
    abortUpload?.()
    conversation.setAttachment(null)
    return
  }
  if (attachment.status === 'processing') {
    showComposerError('The file is already being processed. Wait for processing to finish before removing it.')
    return
  }

  retryUploadFile = null
  conversation.setAttachment(null)
}

async function runAssistant(
  assistant: AssistantMessage,
  request: { mode: AgentMode; query: string; conversationId: string; fileId?: string },
) {
  activeAssistantId.value = assistant.id
  let completed = false
  try {
    await stream.run(request, (event) => {
      conversation.applyEvent(assistant.id, event)
      if (event.type === 'complete') completed = true
    })
    if (!completed && assistant.state === 'streaming') {
      conversation.fail(assistant.id, new Error('The connection closed before the agent completed its response.'))
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      conversation.markStopped(assistant.id)
    } else if (assistant.state === 'streaming') {
      conversation.fail(assistant.id, error)
    }
  } finally {
    if (activeAssistantId.value === assistant.id) activeAssistantId.value = ''
    if (completed) void sessions.load()
  }
}

async function sendMessage() {
  if (!current.value || isStreaming.value) return
  composerError.value = null
  const mode = current.value.mode
  const attachment = current.value.attachment

  if (mode === 'file' && attachment?.status !== 'ready') {
    showComposerError('Upload a file before sending a File request.')
    return
  }

  const query = draft.value.trim() || (mode === 'file' ? 'Please analyze this file.' : '')
  if (!query) return

  resetScrollFollow()
  const conversationId = current.value.id
  const { assistant } = conversation.addTurn(query)
  draft.value = ''

  if (route.params.conversationId !== conversationId) {
    await router.replace(`/c/${encodeURIComponent(conversationId)}`)
  }

  await runAssistant(assistant, {
    mode,
    query,
    conversationId,
    fileId: mode === 'file' || mode === 'skills' ? attachment?.fileId : undefined,
  })
}

async function retryResponse(messageId: string) {
  if (isStreaming.value || !current.value) return
  composerError.value = null
  resetScrollFollow()
  const retry = conversation.prepareRetry(messageId)
  if (!retry) {
    showComposerError('This response can no longer be retried.')
    return
  }
  if (retry.mode === 'file' && !retry.fileId) {
    const failure = new Error('The original file is no longer attached to this request.')
    conversation.fail(retry.assistant.id, failure)
    showComposerError(failure)
    return
  }

  // The backend has no message-overwrite endpoint. Reuse the existing assistant bubble
  // so the UI does not invent a duplicate user message while the server performs a new attempt.
  await runAssistant(retry.assistant, {
    mode: retry.mode,
    query: retry.query,
    conversationId: current.value.id,
    fileId: retry.mode === 'file' || retry.mode === 'skills' ? retry.fileId : undefined,
  })
}

async function resendUserMessage(content: string) {
  if (isStreaming.value) return
  draft.value = content
  await sendMessage()
}

async function stopGeneration() {
  const messageId = activeAssistantId.value
  try {
    await stream.stop()
  } catch (error) {
    const failure = uiError(error, 'Stop request failed.')
    composerError.value = { ...failure, message: `Stop request failed: ${failure.message}` }
  } finally {
    conversation.markStopped(messageId || undefined)
  }
}

function sendRecommendation(question: string) {
  if (isStreaming.value) return
  draft.value = question
  void sendMessage()
}

watch(() => settings.mobileSidebarOpen, (open) => void syncMobileSidebar(open))
watch(messageSignature, async () => {
  if (!messages.value.length) return
  await nextTick()
  const viewport = scrollViewport.value
  if (!viewport) return
  if (followLatest.value) {
    viewport.scrollTop = viewport.scrollHeight
    hasNewContentBelow.value = false
  } else {
    hasNewContentBelow.value = true
  }
})
watch(() => route.params.conversationId, loadRouteConversation, { immediate: true })
onMounted(() => void sessions.load())
</script>

<template>
  <div class="flex h-[100dvh] w-full overflow-hidden bg-[var(--canvas)]">
    <div class="hidden h-full md:block">
      <SidebarNav
        :sessions="sessionItems"
        :current-id="currentId"
        :collapsed="settings.sidebarCollapsed"
        :loading="sessionsLoading"
        :error="sessionsError"
        @new="newChat"
        @select="selectSession"
        @delete="removeSession"
        @toggle="settings.toggleSidebar()"
        @settings="openSettings()"
        @retry="sessions.load"
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
            :current-id="currentId"
            :loading="sessionsLoading"
            :error="sessionsError"
            @new="newChat"
            @select="selectSession"
            @delete="removeSession"
            @settings="openSettings(true)"
            @close="settings.setMobileSidebar(false)"
            @retry="sessions.load"
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
        <div class="text-xs text-[var(--ink-faint)]">{{ AGENT_BY_ID[currentMode].label }}</div>
      </header>

      <main v-if="isEmpty && !loadingConversation" class="min-h-0 flex-1 overflow-y-auto">
        <div class="mx-auto flex min-h-full w-full max-w-[900px] flex-col items-center justify-center px-4 pb-[calc(3rem+env(safe-area-inset-bottom))] pt-6 sm:px-8 sm:pb-12 sm:pt-8">
          <AgentEmptyState :mode="currentMode" />

          <div v-if="composerError" class="mb-3 mt-4 w-full max-w-[800px] px-2">
            <ComposerErrorNotice
              :error="composerError"
              :action-label="conversation.loadError ? 'Retry history' : undefined"
              :action-disabled="loadingConversation"
              @action="loadRouteConversation"
            />
          </div>
          <ComposerBar
            v-model="draft"
            class="mt-4"
            :mode="currentMode"
            :attachment="current?.attachment || null"
            :streaming="isStreaming"
            @update:mode="changeMode"
            @send="sendMessage"
            @stop="stopGeneration"
            @file="attachFile"
            @select-file="selectExistingFile"
            @retry-file="retryAttachmentUpload"
            @remove-file="removeAttachment"
          />
        </div>
      </main>

      <div v-else class="flex min-h-0 flex-1 flex-col">
        <div class="relative min-h-0 flex-1">
          <div
            ref="scrollViewport"
            class="h-full overflow-y-auto px-4 sm:px-6"
            @scroll.passive="handleConversationScroll"
          >
            <div class="mx-auto w-full max-w-[800px] pb-7 pt-3 sm:pb-8 sm:pt-6">
              <div v-if="loadingConversation" class="py-16 text-center text-sm text-[var(--ink-faint)]">Loading conversation…</div>
              <MessageList
                v-else
                :messages="messages"
                :busy="isStreaming"
                @recommend="sendRecommendation"
                @retry="retryResponse"
                @resend="resendUserMessage"
              />
            </div>
          </div>

          <button
            v-if="hasNewContentBelow && !followLatest"
            type="button"
            class="absolute bottom-3 left-1/2 z-10 inline-flex min-h-12 -translate-x-1/2 items-center gap-2 rounded-full border border-[var(--line-strong)] bg-[var(--surface-raised)] px-3 text-base font-medium text-[var(--ink-secondary)] shadow-[var(--shadow-float)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)] sm:min-h-9 sm:text-sm"
            aria-label="Back to latest response"
            @click="scrollToLatest"
          >
            <ArrowDown class="size-4" aria-hidden="true" />
            Back to latest
          </button>
        </div>

        <div class="shrink-0 bg-[var(--canvas)] px-3 pb-[calc(12px+env(safe-area-inset-bottom))] pt-1.5 sm:px-6 sm:pb-4 sm:pt-2">
          <div v-if="composerError" class="mx-auto mb-2 w-full max-w-[800px] px-2">
            <ComposerErrorNotice
              :error="composerError"
              :action-label="conversation.loadError ? 'Retry history' : undefined"
              :action-disabled="loadingConversation"
              @action="loadRouteConversation"
            />
          </div>
          <ComposerBar
            v-model="draft"
            :mode="currentMode"
            :attachment="current?.attachment || null"
            :streaming="isStreaming"
            :disabled="loadingConversation"
            @update:mode="changeMode"
            @send="sendMessage"
            @stop="stopGeneration"
            @file="attachFile"
            @select-file="selectExistingFile"
            @retry-file="retryAttachmentUpload"
            @remove-file="removeAttachment"
          />
        </div>
      </div>
    </div>

    <SettingsDialog :open="settingsOpen" @close="closeSettings" />
  </div>
</template>
