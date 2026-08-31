import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CreationFlow } from '../creationFlow'
import { ApiError, createNetworkError, parseApiErrorResponse } from '../apiError'
import { getGameVerification } from '../gameVerification'
import type { Game } from '../../types/api'

const game: Game = { id: 'game-fixture', topic: '高情商聊天', title: '沟通', status: 'active', hearts: 3,
  current_level: 0, progress: 0, level: null, summary: [], elapsed_seconds: null, input_type: 'keyword',
  generation_mode: 'basic', verification_notice: '未经联网核验', sources: [], retrieved_at: null }
const failure = (overrides: Record<string, unknown> = {}) => parseApiErrorResponse(503, {
  error: { code: 'SEARCH_UNAVAILABLE', message: '资料服务暂不可用', details: {
    request_id: 'a'.repeat(32), reason: 'PROVIDER_TIMEOUT',
    fallback: { available: true, token: 'fixture-permit', expires_at: '2026-08-31T08:05:00Z', mode: 'basic', notice: '未经联网核验' },
    ...overrides,
  } },
})
function setup() {
  const createGame = vi.fn().mockRejectedValue(failure())
  const createBasicGame = vi.fn().mockResolvedValue(game)
  const ensureSession = vi.fn().mockResolvedValue(undefined)
  const flow = new CreationFlow({ createGame, createBasicGame, ensureSession }, '高情商聊天', 'user-fixture')
  return { flow, createGame, createBasicGame, ensureSession }
}

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-08-31T08:00:00Z')) })
afterEach(() => { vi.useRealTimers() })

