import type {
  AnswerResponse,
  BasicGameRequest,
  Game,
  LoginResponse,
  ShareResponse,
  UserProfile,
  UserSettings,
} from '../types/api'
import { request } from './request'
import type { RequestCancellation } from './requestCancellation'

export const api = {
  login: (code: string) =>
    request<LoginResponse>('/auth/wechat', {
      method: 'POST',
      data: { code },
      authenticated: false,
    }),
  createGame: (topic: string, cancellation?: RequestCancellation) =>
    request<Game>('/games', { method: 'POST', data: { topic }, timeout: 90000, ...(cancellation ? { cancellation } : {}) }),
  createBasicGame: (data: BasicGameRequest, cancellation?: RequestCancellation) =>
    request<Game>('/games/basic', {
      method: 'POST', data, timeout: 90000, retryAuthentication: false,
      ...(cancellation ? { cancellation } : {}),
    }),
  getGame: (gameId: string) => request<Game>(`/games/${gameId}`),
  answer: (gameId: string, option: number, attemptId: string) =>
    request<AnswerResponse>(`/games/${gameId}/answers`, {
      method: 'POST',
      data: { option, attempt_id: attemptId },
    }),
  reviveWithAd: (gameId: string, eventId: string, completed: boolean) =>
    request<Game>(`/games/${gameId}/revives/ad`, {
      method: 'POST',
      data: { event_id: eventId, completed },
    }),
  createShare: (gameId: string) =>
    request<ShareResponse>(`/games/${gameId}/share`, { method: 'POST' }),
  assist: (token: string) =>
    request<Game>(`/assists/${encodeURIComponent(token)}`, { method: 'POST' }),
  profile: () => request<UserProfile>('/me'),
  updateSettings: (settings: Partial<UserSettings>) =>
    request<UserSettings>('/me/settings', { method: 'PATCH', data: settings }),
}
