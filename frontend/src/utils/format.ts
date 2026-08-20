// =====================================================================
// 通用格式化工具
// =====================================================================

/** 生成简短唯一 ID（前端消息/记录用） */
export function genId(prefix = 'id'): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

/** 字节大小可读化 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 中文 locale 时间格式化器（模块级缓存复用，避免重复构造） */
const TIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

/** 时间可读化：空值返回 '—'，非法值兜底返回原字符串 */
export function displayTime(value: string | number | Date | null | undefined): string {
  if (value == null || value === '') return '—'
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return TIME_FORMATTER.format(date)
}

/** 截断字符串 */
export function truncate(str: string, max = 30): string {
  return str.length > max ? `${str.slice(0, max)}…` : str
}

/** 按分隔符切分关键词 */
export function splitKeywords(input: string): string[] {
  return input
    .toLowerCase()
    .split(/[\s,，、]+/)
    .filter((k) => k.length >= 2)
}

/** 院系 → 颜色（与后端 DEPT_COLORS 对齐，前端补充更多院系） */
const DEPT_COLORS: Record<string, string> = {
  自动化系: '#4E79A7',
  计算机科学与技术系: '#F28E2B',
  电子工程系: '#E15759',
  机械工程系: '#76B7B2',
  材料学院: '#59A14f',
  精密仪器系: '#EDC948',
  能源与动力工程系: '#B07AA1',
  航天航空学院: '#FF9DA7',
}
const DEPT_FALLBACK = '#9C755F'

export function deptColor(dept: string): string {
  return DEPT_COLORS[dept] || DEPT_FALLBACK
}

/** 防抖 */
export function debounce<T extends (...args: never[]) => void>(fn: T, delay = 200): T {
  let timer: ReturnType<typeof setTimeout> | null = null
  return ((...args: Parameters<T>) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), delay)
  }) as T
}
