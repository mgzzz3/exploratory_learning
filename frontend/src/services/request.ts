import Taro from '@tarojs/taro'

import { useSessionStore } from '../stores/session'
import type { LoginResponse } from '../types/api'
import { ApiError, createNetworkError, parseApiErrorResponse } from './apiError'
import type { RequestCancellation } from './requestCancellation'

export { ApiError, parseApiErrorResponse } from './apiError'

type RequestMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE'

interface RequestOptions {
  method?: RequestMethod
  data?: unknown
  authenticated?: boolean
  retryAuthentication?: boolean
  timeout?: number
  cancellation?: RequestCancellation
}

function cancelledError() {
  return new ApiError({ code: 'REQUEST_CANCELLED', message: '请求已取消' })
}

async function refreshSession(expectedToken: string | null): Promise<void> {
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
  // A late refresh must never overwrite an account selected in the meantime.
  if (useSessionStore.getState().accessToken !== expectedToken) throw cancelledError()
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new ApiError({ message: '登录状态已失效，请重新进入小程序', code: 'UNAUTHORIZED', status: 401 })
  }
  useSessionStore.getState().setSession(response.data.access_token, response.data.user)
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  if (options.cancellation?.cancelled) throw cancelledError()
  const token = useSessionStore.getState().accessToken
  const header: Record<string, string> = { 'content-type': 'application/json' }
  if (options.authenticated !== false && token) {
    header.Authorization = `Bearer ${token}`
  }
  let unsubscribe: (() => void) | undefined
  try {
    const task = Taro.request<T>({
      url: `${API_BASE_URL}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header,
      timeout: options.timeout ?? 60000,
    })
    unsubscribe = options.cancellation?.subscribe(() => task.abort?.())
    const response = await task
    if (options.cancellation?.cancelled) throw cancelledError()
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return response.data
    }
    if (response.statusCode === 401) {
      if (useSessionStore.getState().accessToken !== token) throw cancelledError()
      if (options.authenticated !== false && options.retryAuthentication !== false) {
        try {
          await refreshSession(token)
        } catch (error) {
          if (useSessionStore.getState().accessToken === token) useSessionStore.getState().clearSession()
          throw error
        }
        return request<T>(path, { ...options, retryAuthentication: false })
      }
      useSessionStore.getState().clearSession()
    }
    throw parseApiErrorResponse(response.statusCode, response.data)
  } catch (error) {
    if (options.cancellation?.cancelled) throw cancelledError()
    if (error instanceof ApiError) throw error
    throw createNetworkError()
  } finally {
    unsubscribe?.()
  }
}
