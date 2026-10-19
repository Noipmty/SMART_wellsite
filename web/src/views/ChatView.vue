<template>
  <div class="chat-view">
    <!-- ============ 中栏：对话流 + 输入区 ============ -->
    <section class="chat-main">
      <div ref="scrollRef" class="msg-scroll">
        <div class="msg-container">
          <!-- 空状态：欢迎语 + 快捷提问卡片 -->
          <div v-if="!messages.length" class="welcome">
            <div class="welcome-icon"><el-icon :size="40"><ChatDotRound /></el-icon></div>
            <h2>值班助手已就绪</h2>
            <p class="welcome-sub">井场 {{ app.onlineWells }} 口井在线 · {{ app.alertTotal }} 条未处理告警。可以直接提问，或从下面开始：</p>
            <div class="quick-grid">
              <div
                v-for="qp in QUICK_PROMPTS" :key="qp.title"
                class="quick-card panel-card clickable"
                @click="send(qp.q)"
              >
                <div class="quick-title">{{ qp.title }}</div>
                <div class="quick-desc">{{ qp.desc }}</div>
              </div>
            </div>
          </div>

          <!-- 消息流 -->
          <ChatMessage
            v-for="m in messages" :key="m.id"
            :msg="m" :active="activeMsg?.id === m.id"
            @send="send" @regenerate="regenerate" @select="m2 => activeMsg = m2"
          />
        </div>
      </div>

      <div class="input-area">
        <div class="input-container">
          <ChatInput :loading="loading" @send="send" @stop="stop" />
        </div>
      </div>
    </section>

    <!-- ============ 右栏：协同过程面板（可折叠） ============ -->
    <aside class="trace-panel" :class="{ collapsed: panelCollapsed }">
      <button class="collapse-toggle" :title="panelCollapsed ? '展开协同面板' : '收起协同面板'" @click="panelCollapsed = !panelCollapsed">
        <el-icon><DArrowLeft v-if="!panelCollapsed" /><DArrowRight v-else /></el-icon>
      </button>
      <AgentTimeline
        v-show="!panelCollapsed"
        :results="activeMsg?.resp?.results ?? []"
        :trace-id="activeMsg?.resp?.trace_id ?? ''"
        :running="loading"
      />
    </aside>
  </div>
</template>

