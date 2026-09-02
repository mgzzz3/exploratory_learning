import Taro from '@tarojs/taro'
import { useSyncExternalStore } from 'react'
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware'
import { createStore } from 'zustand/vanilla'

import type { AuthUser, ShareResponse, UserSettings } from '../types/api'

const taroStorage: StateStorage = {
  getItem: (name) => Taro.getStorageSync<string>(name) || null,
  setItem: (name, value) => Taro.setStorageSync(name, value),
  removeItem: (name) => Taro.removeStorageSync(name),
}

interface SessionStore {
  accessToken: string | null
  user: AuthUser | null
  currentGameId: string | null
  lastTopic: string
  settings: UserSettings
  share: ShareResponse | null
  setSession: (accessToken: string, user: AuthUser) => void
  clearSession: () => void
  setCurrentGame: (gameId: string | null) => void
  setLastTopic: (topic: string) => void
  setSettings: (settings: UserSettings) => void
  setShare: (share: ShareResponse | null) => void
}

const sessionStore = createStore<SessionStore>()(
  persist(
    (set) => ({
      accessToken: null,
      user: null,
      currentGameId: null,
      lastTopic: '',
      settings: { sound_enabled: true, vibration_enabled: true, web_search_enabled: true },
      share: null,
      setSession: (accessToken, user) => set({ accessToken, user }),
      clearSession: () => set({ accessToken: null, user: null }),
      setCurrentGame: (currentGameId) => set({ currentGameId }),
      setLastTopic: (lastTopic) => set({ lastTopic }),
      setSettings: (settings) => set({ settings }),
      setShare: (share) => set({ share }),
    }),
    {
      name: 'ai-school-session-v1',
      storage: createJSONStorage(() => taroStorage),
      partialize: (state) => ({
        accessToken: state.accessToken,
        user: state.user,
        currentGameId: state.currentGameId,
        lastTopic: state.lastTopic,
        settings: state.settings,
      }),
    },
  ),
)

export const useSessionStore = Object.assign(
  <Selected>(selector: (state: SessionStore) => Selected): Selected =>
    useSyncExternalStore(
      sessionStore.subscribe,
      () => selector(sessionStore.getState()),
      () => selector(sessionStore.getInitialState()),
    ),
  sessionStore,
)
