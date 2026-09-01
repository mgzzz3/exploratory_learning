import { beforeEach, describe, expect, it, vi } from 'vitest'
import { battleApi } from '../battle'
import { request } from '../request'

vi.mock('../request', () => ({ request: vi.fn() }))

const requestMock = vi.mocked(request)

describe('battleApi', () => {
  beforeEach(() => {
    requestMock.mockReset()
  })

  it('建房请求带 90 秒超时，与联网出题保持一致', async () => {
    requestMock.mockResolvedValue({ id: 'room-1' })

    await battleApi.create('Python 基础')

    expect(requestMock).toHaveBeenCalledWith('/battles', {
      method: 'POST',
      data: { topic: 'Python 基础' },
      timeout: 90000,
    })
  })

  it('加入、就绪与状态查询命中正确的对战路由', async () => {
    requestMock.mockResolvedValue({ id: 'room-1' })

    await battleApi.join('room-1')
    await battleApi.ready('room-1')
    await battleApi.status('room-1')

    expect(requestMock).toHaveBeenNthCalledWith(1, '/battles/room-1/join', { method: 'POST' })
    expect(requestMock).toHaveBeenNthCalledWith(2, '/battles/room-1/ready', { method: 'POST' })
    expect(requestMock).toHaveBeenNthCalledWith(3, '/battles/room-1')
  })

  it('提交答案复用调用方的 attempt_id，保证网络重试幂等', async () => {
    requestMock.mockResolvedValue({ result: 'correct' })

    await battleApi.answer('room-1', 2, 'attempt-fixture')

    expect(requestMock).toHaveBeenCalledWith('/battles/room-1/answers', {
      method: 'POST',
      data: { option: 2, attempt_id: 'attempt-fixture' },
    })
  })
})
