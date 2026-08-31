import type { ApiErrorBody } from '../types/api'

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseApiErrorResponse(status: number, data: unknown): ApiError {
  const body = isRecord(data) ? data as ApiErrorBody : undefined
  const payload = body?.error
  const details = isRecord(payload?.details) ? payload.details : undefined

  return new ApiError({
    message: typeof payload?.message === 'string'
      ? payload.message
      : '请求没有成功，请稍后再试',
    code: typeof payload?.code === 'string' ? payload.code : 'HTTP_ERROR',
    status,
    details,
  })
}

export function createNetworkError(): ApiError {
  return new ApiError({
    message: '网络开小差了，请检查连接后重试',
    code: 'NETWORK_ERROR',
    isNetworkError: true,
  })
}
