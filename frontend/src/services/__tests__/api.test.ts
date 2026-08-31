import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { request } from '../request'

vi.mock('../request', () => ({ request: vi.fn() }))

const requestMock = vi.mocked(request)

describe('api.createGame', () => {
  beforeEach(() => {
    requestMock.mockReset()
  })

  it('为联网研究链路设置 90 秒超时', async () => {
    requestMock.mockResolvedValue({ id: 'game-1' })

    await api.createGame('Harness Engineering')

    expect(requestMock).toHaveBeenCalledWith('/games', {
      method: 'POST',
      data: { topic: 'Harness Engineering' },
      timeout: 90000,
    })
  })

  it('独立 basic 请求有明确同意和 90 秒上限，不自动重新认证重放许可', async () => {
    requestMock.mockResolvedValue({ id: 'basic-fixture' })
    const body = { topic: '高情商聊天', fallback_token: 'fixture-token', acknowledge_unverified: true as const }
    await api.createBasicGame(body)
    expect(requestMock).toHaveBeenCalledWith('/games/basic', {
      method: 'POST', data: body, timeout: 90000, retryAuthentication: false,
    })
  })
})
