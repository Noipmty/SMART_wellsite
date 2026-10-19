<template>
  <div class="graph-view">
    <!-- ============ 顶部工具条 ============ -->
    <header class="graph-toolbar">
      <el-select
        v-model="searchName" filterable clearable placeholder="搜索实体定位…"
        style="width: 220px" @change="focusNode"
      >
        <el-option v-for="n in allNodes" :key="n.name" :label="`${n.name}（${n.entity_type}）`" :value="n.name" />
      </el-select>
      <el-checkbox-group v-model="typeFilter" @change="applyTypeFilter">
        <el-checkbox v-for="t in ALL_TYPES" :key="t" :value="t">{{ t }}</el-checkbox>
      </el-checkbox-group>
      <el-switch v-model="physicsOn" active-text="物理布局" @change="togglePhysics" />
      <div class="spacer" />
      <!-- 版本时间线滑块 -->
      <div class="version-box">
        <span class="mono version-label">v1</span>
        <el-slider
          v-model="versionView" :min="1" :max="Math.max(stats.version, 1)" :step="1"
          style="width: 140px" @change="onVersionSlide"
        />
        <span class="mono version-label current">v{{ stats.version }}</span>
      </div>
      <el-button size="small" type="primary" plain :loading="rebuilding" @click="doRebuild">手动重建</el-button>
    </header>

    <!-- 重建完成提示条 -->
    <transition name="fade">
      <div v-if="rebuildBanner" class="rebuild-banner">
        <el-icon><CircleCheckFilled /></el-icon>
        本次重建新增 <b class="mono">{{ rebuildBanner.nodes }}</b> 节点 / <b class="mono">{{ rebuildBanner.edges }}</b> 边 · 当前版本 <b class="mono">v{{ stats.version }}</b>
        <el-icon class="banner-close" @click="rebuildBanner = null"><Close /></el-icon>
      </div>
    </transition>

    <!-- 重建中状态条 -->
    <div v-if="stats.status === 'building'" class="building-bar">
      <el-icon class="is-loading"><Loading /></el-icon> 知识图谱重建中（v{{ stats.version }}）… 约需数秒
    </div>

    <!-- ============ 图主体 ============ -->
    <div class="graph-main">
      <div ref="netRef" class="net-box" />
      <!-- 图例 -->
      <div class="legend panel-card">
        <div v-for="(c, i) in communities" :key="c.community_id" class="legend-item">
          <span class="legend-dot" :style="{ background: PALETTE[i % PALETTE.length] }" />
          {{ c.title }}
        </div>
      </div>
    </div>

    <!-- ============ 节点详情抽屉 ============ -->
    <el-drawer v-model="drawerVisible" :title="detail?.entity.name" size="360px">
      <template v-if="detail">
        <div class="drawer-block">
          <el-tag effect="dark" :type="detail.entity.entity_type === '井' ? 'primary' : detail.entity.entity_type === '风险' ? 'danger' : detail.entity.entity_type === '文档' ? 'success' : 'warning'">
            {{ detail.entity.entity_type }}
          </el-tag>
          <span class="mono degree-hint">度 {{ detail.entity.degree }}</span>
        </div>
        <p class="drawer-desc">{{ detail.entity.description }}</p>
        <div v-if="detail.entity.sources.length" class="drawer-block">
          <div class="block-label">来源</div>
          <el-tag v-for="s in detail.entity.sources" :key="s" size="small" effect="plain" class="src-tag">{{ s }}</el-tag>
        </div>
        <div class="drawer-block">
          <div class="block-label">关联关系（{{ detail.neighbors.length }}）</div>
          <div v-for="(nb, i) in detail.neighbors" :key="i" class="neighbor-row" @click="onNeighborClick(nb)">
            <span class="rel-dir mono">{{ nb.direction === 'out' ? '→' : '←' }}</span>
            <span class="rel-name">{{ nb.relation }}</span>
            <span class="nb-name">{{ nb.node.name }}</span>
            <span class="mono nb-weight">w{{ nb.weight }}</span>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled, Close, Loading } from '@element-plus/icons-vue'
import { DataSet, Network } from 'vis-network/standalone'
import { entityNeighbors, graphData, graphStats, rebuildGraph } from '@/api'
import { KB_DOCS } from '@/api/mock/data'
import type { GraphCommunity, GraphNode, GraphStats as GraphStatsT, NeighborItem } from '@/api/types'

const router = useRouter()

const ALL_TYPES = ['井', '风险', '概念', '文档'] as const
const PALETTE = ['#2f81f7', '#3fb950', '#d29922', '#bc8cff', '#f85149', '#58a6ff', '#39c5cf']

