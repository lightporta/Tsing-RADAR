import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiResponse } from '@/types/api'

// =====================================================================
// Axios 实例：统一 baseURL / 拦截器 / 错误提示
// 开发期由 vite proxy 转发 /api /v1 到后端，生产期同源
// =====================================================================

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：注入学生身份头（清小搭 SSO 占位）
service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('tsing_radar_token')
    if (token) {
      config.headers['X-Student-Token'] = token
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截：统一解包 { data } 与错误提示
// [PATCH] 支持统一响应格式 { code, message, data }，同时兼容旧的裸对象返回
service.interceptors.response.use(
  (response) => {
    const res = response.data
    // 统一响应格式 { code, message, data }
    if (res && typeof res === 'object' && 'code' in res) {
      if (res.code !== 0) {
        const msg = res.message || '请求失败'
        if (response.status !== 401 && response.status !== 403) {
          ElMessage.error(msg)
        }
        return Promise.reject(new Error(msg))
      }
      return res.data !== undefined ? res.data : res
    }
    // 兼容旧格式：直接返回 response.data
    return res
  },
  (error) => {
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

export type { ApiResponse }
export default service
