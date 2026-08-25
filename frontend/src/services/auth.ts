import Taro from '@tarojs/taro'

import { useSessionStore } from '../stores/session'
import { api } from './api'

export async function ensureLogin(): Promise<string> {
  const existing = useSessionStore.getState().accessToken
  if (existing) return existing

  const code = process.env.TARO_ENV === 'weapp'
    ? (await Taro.login()).code
    : 'h5-local-preview'
  const login = await api.login(code)
  useSessionStore.getState().setSession(login.access_token, login.user)
  return login.access_token
}
