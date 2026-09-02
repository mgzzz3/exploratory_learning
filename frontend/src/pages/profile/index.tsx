import { useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'

import { AppShell } from '../../components/AppShell'
import { api } from '../../services/api'
import { ensureLogin } from '../../services/auth'
import { useSessionStore } from '../../stores/session'
import type { UserProfile, UserSettings } from '../../types/api'
import './index.scss'

const settingRows = [
  { icon: '◷', label: '每日学习提醒', value: '未设置　›' },
  { icon: '◇', label: '内容与隐私', value: '›' },
  { icon: 'i', label: '关于 AI 万物学堂', value: 'v0.1　›' },
]

export default function ProfilePage() {
  const storedUser = useSessionStore((state) => state.user)
  const storedSettings = useSessionStore((state) => state.settings)
  const setStoredSettings = useSessionStore((state) => state.setSettings)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [settings, setSettings] = useState<UserSettings>(storedSettings)

  const load = async () => {
    try {
      await ensureLogin()
      const value = await api.profile()
      setProfile(value)
      const next = {
        sound_enabled: value.sound_enabled,
        vibration_enabled: value.vibration_enabled,
        web_search_enabled: value.web_search_enabled,
      }
      setSettings(next)
      setStoredSettings(next)
    } catch {
      Taro.showToast({ title: '个人数据暂时没有加载出来', icon: 'none' })
    }
  }

  useDidShow(() => { load() })

  const toggle = async (key: keyof UserSettings) => {
    const previous = settings
    const next = { ...settings, [key]: !settings[key] }
    setSettings(next)
    setStoredSettings(next)
    try {
      const saved = await api.updateSettings({ [key]: next[key] })
      setSettings(saved)
      setStoredSettings(saved)
    } catch {
      setSettings(previous)
      setStoredSettings(previous)
      Taro.showToast({ title: '设置没有保存，请重试', icon: 'none' })
    }
  }

  const name = profile?.nickname || storedUser?.nickname || '好学的小万'
  return (
    <AppShell title='我的' activeTab='profile' className='profile-screen'>
      <View className='profile'>
        <Text className='profile__avatar'>{name.slice(-1)}</Text>
        <View><Text className='profile__name'>{name}</Text><Text className='profile__copy'>今天也要轻松学一点</Text></View>
      </View>
      <View className='stats'>
        <View className='stat'><Text className='stat__value'>{profile?.completed_games || 0} 局</Text><Text className='stat__label'>已经通关</Text></View>
        <View className='stat'><Text className='stat__value'>{profile?.learned_points || 0} 个</Text><Text className='stat__label'>学会知识点</Text></View>
      </View>
      <Text className='setting-title'>学习设置</Text>
      <View className='settings'>
        <Button className='setting-row' onClick={() => toggle('web_search_enabled')}>
          <View className='setting-row__main'><Text className='setting-row__icon'>◎</Text><Text>联网搜索出题</Text></View>
          <View className={`switch ${settings.web_search_enabled ? 'switch--on' : ''}`} />
        </Button>
        <Button className='setting-row' onClick={() => toggle('sound_enabled')}>
          <View className='setting-row__main'><Text className='setting-row__icon'>♪</Text><Text>学习音效</Text></View>
          <View className={`switch ${settings.sound_enabled ? 'switch--on' : ''}`} />
        </Button>
        <Button className='setting-row' onClick={() => toggle('vibration_enabled')}>
          <View className='setting-row__main'><Text className='setting-row__icon'>≋</Text><Text>振动反馈</Text></View>
          <View className={`switch ${settings.vibration_enabled ? 'switch--on' : ''}`} />
        </Button>
        {settingRows.map((row) => (
          <Button className='setting-row' key={row.label} onClick={() => Taro.showToast({ title: 'MVP 暂未开放', icon: 'none' })}>
            <View className='setting-row__main'><Text className='setting-row__icon'>{row.icon}</Text><Text>{row.label}</Text></View>
            <Text className='setting-value'>{row.value}</Text>
          </Button>
        ))}
      </View>
    </AppShell>
  )
}
