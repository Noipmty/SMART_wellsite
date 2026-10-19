/* ============ 统一轮询：页面隐藏时自动暂停，组件卸载时停止 ============ */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useDocumentVisibility } from '@vueuse/core'
import { watch } from 'vue'

/**
 * @param fn 轮询执行的异步函数
 * @param interval 间隔毫秒；传 0 表示不自动启动（手动 start）
 * @param immediate 挂载后立即执行一次（默认 true）
 */
export function usePolling(fn: () => Promise<void> | void, interval: number, immediate = true) {
  const running = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  const visibility = useDocumentVisibility()

  async function tick() {
    if (running.value) return // 防重入
    running.value = true
    try { await fn() } finally { running.value = false }
  }

  function loop() {
    stop()
    if (interval <= 0) return
    timer = setTimeout(async () => { await tick(); loop() }, interval)
  }

  function start() { loop() }
  function stop() { if (timer) { clearTimeout(timer); timer = null } }

  // 页面隐藏时暂停，恢复可见时立即补一次再继续轮询
  watch(visibility, v => {
    if (v === 'visible') { tick(); loop() } else stop()
  })

  onMounted(() => { if (immediate) tick(); if (interval > 0) loop() })
  onBeforeUnmount(stop)

  return { running, start, stop, tick }
}
