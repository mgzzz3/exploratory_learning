import type {
  BattleAnswerResponse,
  BattleResult,
  BattleRoom,
} from '../types/api'
import { request } from './request'

export const battleApi = {
  create: (topic: string) =>
    request<BattleRoom>('/battles', {
      method: 'POST',
      data: { topic },
      timeout: 90000,
    }),
  join: (roomId: string) =>
    request<BattleRoom>(`/battles/${roomId}/join`, { method: 'POST' }),
  ready: (roomId: string) =>
    request<BattleRoom>(`/battles/${roomId}/ready`, { method: 'POST' }),
  status: (roomId: string) => request<BattleRoom>(`/battles/${roomId}`),
  answer: (roomId: string, option: number, attemptId: string) =>
    request<BattleAnswerResponse>(`/battles/${roomId}/answers`, {
      method: 'POST',
      data: { option, attempt_id: attemptId },
    }),
  result: (roomId: string) =>
    request<BattleResult>(`/battles/${roomId}/result`),
}
