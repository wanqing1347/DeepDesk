import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'new-chat', component: ChatView },
    { path: '/c/:conversationId', name: 'conversation', component: ChatView },
  ],
})
