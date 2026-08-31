import { beforeEach, expect, it, vi } from 'vitest'
import Taro from '@tarojs/taro'
import { request } from '../request'
import { RequestCancellation } from '../requestCancellation'

const state = vi.hoisted(() => ({ accessToken: 'expired', user: {id:'same-user'},
  setSession: vi.fn(), clearSession: vi.fn() }))
vi.mock('@tarojs/taro', () => ({ default: { request: vi.fn() } }))
vi.mock('../../stores/session', () => ({ useSessionStore: { getState: () => state } }))

beforeEach(() => {
  vi.stubGlobal('API_BASE_URL', 'http://example.invalid/api/v1')
  state.accessToken = 'expired'
  vi.mocked(Taro.request).mockReset(); state.clearSession.mockReset(); state.setSession.mockReset()
  state.setSession.mockImplementation((token: string) => { state.accessToken = token })
})

it('同账号刷新不先清空身份而误取消当前生成', async () => {
  const cancellation = new RequestCancellation()
  state.clearSession.mockImplementation(() => cancellation.cancel())
  vi.mocked(Taro.request).mockResolvedValueOnce({statusCode:401, data:{}} as never)
    .mockResolvedValueOnce({statusCode:200, data:{access_token:'refreshed', user:{id:'same-user'}}} as never)
    .mockResolvedValueOnce({statusCode:201, data:{id:'game'}} as never)
  await expect(request('/games', {method:'POST', cancellation})).resolves.toEqual({id:'game'})
  expect(state.clearSession).not.toHaveBeenCalled()
})

it('刷新期间切换账号不被旧登录响应覆盖或重放旧请求', async () => {
  vi.mocked(Taro.request).mockResolvedValueOnce({statusCode:401, data:{}} as never)
    .mockImplementationOnce(async () => {
      state.accessToken = 'new-account-token'
      return {statusCode:200, data:{access_token:'old-account-refresh',user:{id:'same-user'}}} as never
    })
  await expect(request('/games', {method:'POST'})).rejects.toMatchObject({code:'REQUEST_CANCELLED'})
  expect(state.setSession).not.toHaveBeenCalled()
  expect(state.accessToken).toBe('new-account-token')
  expect(Taro.request).toHaveBeenCalledTimes(2)
})
