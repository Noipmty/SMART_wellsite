/* ============ 全局快捷键：Ctrl+K 搜索 / G 系列跳转 / Esc 关闭弹层 ============ */
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const G_MAP: Record<string, string> = {
  d: '/chat',      // 值班对话
  a: '/alerts',    // 告警工单
  p: '/production',// 生产数据
  k: '/knowledge', // 知识运营
  g: '/graph',     // 知识图谱
}

export function useHotkeys(onSearch?: () => void) {
  const router = useRouter()
  let gPending = false
  let gTimer: ReturnType<typeof setTimeout> | null = null

  function handler(e: KeyboardEvent) {
    const target = e.target as HTMLElement
    const typing = ['INPUT', 'TEXTAREA'].includes(target.tagName) || target.isContentEditable

    // Ctrl/Cmd + K：全局搜索（输入中也可用）
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault()
      onSearch?.()
      return
    }
    if (typing) return

    if (e.key === 'Escape') {
      // Element 弹层自身监听 Esc，这里只兜底广播
      document.dispatchEvent(new CustomEvent('app:esc'))
      return
    }

    // G 然后字母：二连击跳转
    if (e.key.toLowerCase() === 'g' && !gPending) {
      gPending = true
      gTimer = setTimeout(() => { gPending = false }, 800)
      return
    }
    if (gPending) {
      const path = G_MAP[e.key.toLowerCase()]
      if (path) router.push(path)
      gPending = false
      if (gTimer) clearTimeout(gTimer)
    }
  }

  onMounted(() => window.addEventListener('keydown', handler))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', handler)
    if (gTimer) clearTimeout(gTimer)
  })
}
