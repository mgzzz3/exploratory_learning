import { describe, expect, it } from 'vitest'

import { useBattleStore } from '../battle'
import type { BattleResult, BattleRoom } from '../../types/api'

const room: BattleRoom = {
  id: 'room-fixture',
  topic: 'Python 基础',
  status: 'waiting',
  error_message: null,
  started_at: null,
  expires_at: '2026-09-01T00:03:00Z',
  me: { role: 'host', status: 'joined', nickname: '房主', correct_count: 0, total_seconds: null, result: null },
  opponent: null,
  question: null,
}

const result: BattleResult = {
  room_id: 'room-fixture',
  topic: 'Python 基础',
  status: 'finished',
  my_result: 'win',
  opponent_result: 'lose',
  my_correct_count: 3,
  opponent_correct_count: 2,
  my_total_seconds: 30,
  opponent_total_seconds: 45,
  review: [],
}

describe('battle store', () => {
  it('setRoom 同步缓存房间并记录当前房间 ID', () => {
    useBattleStore.getState().clear()
    useBattleStore.getState().setRoom(room)

    expect(useBattleStore.getState().room?.id).toBe('room-fixture')
    expect(useBattleStore.getState().currentRoomId).toBe('room-fixture')
  })

  it('setResult 缓存结算结果，clear 一次性清空对战态', () => {
    useBattleStore.getState().setRoom(room)
    useBattleStore.getState().setResult(result)

    expect(useBattleStore.getState().result?.my_result).toBe('win')

    useBattleStore.getState().clear()

    expect(useBattleStore.getState().room).toBeNull()
    expect(useBattleStore.getState().result).toBeNull()
    expect(useBattleStore.getState().currentRoomId).toBeNull()
  })
})