/* ---------- 数据 ---------- */
const allNodes = ref<GraphNode[]>([])
const communities = ref<GraphCommunity[]>([])
const stats = ref<GraphStatsT>({ status: 'done', version: 1, node_count: 0, edge_count: 0, community_count: 0, built_at: null })

/* ---------- vis-network ---------- */
const netRef = ref<HTMLElement>()
let network: Network | null = null
let nodeSet: DataSet<Record<string, unknown>> | null = null
let edgeSet: DataSet<Record<string, unknown>> | null = null

/** 节点所属社区 → 颜色 */
const communityOf = new Map<string, number>()
function nodeColor(name: string) {
  const idx = communityOf.get(name)
  return idx == null ? '#6e7681' : PALETTE[idx % PALETTE.length]
}

async function buildGraph() {
  const data = await graphData()
  allNodes.value = data.nodes
  communities.value = data.communities
  communityOf.clear()
  data.communities.forEach((c, i) => c.members.forEach(m => communityOf.set(m, i)))

  nodeSet = new DataSet(data.nodes.map(n => ({
    id: n.name,
    label: n.name,
    title: `${n.entity_type} · ${n.description}`,
    color: { background: nodeColor(n.name), border: 'rgba(230,237,243,.25)' },
    // 大小按度映射
    size: 12 + n.degree * 3,
    font: { color: '#e6edf3', size: 13, face: 'PingFang SC, Microsoft YaHei, sans-serif' },
    borderWidth: 1.5,
    entityType: n.entity_type,
  })))
  edgeSet = new DataSet(data.edges.map((e, i) => ({
    id: i, from: e.source, to: e.target, label: e.relation,
    width: e.weight, arrows: 'to',
    color: { color: '#484f58', highlight: '#4a94ff' },
    font: { color: '#8b949e', size: 10, strokeWidth: 0, align: 'middle' },
  })))

  network = new Network(netRef.value!, { nodes: nodeSet, edges: edgeSet }, {
    physics: { enabled: physicsOn.value, solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -60, springLength: 120 } },
    interaction: { hover: true, tooltipDelay: 120 },
    edges: { smooth: { enabled: true, type: 'continuous', roundness: 0.4 } },
    nodes: { shape: 'dot' },
  })

  // 点击节点 → 详情抽屉
  network.on('click', params => {
    if (params.nodes.length) openDetail(params.nodes[0] as string)
  })
}

/* ---------- 类型过滤 / 物理开关 / 搜索定位 ---------- */
const typeFilter = ref<string[]>([...ALL_TYPES])
const physicsOn = ref(true)
const searchName = ref('')

function applyTypeFilter() {
  nodeSet?.update(allNodes.value.map(n => ({
    id: n.name, hidden: !typeFilter.value.includes(n.entity_type),
  })))
}
function togglePhysics() { network?.setOptions({ physics: { enabled: physicsOn.value } }) }
function focusNode(name: string) {
  if (!name || !network) return
  network.selectNodes([name])
  network.focus(name, { scale: 1.25, animation: { duration: 400, easingFunction: 'easeOutQuad' } })
  openDetail(name)
}

/* ---------- 详情抽屉 ---------- */
const drawerVisible = ref(false)
const detail = ref<{ entity: GraphNode; neighbors: NeighborItem[] } | null>(null)
async function openDetail(name: string) {
  detail.value = await entityNeighbors(name)
  drawerVisible.value = true
}

/** 邻居行点击：按节点类型路由——井→生产页定位、文档→知识库打开、概念/风险→图谱内聚焦 */
function onNeighborClick(nb: NeighborItem) {
  const name = nb.node.name
  const type = nb.node.entity_type
  if (type === '井') {
    router.push({ path: '/production', query: { well: name } })
    return
  }
  if (type === '文档') {
    const doc = KB_DOCS.find(d => d.title === name || name.includes(d.title) || d.title.includes(name))
    router.push({ path: '/knowledge', query: { tab: 'docs', ...(doc ? { doc: doc.doc_id } : {}) } })
    return
  }
  // 概念 / 风险：图谱内聚焦
  focusNode(name)
}

/* ---------- 版本滑块（快照演示） ---------- */
const versionView = ref(1)
function onVersionSlide(v: number | number[]) {
  if (v !== stats.value.version) ElMessage.info(`已切换到 v${v} 快照视角（mock 环境仅演示当前图结构）`)
  else ElMessage.success('当前为最新版本')
}

/* ---------- 重建：2s 轮询 building 态，完成后横幅 + 新增节点高亮 3s ---------- */
const rebuilding = ref(false)
const rebuildBanner = ref<{ nodes: number; edges: number } | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | null = null
let prevCounts = { nodes: 0, edges: 0 }

