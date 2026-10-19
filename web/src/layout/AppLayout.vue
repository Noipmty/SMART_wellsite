<template>
  <div class="layout">
    <!-- ============ 顶栏（全局常驻） ============ -->
    <header class="topbar">
      <div class="topbar-left">
        <el-tooltip :content="app.navCollapsed ? '展开导航' : '收起导航'" placement="bottom">
          <button class="icon-btn clickable" @click="app.toggleNav()">
            <el-icon><Fold v-if="!app.navCollapsed" /><Expand v-else /></el-icon>
          </button>
        </el-tooltip>
        <span class="site-name">智慧井场 WS001</span>
        <span class="divider" />
        <span class="summary-item">
          <span class="dot dot-ok" />
          <span class="mono">{{ app.onlineWells }}/{{ app.wellTotal }}</span>&nbsp;口井在线
        </span>
        <router-link to="/alerts" class="summary-item clickable alert-entry">
          <span class="dot" :class="app.alertTotal > 0 ? 'dot-danger' : 'dot-ok'" />
          未处理告警&nbsp;<span class="mono">{{ app.alertTotal }}</span>
          <el-badge v-if="app.alertTotal > 0" :value="app.alertTotal" type="danger" class="alert-badge" />
        </router-link>
        <router-link to="/graph" class="summary-item clickable">
          <el-icon><Share /></el-icon>
          图谱&nbsp;<span class="mono">v{{ app.graphVersion }}</span>
        </router-link>
      </div>
      <div class="topbar-right">
        <el-tooltip content="快捷键" placement="bottom">
          <button class="icon-btn clickable" @click="hotkeyVisible = true">
            <el-icon><Key /></el-icon>
          </button>
        </el-tooltip>
        <el-dropdown trigger="click">
          <div class="user-chip clickable">
            <span class="avatar">{{ app.dutyUser.slice(0, 1) }}</span>
            <span>{{ app.dutyUser }} · 值班员</span>
            <el-icon><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item>班次：早班 08:00–20:00</el-dropdown-item>
              <el-dropdown-item divided>交接班记录</el-dropdown-item>
              <el-dropdown-item>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="body">
      <!-- ============ 左侧导航 ============ -->
      <aside class="nav" :class="{ collapsed: app.navCollapsed }">
        <router-link
          v-for="item in NAV" :key="item.path" :to="item.path"
          class="nav-item clickable" :class="{ active: route.path === item.path }"
        >
          <el-tooltip :disabled="!app.navCollapsed" :content="item.title" placement="right">
            <el-icon :size="18"><component :is="item.icon" /></el-icon>
          </el-tooltip>
          <span v-if="!app.navCollapsed" class="nav-title">{{ item.title }}</span>
          <el-badge
            v-if="item.path === '/alerts' && app.alertTotal > 0"
            :value="app.alertTotal" type="danger" class="nav-badge"
          />
        </router-link>
        <div class="nav-footer">
          <div v-if="!app.navCollapsed" class="nav-hint">
            <div>G D 对话 · G A 告警</div>
            <div>G P 生产 · G K 知识</div>
          </div>
        </div>
      </aside>

      <!-- ============ 主工作区（随路由切换；右侧面板由对话页自带） ============ -->
      <main class="main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <!-- 快捷键说明弹层 -->
    <el-dialog v-model="hotkeyVisible" title="快捷键" width="420px">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="Ctrl / ⌘ + K">全局搜索</el-descriptions-item>
        <el-descriptions-item label="G 然后 D">跳转值班对话</el-descriptions-item>
        <el-descriptions-item label="G 然后 A">跳转告警工单</el-descriptions-item>
        <el-descriptions-item label="G 然后 P">跳转生产数据</el-descriptions-item>
        <el-descriptions-item label="G 然后 K">跳转知识运营</el-descriptions-item>
        <el-descriptions-item label="G 然后 G">跳转知识图谱</el-descriptions-item>
        <el-descriptions-item label="Esc">关闭弹层</el-descriptions-item>
        <el-descriptions-item label="↑ / ↓ + Enter">告警列表切换与打开</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { h, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import {
  ArrowDown, Bell, ChatDotRound, Connection, Expand, Fold, Key,
  DataLine, Share, Collection,
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { usePolling } from '@/composables/usePolling'
import { useHotkeys } from '@/composables/useHotkeys'
import { onSimAlert, startRealtime } from '@/api/mock/realtime'
import { USE_MOCK } from '@/api'
import type { Level } from '@/api/types'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const hotkeyVisible = ref(false)

const NAV = [
  { path: '/chat', title: '值班对话', icon: ChatDotRound },
  { path: '/alerts', title: '告警工单', icon: Bell },
  { path: '/production', title: '生产数据', icon: DataLine },
  { path: '/knowledge', title: '知识运营', icon: Collection },
  { path: '/graph', title: '知识图谱', icon: Connection },
]

// 顶栏告警红点：30s 轮询（页面隐藏自动暂停）
usePolling(app.refreshSummary, 30_000)
useHotkeys()

/* ---------- 实时模拟：仅 mock 模式启动（真实后端模式告警由后端 sim/服务产生） ---------- */
if (USE_MOCK) {
  startRealtime()
  const NOTIFY_TYPE: Record<Level, 'error' | 'warning' | 'primary' | 'info'> = { 紧急: 'error', 预警: 'warning', 提醒: 'primary', 提示: 'info' }
  onSimAlert((alert, order) => {
    ElNotification({
      type: NOTIFY_TYPE[alert.level],
      title: `${alert.level}告警 · ${alert.scope} ${alert.cause}`,
      message: h('div', null, [
        h('div', { style: 'margin-bottom:6px' }, alert.content),
        h('div', { style: 'color: var(--text-disabled); font-size:12px; margin-bottom:6px' }, `已自动派单 ${order.order_id}`),
        h('a', {
          style: 'color: var(--accent-hover); cursor: pointer; font-size: 13px;',
          onClick: () => router.push({ path: '/alerts', query: { well: alert.scope } }),
        }, '去处置 →'),
      ]),
      duration: 8000,
    })
    app.refreshSummary() // 顶栏红点立即 +1
  })
}
</script>

<style scoped lang="scss">
.layout { height: 100%; display: flex; flex-direction: column; }

.topbar {
  height: var(--topbar-h); flex: none;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  z-index: 10;
}
.topbar-left { display: flex; align-items: center; gap: 14px; }
.topbar-right { display: flex; align-items: center; gap: 12px; }

.icon-btn {
  min-width: 32px; min-height: 32px;
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent; border: 1px solid transparent; border-radius: var(--radius-btn);
  color: var(--text-secondary); font-size: 16px; cursor: pointer;
  &:hover { color: var(--text-primary); background: var(--bg-elevated); }
}

.site-name { font-size: 16px; font-weight: 600; letter-spacing: 0.02em; }
.divider { width: 1px; height: 18px; background: var(--border-strong); }

.summary-item {
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--text-secondary); font-size: 13px;
  padding: 4px 8px; border-radius: var(--radius-btn);
  text-decoration: none;
  &.alert-entry { position: relative; }
}
.alert-badge { margin-left: -2px; }

.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot-ok { background: var(--level-ok); box-shadow: 0 0 6px rgba(63, 185, 80, .7); }
.dot-danger { background: var(--level-critical); box-shadow: 0 0 6px rgba(248, 81, 73, .8); }

.user-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 10px 4px 4px; border-radius: 18px;
  border: 1px solid var(--border); color: var(--text-primary);
  cursor: pointer; font-size: 13px;
  .avatar {
    width: 26px; height: 26px; border-radius: 50%;
    background: var(--accent); color: #fff;
    display: flex; align-items: center; justify-content: center; font-size: 13px;
  }
}

.body { flex: 1; display: flex; min-height: 0; }

.nav {
  width: var(--nav-w); flex: none;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  padding: 10px 8px;
  transition: width 0.18s ease-out;
  &.collapsed { width: var(--nav-w-collapsed); }
}
.nav-item {
  position: relative;
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; margin-bottom: 4px;
  border-radius: var(--radius-btn);
  color: var(--text-secondary); text-decoration: none;
  font-size: 14px;
  transition: background 0.15s ease-out, color 0.15s ease-out;
  &:hover { background: var(--bg-elevated); color: var(--text-primary); }
  &.active {
    background: var(--accent-dim); color: var(--accent-hover);
    box-shadow: inset 2px 0 0 var(--accent);
  }
  .collapsed & { justify-content: center; padding: 10px 0; }
}
.nav-badge { margin-left: auto; .collapsed & { position: absolute; top: 2px; right: 6px; } }
.nav-footer { margin-top: auto; padding: 8px 6px; }
.nav-hint { color: var(--text-disabled); font-size: 12px; line-height: 1.8; font-family: var(--font-mono); }

.main { flex: 1; min-width: 0; overflow: hidden; display: flex; flex-direction: column; }
</style>
