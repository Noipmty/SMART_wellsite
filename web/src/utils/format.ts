/* ============ 时间格式化小工具（展示层统一口径） ============ */

const pad = (n: number) => n.toString().padStart(2, '0')

function toDate(iso: string | Date): Date {
  return iso instanceof Date ? iso : new Date(iso)
}

/** HH:mm:ss —— 告警时间、日志时间 */
export function fmtTime(iso: string | Date): string {
  const d = toDate(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** MM-dd HH:mm —— 列表次要时间 */
export function fmtShort(iso: string | Date): string {
  const d = toDate(iso)
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** YYYY-MM-dd HH:mm —— 详情页完整时间 */
export function fmtFull(iso: string | Date): string {
  const d = toDate(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 相对时间：x 分钟前 / x 小时前 */
export function fmtAgo(iso: string | Date): string {
  const diff = Date.now() - toDate(iso).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}
