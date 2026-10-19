/* ============ 全局状态：顶栏摘要 / 导航折叠 / 告警红点 / 图谱版本 ============ */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { graphStats, isOvertime, listAlerts } from '@/api'
import { WELLS } from '@/api/mock/data'

export const useAppStore = defineStore('app', () => {
  const navCollapsed = ref(false)
  const alertTotal = ref(0)          // 未处理（active）告警数
  const overtimeTotal = ref(0)       // 超时告警数
  const graphVersion = ref(0)
  const dutyUser = ref('张伟')

  const onlineWells = computed(() => WELLS.filter(w => w.status === 'active').length)
  const wellTotal = computed(() => WELLS.length)

  /** 顶栏轮询：30s 一次刷新红点与图谱版本 */
  async function refreshSummary() {
    const [alerts, stats] = await Promise.all([listAlerts({ status: 'active' }), graphStats()])
    alertTotal.value = alerts.total
    overtimeTotal.value = alerts.items.filter(isOvertime).length
    graphVersion.value = stats.version
  }

  function toggleNav() { navCollapsed.value = !navCollapsed.value }

  return { navCollapsed, alertTotal, overtimeTotal, graphVersion, dutyUser, onlineWells, wellTotal, refreshSummary, toggleNav }
})