async function pollStats() {
  const s = await graphStats()
  const wasBuilding = stats.value.status === 'building'
  stats.value = s
  versionView.value = s.version

  if (wasBuilding && s.status === 'done') {
    // 对比重建前后计数，得出“新增 N 节点 / M 边”
    rebuildBanner.value = {
      nodes: Math.max(0, s.node_count - prevCounts.nodes),
      edges: Math.max(0, s.edge_count - prevCounts.edges),
    }
    flashNewNodes()
    rebuilding.value = false
  }
  if (s.status === 'building' && document.visibilityState === 'visible') {
    pollTimer = setTimeout(pollStats, 2000)
  }
}

/** 新增节点绿色高亮 3 秒渐隐（按度最高的两个节点模拟新增位） */
function flashNewNodes() {
  if (!nodeSet) return
  const top = [...allNodes.value].sort((a, b) => b.degree - a.degree).slice(0, 2).map(n => n.name)
  const highlight = top.map(id => ({
    id,
    color: { background: 'rgba(63,185,80,.95)', border: '#3fb950' },
    borderWidth: 3,
    shadow: { enabled: true, color: 'rgba(63,185,80,.9)', size: 22 },
  }))
  nodeSet.update(highlight as never)
  setTimeout(() => {
    nodeSet?.update(top.map(id => ({
      id,
      color: { background: nodeColor(id), border: 'rgba(230,237,243,.25)' },
      borderWidth: 1.5,
      shadow: { enabled: false },
    })) as never)
  }, 3000)
}

async function doRebuild() {
  rebuilding.value = true
  prevCounts = { nodes: stats.value.node_count, edges: stats.value.edge_count }
  await rebuildGraph()
  ElMessage.info('已触发知识图谱重建')
  pollStats()
}

onMounted(async () => {
  stats.value = await graphStats()
  prevCounts = { nodes: stats.value.node_count, edges: stats.value.edge_count }
  versionView.value = stats.value.version
  await buildGraph()
  // 若进入页面时正处于重建中（如从知识运营页采纳后跳入），继续轮询
  if (stats.value.status === 'building') { rebuilding.value = true; pollStats() }
})

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
  network?.destroy()
})
</script>

<style scoped>
.graph-view { display: flex; flex-direction: column; height: 100%; min-height: 0; }

.graph-toolbar {
  flex: none; display: flex; align-items: center; gap: 14px;
  padding: 10px 16px; background: var(--bg-panel); border-bottom: 1px solid var(--border);
}
.spacer { flex: 1; }
.version-box { display: flex; align-items: center; gap: 8px; }
.version-label { font-size: 11.5px; color: var(--text-disabled); }
.version-label.current { color: var(--accent-hover); font-weight: 700; }

.rebuild-banner {
  flex: none; display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; font-size: 13px;
  color: var(--level-ok); background: rgba(63,185,80,.1);
  border-bottom: 1px solid rgba(63,185,80,.35);
}
.banner-close { margin-left: auto; cursor: pointer; color: var(--text-secondary); }
.banner-close:hover { color: var(--text-primary); }

.building-bar {
  flex: none; display: flex; align-items: center; gap: 8px;
  padding: 8px 16px; font-size: 13px;
  color: var(--accent-hover); background: var(--accent-dim);
  border-bottom: 1px solid rgba(47,129,247,.35);
}

.graph-main { position: relative; flex: 1; min-height: 0; }
.net-box { position: absolute; inset: 0; }

.legend {
  position: absolute; left: 14px; bottom: 14px; z-index: 5;
  padding: 10px 14px; display: flex; flex-direction: column; gap: 6px;
  font-size: 12px; color: var(--text-secondary);
  background: rgba(22,27,34,.85); backdrop-filter: blur(4px);
}
.legend-item { display: flex; align-items: center; gap: 8px; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }

/* 抽屉 */
.drawer-block { margin-bottom: 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.degree-hint { color: var(--text-disabled); font-size: 12px; }
.drawer-desc { color: var(--text-secondary); font-size: 13px; line-height: 1.7; margin: 0 0 14px; }
.block-label { font-size: 12px; color: var(--text-disabled); width: 100%; margin-bottom: 2px; }
.src-tag { margin-right: 6px; }
.neighbor-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: var(--radius-btn); cursor: pointer;
  font-size: 13px; width: 100%;
}
.neighbor-row:hover { background: var(--bg-elevated); }
.rel-dir { color: var(--text-disabled); }
.rel-name { color: var(--level-warning); font-size: 12px; }
.nb-name { color: var(--text-primary); }
.nb-weight { margin-left: auto; color: var(--text-disabled); font-size: 11.5px; }
</style>
