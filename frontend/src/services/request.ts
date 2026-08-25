import Taro from '@tarojs/taro'

import { useSessionStore } from '../stores/session'
import type { ApiErrorBody, LoginResponse } from '../types/api'

export class ApiError extends Error {
  code: string
  status: number
  details?: Record<string, unknown>
  isNetworkError: boolean

  constructor(options: {
    message: string
    code?: string
    status?: number
    details?: Record<string, unknown>
    isNetworkError?: boolean
  }) {
    super(options.message)
    this.name = 'ApiError'
    this.code = options.code || 'UNKNOWN_ERROR'
    this.status = options.status || 0
    this.details = options.details
    this.isNetworkError = Boolean(options.isNetworkError)
  }
}

type RequestMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE'

interface RequestOptions {
  method?: RequestMethod
  data?: unknown
  authenticated?: boolean
  retryAuthentication?: boolean
}

async function refreshSession(): Promise<void> {
  const code = process.env.TARO_ENV === 'weapp'
    ? (await Taro.login()).code
    : 'h5-local-preview'
  const response = await Taro.request<LoginResponse>({
    url: `${API_BASE_URL}/auth/wechat`,
    method: 'POST',
    data: { code },
    header: { 'content-type': 'application/json' },
    timeout: 20000,
  })
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new ApiError({ message: '登录状态已失效，请重新进入小程序', code: 'UNAUTHORIZED', status: 401 })
  }
  useSessionStore.getState().setSession(response.data.access_token, response.data.user)
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const token = useSessionStore.getState().accessToken
  const header: Record<string, string> = { 'content-type': 'application/json' }
  if (options.authenticated !== false && token) {
    header.Authorization = `Bearer ${token}`
  }
  try {
    const response = await Taro.request<T>({
      url: `${API_BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      timeout: 60000,
    })
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return response.data
    }
    const body = response.data as ApiErrorBody
    const apiError = body?.error
    if (response.statusCode === 401) {
      useSessionStore.getState().clearSession()
      if (options.authenticated !== false && options.retryAuthentication !== false) {
        await refreshSession()
        return request<T>(path, { ...options, retryAuthentication: false })
      }
    }
    throw new ApiError({
      message: apiError?.message || '请求没有成功，请稍后再试',
      code: apiError?.code,
      status: response.statusCode,
      details: apiError?.details,
    })
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError({
      message: '网络开小差了，请检查连接后重试',
      code: 'NETWORK_ERROR',
      isNetworkError: true,
    })
  }
}
