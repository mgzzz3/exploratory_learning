import { beforeEach, expect, it, vi } from 'vitest'
import Taro from '@tarojs/taro'
import { request } from '../request'
import { RequestCancellation } from '../requestCancellation'

vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }))
vi.mock('../../stores/session', () => ({ useSessionStore: { getState: () => ({ accessToken: null, clearSession: vi.fn() }) } }))
beforeEach(() => { vi.stubGlobal('API_BASE_URL', 'http://example.invalid/api/v1'); vi.mocked(Taro.request).mockReset() })

it('取消传给实际 RequestTask.abort，并返回安全取消码', async () => {
  let fail!: (error: unknown) => void
  const abort = vi.fn(() => fail(new Error('sensitive-provider-fixture')))
  const pending = Object.assign(new Promise((_, reject) => { fail = reject }), { abort })
  vi.mocked(Taro.request).mockReturnValue(pending as unknown as ReturnType<typeof Taro.request>)
  const cancellation = new RequestCancellation()
  const response = request('/games', { method: 'POST', cancellation })
  cancellation.cancel()
  await expect(response).rejects.toMatchObject({ code: 'REQUEST_CANCELLED', isNetworkError: false })
  expect(abort).toHaveBeenCalledTimes(1)
})

it('已取消的请求不发出，取消是幂等的', async () => {
  const cancellation = new RequestCancellation()
  cancellation.cancel(); cancellation.cancel()
  await expect(request('/games', { cancellation })).rejects.toMatchObject({ code: 'REQUEST_CANCELLED' })
  expect(Taro.request).not.toHaveBeenCalled()
})

it('basic 登录失败不刷新认证、也不重放许可', async () => {
  vi.mocked(Taro.request).mockResolvedValue({ statusCode: 401, data: { error: { code: 'UNAUTHORIZED', message: '登录失效' } } } as never)
  await expect(request('/games/basic', { method:'POST', retryAuthentication:false })).rejects.toMatchObject({code:'UNAUTHORIZED'})
  expect(Taro.request).toHaveBeenCalledTimes(1)
})
