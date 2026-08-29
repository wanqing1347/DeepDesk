import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '../views/ChatView.vue'
import PresentationsView from '../views/PresentationsView.vue'
import ResearchView from '../views/ResearchView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'new-chat', component: ChatView },
    { path: '/research', name: 'research-history', component: ResearchView },
    { path: '/presentations', name: 'presentations', component: PresentationsView },
    { path: '/c/:conversationId', name: 'conversation', component: ChatView },
  ],
})