<script setup lang="ts">
import { h, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import { ChatDotRound, DArrowLeft, DArrowRight } from '@element-plus/icons-vue'
import ChatMessage from '@/components/ChatMessage.vue'
import ChatInput from '@/components/ChatInput.vue'
import AgentTimeline from '@/components/AgentTimeline.vue'
import { chat, listAlerts } from '@/api'
import { QUICK_PROMPTS } from '@/api/mock/data'
import { useAppStore } from '@/stores/app'
import type { ChatMsg } from '@/types/chat'
import type { Level } from '@/api/types'

const router = useRouter()
const app = useAppStore()

const messages = ref<ChatMsg[]>([])
const activeMsg = ref<ChatMsg | null>(null)
const loading = ref(false)
// <1440px 时右栏默认折叠（响应式约束）
const panelCollapsed = ref(!window.matchMedia('(min-width: 1440px)').matches)
const scrollRef = ref<HTMLElement>()

const sessionId = `sess-${Math.random().toString(16).slice(2, 10)}`
let seq = 0
const nid = () => `m-${++seq}`

async function scrollBottom() {
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
}

/** 发送（用户输入 / 澄清选项 / 快捷卡片共用入口） */
async function send(text: string) {
  const t = text.trim()
  if (!t || loading.value) return

  messages.value.push({ id: nid(), role: 'user', content: t, ts: Date.now() })
  // 生成中占位消息
  const placeholder: ChatMsg = { id: nid(), role: 'assistant', content: '', loading: true, ts: Date.now() }
  messages.value.push(placeholder)
  activeMsg.value = null // 面板切到“编排中”占位
  loading.value = true
  scrollBottom()

  try {
    const resp = await chat(t, sessionId)
    Object.assign(placeholder, { loading: false, content: resp.reply, resp })
    activeMsg.value = placeholder // 协同面板默认跟随最新一条
    maybeNotifyAlert(resp.results)
  } catch {
    Object.assign(placeholder, { loading: false, content: '服务暂时不可用，请稍后重试。' })
  } finally {
    loading.value = false
    scrollBottom()
  }
}

/** 对话中若产生告警 → 等级色 toast + 去处置按钮 + 顶栏红点刷新 */
function maybeNotifyAlert(results: NonNullable<ChatMsg['resp']>['results']) {
  const hit = results.find(r => r.agent === 'alert_handler' && r.data?.level)
  if (!hit) return
  const level = hit.data.level as Level
  const typeMap: Record<Level, 'error' | 'warning' | 'primary' | 'info'> = { 紧急: 'error', 预警: 'warning', 提醒: 'primary', 提示: 'info' }
  ElNotification({
    type: typeMap[level],
    title: `${level}告警 · ${String(hit.data.alert_id ?? '')}`,
    message: h('div', { class: 'alert-toast' }, [
      h('div', null, hit.conclusion),
      h('a', {
        style: 'color: var(--accent-hover); cursor: pointer; font-size: 13px;',
        onClick: () => router.push('/alerts'),
      }, '去处置 →'),
    ]),
    duration: 8000,
  })
  app.refreshSummary()
}

/** 停止生成（mock 无法中断请求，仅终止占位状态） */
function stop() {
  const last = messages.value[messages.value.length - 1]
  if (last?.loading) Object.assign(last, { loading: false, stopped: true, content: '_已手动停止生成。_' })
  loading.value = false
}

/** 重新生成：重发最近一条用户消息 */
function regenerate() {
  if (loading.value) return
  const lastUser = [...messages.value].reverse().find(m => m.role === 'user')
  if (lastUser) send(lastUser.content)
}

// 顶栏数据兜底刷新一次（首次进入时红点可能为空）
app.refreshSummary()
// 预拉告警，保证空状态副标题数字准确
listAlerts({ status: 'active' })
</script>

<style scoped>
.chat-view { display: flex; height: 100%; min-height: 0; }

.chat-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }

.msg-scroll { flex: 1; overflow-y: auto; padding: 20px 24px; }
.msg-container { max-width: 760px; margin: 0 auto; }

/* 空状态 */
.welcome { text-align: center; padding: 48px 0 24px; }
.welcome-icon { color: var(--accent); margin-bottom: 12px; }
.welcome h2 { margin: 0 0 8px; font-size: 20px; }
.welcome-sub { color: var(--text-secondary); margin: 0 0 24px; }
.quick-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; text-align: left; }
.quick-card { padding: 14px 16px; }
.quick-card:hover { border-color: var(--accent); }
.quick-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.quick-desc { font-size: 12.5px; color: var(--text-secondary); }

.input-area { flex: none; padding: 12px 24px 16px; }
.input-container { max-width: 760px; margin: 0 auto; }

/* 右栏 */
.trace-panel {
  position: relative; flex: none; width: var(--panel-w);
  background: var(--bg-panel); border-left: 1px solid var(--border);
  transition: width .18s ease-out;
}
.trace-panel.collapsed { width: 36px; }
.collapse-toggle {
  position: absolute; top: 10px; left: 4px; z-index: 5;
  width: 26px; height: 26px; border: 1px solid var(--border); border-radius: var(--radius-btn);
  background: var(--bg-elevated); color: var(--text-secondary); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; font-size: 13px;
}
.trace-panel:not(.collapsed) .collapse-toggle { left: auto; right: 10px; }
.collapse-toggle:hover { color: var(--text-primary); border-color: var(--border-strong); }
</style>
