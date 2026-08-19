import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'
import { beginRequest, finishRequest } from '@/utils/performance'

// =====================================================================
// Axios 实例：统一 baseURL / 拦截器 / 错误提示
// 开发期由 vite proxy 转发 /api /v1 到后端，生产期同源
// =====================================================================

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

function readCookie(name: string): string | undefined {
  return document.cookie
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1)
}

function serverFilename(contentDisposition: string | null) {
  const encoded = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const fallback = contentDisposition?.match(/filename="([^"]+)"/i)?.[1]
  const value = encoded ? decodeURIComponent(encoded) : fallback || 'download'
  return value.replace(/[\\/]/g, '_').slice(0, 180) || 'download'
}

async function sha256Hex(payload: ArrayBuffer) {
  const digest = await crypto.subtle.digest('SHA-256', payload)
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

/** 以 CSRF 保护的 POST 兑换私有 Blob，并校验服务端摘要与文件 magic。 */
export async function postPrivateBlob(url: string) {
  const csrf = readCookie('tsing_radar_csrf')
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {},
    cache: 'no-store',
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `私有下载失败（HTTP ${response.status}）`)
  }
  const blob = await response.blob()
  const payload = await blob.arrayBuffer()
  const magic = new Uint8Array(payload.slice(0, 5))
  const isPdf =
    magic.length >= 5 &&
    String.fromCharCode(...magic) === '%PDF-'
  const isDocx =
    magic.length >= 4 &&
    magic[0] === 0x50 &&
    magic[1] === 0x4b &&
    magic[2] === 0x03 &&
    magic[3] === 0x04
  if (!isPdf && !isDocx) throw new Error('服务端下载文件 magic 校验失败')
  const expectedDigest = response.headers.get('X-Artifact-SHA256')
  if (!expectedDigest || (await sha256Hex(payload)) !== expectedDigest.toLowerCase()) {
    throw new Error('服务端下载文件完整性校验失败')
  }
  return {
    blob,
    filename: serverFilename(response.headers.get('Content-Disposition')),
    sha256: expectedDigest.toLowerCase(),
  }
}

// 写操作使用双提交 CSRF；身份只由 HttpOnly opaque 会话 Cookie 决定。
service.interceptors.request.use(
  (config) => {
    beginRequest(config, config.url || '')
    if (config.data instanceof FormData) {
      delete config.headers['Content-Type']
    }
    const method = (config.method || 'get').toLowerCase()
    if (!['get', 'head', 'options'].includes(method)) {
      const csrf = readCookie('tsing_radar_csrf')
      if (csrf) config.headers['X-CSRF-Token'] = decodeURIComponent(csrf)
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截：统一解包 { data } 与错误提示
service.interceptors.response.use(
  (response) => {
    finishRequest(response.config, response.status)
    return response.data
  },
  (error) => {
    finishRequest(error.config, error.response?.status || error.code || 'error')
    // 主动取消的请求不弹错误提示（由调用方静默处理）
    if (axios.isCancel(error)) {
      return Promise.reject(error)
    }
    const msg =
      error.response?.data?.detail ||
      error.response?.data?.message ||
      error.message ||
      '请求失败'
    // 401/403 不弹消息（由路由守卫处理）
    if (error.response?.status !== 401 && error.response?.status !== 403) {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  },
)

/** 通用 GET */
export function get<T>(url: string, params?: Record<string, unknown>, config?: AxiosRequestConfig) {
  return service.get<unknown, T>(url, { params, ...config })
}

/** 通用 POST */
export function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  return service.post<unknown, T>(url, data, config)
}

/** 通用 PATCH */
export function patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  return service.patch<unknown, T>(url, data, config)
}

/** 通用 DELETE */
export function remove<T>(url: string, config?: AxiosRequestConfig) {
  return service.delete<unknown, T>(url, config)
}

/** 每次用户意图生成一个高熵键；网络失败后的手动重试应复用同一键。 */
export function newIdempotencyKey(operation: string) {
  return `${operation}:${crypto.randomUUID()}`
}

/** 初始化服务端高熵匿名会话。 */
export function bootstrapSession() {
  return service.get<unknown, { status: string; channel: string; persistent: boolean }>(
    '/api/session',
  )
}

/** 网页免认证测试模式公开状态（未实名认证测试身份标注）。 */
export interface WebTestModeStatus {
  enabled: boolean
  label: string
  expires_at: string | null
  active: boolean
}

export function fetchWebTestMode() {
  return service.get<unknown, WebTestModeStatus>('/api/web-test-mode')
}

export type { ApiResponse }
export default service
