import { ref } from 'vue'
import { openAgentStream, stopAgent, type StreamRequest } from '../api/agent'
import { parseAgentEventStream } from '../stream/parser'
import type { AgentEvent } from '../types/sse'

export function useAgentStream() {
  const active = ref(false)
  let controller: AbortController | null = null
  let activeConversationId = ''

  async function run(
    request: Omit<StreamRequest, 'signal'>,
    onEvent: (event: AgentEvent) => void | Promise<void>,
  ): Promise<void> {
    if (active.value) throw new Error('Another response is already streaming.')
    controller = new AbortController()
    activeConversationId = request.conversationId
    active.value = true
    try {
      const response = await openAgentStream({ ...request, signal: controller.signal })
      if (!response.body) throw new Error('The browser did not receive a readable response stream.')
      await parseAgentEventStream(response.body, onEvent)
    } finally {
      active.value = false
      controller = null
      activeConversationId = ''
    }
  }

  async function stop(): Promise<void> {
    if (!active.value || !activeConversationId) return
    try {
      await stopAgent(activeConversationId)
    } finally {
      controller?.abort()
      active.value = false
    }
  }

  return { active, run, stop }
}
