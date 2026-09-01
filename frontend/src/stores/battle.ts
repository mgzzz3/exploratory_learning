import { useSyncExternalStore } from 'react'
import { createStore } from 'zustand/vanilla'

import type { BattleResult, BattleRoom } from '../types/api'

interface BattleStore {
  currentRoomId: string | null
  room: BattleRoom | null
  result: BattleResult | null
  setRoom: (room: BattleRoom) => void
  setResult: (result: BattleResult) => void
  clear: () => void
}

const battleStore = createStore<BattleStore>()((set) => ({
  currentRoomId: null,
  room: null,
  result: null,
  setRoom: (room) => set({ room, currentRoomId: room.id }),
  setResult: (result) => set({ result }),
  clear: () => set({ room: null, result: null, currentRoomId: null }),
}))

export const useBattleStore = Object.assign(
  <Selected>(selector: (state: BattleStore) => Selected): Selected =>
    useSyncExternalStore(
      battleStore.subscribe,
      () => selector(battleStore.getState()),
      () => selector(battleStore.getInitialState()),
    ),
  battleStore,
)