describe('页面内存许可与显式选择', () => {
  it('失败与许可全过程不输出客户端日志或持久化快照凭据', async () => {
    const spies = ['log','info','warn','error'].map(method => vi.spyOn(console,method as 'log').mockImplementation(() => undefined))
    try {
      const {flow,createBasicGame}=setup()
      createBasicGame.mockRejectedValue(new ApiError({code:'AI_GENERATION_FAILED',message:'sensitive-fixture',status:502}))
      await flow.startOnline(); flow.selectBasic(); await flow.confirmBasic()
      expect(JSON.stringify(flow.getSnapshot())).not.toContain('fixture-permit')
      expect(JSON.stringify(flow.getSnapshot())).not.toContain('sensitive-fixture')
      spies.forEach(spy => expect(spy).not.toHaveBeenCalled())
    } finally { spies.forEach(spy => spy.mockRestore()) }
  })
  it('保留安全诊断，收到失败及打开告知页都不自动生成', async () => {
    const { flow, createBasicGame } = setup()
    await flow.startOnline()
    expect(flow.getSnapshot()).toMatchObject({ view: 'error', canUseBasic: true, error: { code: 'SEARCH_UNAVAILABLE', requestId: 'a'.repeat(32), reason: 'PROVIDER_TIMEOUT' } })
    expect(JSON.stringify(flow.getSnapshot())).not.toContain('fixture-permit')
    flow.selectBasic()
    expect(flow.getSnapshot().view).toBe('confirm')
    expect(createBasicGame).not.toHaveBeenCalled()
    flow.returnToFailure()
    expect(flow.getSnapshot().view).toBe('error')
    expect(createBasicGame).not.toHaveBeenCalled()
    flow.selectBasic()
    expect(await flow.confirmBasic()).toEqual(game)
    expect(createBasicGame).toHaveBeenCalledWith({ topic: '高情商聊天', fallback_token: 'fixture-permit', acknowledge_unverified: true }, expect.anything())
    expect(flow.getSnapshot().canUseBasic).toBe(false)
  })

  it('不选择告知页不能直接确认，反复点击仅一个在途请求', async () => {
    const { flow, createBasicGame } = setup()
    await flow.startOnline()
    expect(await flow.confirmBasic()).toBeNull()
    flow.selectBasic()
    let complete!: (value: Game) => void
    createBasicGame.mockImplementation(() => new Promise(resolve => { complete = resolve }))
    const pending = flow.confirmBasic()
    expect(flow.getSnapshot().view).toBe('basic-loading')
    expect(await flow.confirmBasic()).toBeNull()
    complete(game)
    await pending
    expect(createBasicGame).toHaveBeenCalledTimes(1)
  })

  it.each([{}, { fallback: { available: false } }, { fallback: { available: true } },
    { fallback: { available: true, token: 'x', mode: 'legacy', expires_at: '2026-08-31T08:05:00Z' } },
    { fallback: { available: true, token: 'x', mode: 'basic', expires_at: 'invalid', notice: '未经联网核验' } },
  ])('旧响应或无效许可不开放入口 %#', async (details) => {
    const { flow, createGame, createBasicGame } = setup()
    createGame.mockRejectedValue(new ApiError({ code: 'SEARCH_UNAVAILABLE', message: '失败', status: 503, details }))
    await flow.startOnline(); flow.selectBasic(); await flow.confirmBasic()
    expect(flow.getSnapshot().canUseBasic).toBe(false)
    expect(createBasicGame).not.toHaveBeenCalled()
  })

  it.each(['edit', 'leave', 'identity', 'retry'] as const)('%s 清除许可且不执行兜底', async (action) => {
    const { flow, createGame, createBasicGame } = setup()
    await flow.startOnline()
    if (action === 'edit') flow.edit('新知识')
    if (action === 'leave') flow.leave()
    if (action === 'identity') flow.changeIdentity('other-user')
    if (action === 'retry') { createGame.mockRejectedValue(createNetworkError()); await flow.startOnline() }
    flow.selectBasic(); await flow.confirmBasic()
    expect(flow.getSnapshot().canUseBasic).toBe(false)
    expect(createBasicGame).not.toHaveBeenCalled()
  })

  it.each(['edit', 'leave', 'identity'] as const)('%s 取消请求且迟到响应不恢复许可', async (action) => {
    const { flow, createGame } = setup()
    let reject!: (error: unknown) => void
    let entered!: () => void
    const started = new Promise<void>(resolve => { entered = resolve })
    createGame.mockImplementation(() => new Promise((_, fail) => { reject = fail; entered() }))
    const pending = flow.startOnline()
    await started
    const cancellation = createGame.mock.calls[0][1]
    if (action === 'edit') flow.edit('新知识')
    if (action === 'leave') flow.leave()
    if (action === 'identity') flow.changeIdentity('other-user')
    expect(cancellation.cancelled).toBe(true)
    reject(failure())
    expect(await pending).toBeNull()
    expect(flow.getSnapshot()).toMatchObject({ view: 'home', canUseBasic: false })
  })

  it('取消首次登录等待后不再发送创建请求', async () => {
    const { flow, ensureSession, createGame } = setup()
    let done!: () => void
    ensureSession.mockImplementation(() => new Promise<void>(resolve => { done = resolve }))
    const pending = flow.startOnline()
    flow.leave(); done(); await pending
    expect(createGame).not.toHaveBeenCalled()
  })

  it('许可到期移除入口，并阻止发起请求', async () => {
    const { flow, createBasicGame } = setup()
    await flow.startOnline(); flow.selectBasic()
    vi.setSystemTime(new Date('2026-08-31T08:05:00Z'))
    flow.checkExpiry()
    expect(flow.getSnapshot()).toMatchObject({ view: 'expired', canUseBasic: false })
    await flow.confirmBasic()
    expect(createBasicGame).not.toHaveBeenCalled()
  })

  it('basic 业务失败只允许手动重试原许可，不采用递归许可', async () => {
    const { flow, createBasicGame } = setup()
    createBasicGame.mockRejectedValue(failure({ fallback: { available: false } }))
    await flow.startOnline(); flow.selectBasic(); await flow.confirmBasic()
    expect(flow.getSnapshot()).toMatchObject({ view: 'basic-error', canUseBasic: true })
    expect(createBasicGame).toHaveBeenCalledTimes(1)
    createBasicGame.mockResolvedValue(game)
    await flow.confirmBasic()
    expect(createBasicGame).toHaveBeenCalledTimes(2)
  })

  it.each([createNetworkError(), new ApiError({ code: 'BASIC_MODE_NOT_ALLOWED', status: 403, message: '许可无效' }), new ApiError({code:'UNAUTHORIZED',status:401,message:'登录失效'})])('basic 无响应/拒绝/失去登录清空许可', async error => {
    const { flow, createBasicGame } = setup()
    createBasicGame.mockRejectedValue(error)
    await flow.startOnline(); flow.selectBasic(); await flow.confirmBasic()
    expect(flow.getSnapshot().canUseBasic).toBe(false)
    await flow.confirmBasic()
    expect(createBasicGame).toHaveBeenCalledTimes(1)
  })
})

describe('从持久化结果识别模式', () => {
  it('basic 重进保持固定提示且没有来源', () => {
    expect(getGameVerification(JSON.parse(JSON.stringify(game)))).toEqual({ isBasic: true, notice: '未经联网核验', sources: [], retrievedAt: null })
  })
  it('旧响应缺字段不报错、不把空来源推断成 basic', () => {
    expect(getGameVerification({ id: 'old' } as Game)).toEqual({ isBasic: false, notice: null, sources: [], retrievedAt: null })
  })
  it('basic 即使收到矛盾来源也不展示联网标识', () => {
    expect(getGameVerification({ ...game, sources: [{id:'bad'}] as Game['sources'] }).sources).toEqual([])
  })
})
