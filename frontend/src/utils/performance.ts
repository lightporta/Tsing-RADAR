import { readonly, ref } from 'vue'

export interface ClientPerformanceMetric {
  kind: 'route' | 'request'
  name: string
  duration_ms: number
  status?: number | string
  recorded_at: string
}

const MAX_METRICS = 200
const metrics = ref<ClientPerformanceMetric[]>([])
const activeRequests = ref(0)
const requestStarts = new WeakMap<object, { startedAt: number; name: string }>()
let activeRoute: { startedAt: number; name: string } | null = null

function safePath(value: string) {
  try {
    return new URL(value, window.location.origin).pathname
      .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ':id')
      .replace(/\/[A-Za-z0-9_-]{24,}(?=\/|$)/g, '/:id')
  } catch {
    return value.split('?')[0]
  }
}

function record(metric: ClientPerformanceMetric) {
  metrics.value.push(metric)
  if (metrics.value.length > MAX_METRICS) {
    metrics.value.splice(0, metrics.value.length - MAX_METRICS)
  }
}

export function beginRequest(config: object, url = '') {
  requestStarts.set(config, { startedAt: performance.now(), name: safePath(url) })
  activeRequests.value += 1
}

export function finishRequest(config: object | undefined, status?: number | string) {
  if (!config) return
  const started = requestStarts.get(config)
  if (!started) return
  requestStarts.delete(config)
  activeRequests.value = Math.max(0, activeRequests.value - 1)
  record({
    kind: 'request',
    name: started.name,
    duration_ms: Math.round((performance.now() - started.startedAt) * 10) / 10,
    status,
    recorded_at: new Date().toISOString(),
  })
}

export function beginRoute(path: string) {
  activeRoute = { startedAt: performance.now(), name: safePath(path) }
}

export function finishRoute(status: string) {
  if (!activeRoute) return
  record({
    kind: 'route',
    name: activeRoute.name,
    duration_ms: Math.round((performance.now() - activeRoute.startedAt) * 10) / 10,
    status,
    recorded_at: new Date().toISOString(),
  })
  activeRoute = null
}

export function performanceSnapshot() {
  const values = metrics.value.map((item) => ({ ...item }))
  const durations = values.map((item) => item.duration_ms).sort((a, b) => a - b)
  const percentile = (fraction: number) =>
    durations.length ? durations[Math.min(durations.length - 1, Math.floor(durations.length * fraction))] : 0
  return {
    active_requests: activeRequests.value,
    metric_count: values.length,
    p50_ms: percentile(0.5),
    p95_ms: percentile(0.95),
    max_ms: durations.at(-1) || 0,
    metrics: values,
  }
}

export const clientPerformance = {
  activeRequests: readonly(activeRequests),
  metrics: readonly(metrics),
  snapshot: performanceSnapshot,
}

declare global {
  interface Window {
    __TSINGRADAR_PERFORMANCE__?: { snapshot: typeof performanceSnapshot }
  }
}

if (typeof window !== 'undefined') {
  Object.defineProperty(window, '__TSINGRADAR_PERFORMANCE__', {
    configurable: true,
    value: { snapshot: performanceSnapshot },
  })
}
