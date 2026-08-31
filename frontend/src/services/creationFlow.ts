import type { BasicFallback, BasicGameRequest, Game } from '../types/api'
import { ApiError, createNetworkError } from './apiError'
import { getGenerationErrorPresentation, type GenerationErrorPresentation } from './gameCreation'
import { BASIC_NOTICE } from './gameVerification'
import { RequestCancellation } from './requestCancellation'

interface Dependencies {
  createGame: (topic: string, cancellation: RequestCancellation) => Promise<Game>
  createBasicGame: (data: BasicGameRequest, cancellation: RequestCancellation) => Promise<Game>
  ensureSession: () => Promise<unknown>
}

interface Snapshot {
  topic: string
  view: 'home' | 'loading' | 'error' | 'confirm' | 'basic-loading' | 'basic-error' | 'expired'
  error: GenerationErrorPresentation | null
  canUseBasic: boolean
  expiresAt: number | null
}

function readPermit(error: ApiError): BasicFallback | null {
  if (error.isNetworkError || error.status < 400 || !/^[a-f0-9]{32}$/.test(String(error.details?.request_id || ''))) return null
  const value = error.details?.fallback as Partial<BasicFallback> | undefined
  if (!value || value.available !== true || value.mode !== 'basic' || value.notice !== BASIC_NOTICE
    || typeof value.token !== 'string' || !value.token || value.token.length > 4096
    || typeof value.expires_at !== 'string' || !Number.isFinite(Date.parse(value.expires_at))) return null
  return value as BasicFallback
}

/** 每个页面实例独立；许可不进入 React 快照、持久化 store、URL 或日志。 */
export class CreationFlow {
  private snapshot: Snapshot
  private listeners = new Set<() => void>()
  private permit: BasicFallback | null = null
  private cancellation: RequestCancellation | null = null
  private epoch = 0
  private authenticating = false

  constructor(private deps: Dependencies, topic = '', private identity: string | null = null) {
    this.snapshot = { topic, view: 'home', error: null, canUseBasic: false, expiresAt: null }
  }

  getSnapshot = (): Snapshot => this.snapshot
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private update(values: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, ...values }
    this.listeners.forEach(listener => listener())
  }
  private clearPermit() {
    this.permit = null
  }
  private invalidate() {
    this.epoch += 1
    this.authenticating = false
    this.cancellation?.cancel()
    this.cancellation = null
    this.clearPermit()
  }
  edit = (topic: string) => {
    this.invalidate()
    this.update({ topic, view: 'home', error: null, canUseBasic: false, expiresAt: null })
  }
  leave = () => this.edit(this.snapshot.topic)
  changeIdentity = (identity: string | null) => {
    if (identity === this.identity) return
    const initialLogin = this.authenticating && this.identity === null && identity !== null
    this.identity = identity
    if (!initialLogin) this.leave()
  }
  checkExpiry = () => {
    if (!this.permit || this.snapshot.view === 'basic-loading') return
    if (Date.parse(this.permit.expires_at) <= Date.now()) {
      this.clearPermit()
      this.update({ view: 'expired', canUseBasic: false, expiresAt: null })
    }
  }
  selectBasic = () => {
    this.checkExpiry()
    if (this.snapshot.view === 'error' && this.permit) this.update({ view: 'confirm' })
  }
  returnToFailure = () => {
    this.checkExpiry()
    if (this.snapshot.view === 'confirm') this.update({ view: 'error' })
  }
  startOnline = async (): Promise<Game | null> => {
    if (this.snapshot.view === 'loading' || this.snapshot.view === 'basic-loading') return null
    this.invalidate()
    const attempt = this.epoch
    const cancellation = new RequestCancellation()
    this.cancellation = cancellation
    const topic = this.snapshot.topic.trim()
    this.update({ topic, view: 'loading', error: null, canUseBasic: false, expiresAt: null })
    try {
      this.authenticating = true
      await this.deps.ensureSession()
      this.authenticating = false
      if (attempt !== this.epoch) return null
      const game = await this.deps.createGame(topic, cancellation)
      if (attempt !== this.epoch) return null
      this.update({ view: 'home' })
      return game
    } catch (cause) {
      if (attempt !== this.epoch) return null
      const error = cause instanceof ApiError ? cause : createNetworkError()
      this.permit = readPermit(error)
      this.update({ view: 'error', error: getGenerationErrorPresentation(error, topic),
        canUseBasic: Boolean(this.permit), expiresAt: this.permit ? Date.parse(this.permit.expires_at) : null })
      this.checkExpiry()
      return null
    } finally {
      if (attempt === this.epoch) { this.cancellation = null; this.authenticating = false }
    }
  }
  confirmBasic = async (): Promise<Game | null> => {
    this.checkExpiry()
    if (!this.permit || !['confirm', 'basic-error'].includes(this.snapshot.view)) return null
    const attempt = ++this.epoch
    const cancellation = new RequestCancellation()
    this.cancellation = cancellation
    const topic = this.snapshot.topic
    const body: BasicGameRequest = { topic, fallback_token: this.permit.token, acknowledge_unverified: true }
    this.update({ view: 'basic-loading' })
    try {
      const game = await this.deps.createBasicGame(body, cancellation)
      if (attempt !== this.epoch) return null
      this.clearPermit()
      this.update({ view: 'home', error: null, canUseBasic: false, expiresAt: null })
      return game
    } catch (cause) {
      if (attempt !== this.epoch) return null
      const error = cause instanceof ApiError ? cause : createNetworkError()
      const denied = error.code === 'BASIC_MODE_NOT_ALLOWED'
      const cannotRetry = denied || error.isNetworkError || error.status === 401
        || ['CONTENT_BLOCKED', 'VALIDATION_ERROR'].includes(error.code)
      if (cannotRetry) this.clearPermit()
      this.update({ view: denied ? 'expired' : this.permit ? 'basic-error' : 'error',
        error: getGenerationErrorPresentation(error, topic), canUseBasic: Boolean(this.permit),
        expiresAt: this.permit ? Date.parse(this.permit.expires_at) : null })
      this.checkExpiry()
      return null
    } finally {
      if (attempt === this.epoch) this.cancellation = null
    }
  }
}
