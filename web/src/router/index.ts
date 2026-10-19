import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' }, // 对话优先：默认落地值班对话
    { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue'), meta: { title: '值班对话' } },
    { path: '/alerts', name: 'alerts', component: () => import('@/views/AlertsView.vue'), meta: { title: '告警工单' } },
    { path: '/production', name: 'production', component: () => import('@/views/ProductionView.vue'), meta: { title: '生产数据' } },
    { path: '/knowledge', name: 'knowledge', component: () => import('@/views/KnowledgeView.vue'), meta: { title: '知识运营' } },
    { path: '/graph', name: 'graph', component: () => import('@/views/GraphView.vue'), meta: { title: '知识图谱' } },
  ],
})

router.afterEach(to => { document.title = `${to.meta.title ?? ''} · 智慧井场值班工作台` })

export default router
