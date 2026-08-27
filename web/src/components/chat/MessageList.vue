<script setup lang="ts">
import type { ConversationMessage } from '../../types/agent'
import MessageItem from './MessageItem.vue'

defineProps<{
  messages: ConversationMessage[]
  busy?: boolean
}>()

const emit = defineEmits<{
  recommend: [question: string]
  retry: [messageId: string]
  resend: [content: string]
}>()
</script>

<template>
  <div>
    <MessageItem
      v-for="message in messages"
      :key="message.id"
      :message="message"
      :busy="busy"
      @recommend="emit('recommend', $event)"
      @retry="emit('retry', $event)"
      @resend="emit('resend', $event)"
    />
  </div>
</template>
