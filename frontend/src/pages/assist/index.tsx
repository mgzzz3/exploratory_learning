import { useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useLoad } from '@tarojs/taro'

import { AppShell } from '../../components/AppShell'
import { Mascot } from '../../components/Mascot'
import { PrimaryButton } from '../../components/ActionButton'
import { StatusState } from '../../components/StatusState'
import { api } from '../../services/api'
import { ensureLogin } from '../../services/auth'
import { ApiError } from '../../services/request'
import './index.scss'

type AssistState = 'ready' | 'loading' | 'success' | 'error'

export default function AssistPage() {
  const [token, setToken] = useState('')
  const [state, setState] = useState<AssistState>('ready')
  const [error, setError] = useState('这张助力卡暂时不能使用')

  useLoad((options) => {
    setToken(options.token || '')
  })

  const assist = async () => {
    if (!token) {
      setError('助力链接不完整，请让好友重新分享')
      setState('error')
      return
    }
    setState('loading')
    try {
      await ensureLogin()
      await api.assist(token)
      setState('success')
    } catch (caught) {
      const value = caught as ApiError
      const messages: Record<string, string> = {
        SELF_ASSIST_NOT_ALLOWED: '自己的脑细胞，得请另一位好友来救',
        ASSIST_ALREADY_USED: '这张助力卡已经帮好友恢复过啦',
        ASSIST_EXPIRED: '这张助力卡已经过期，请好友重新分享',
      }
      setError(messages[value.code] || value.message)
      setState('error')
    }
  }

  if (state === 'success') {
    return (
      <AppShell title='好友助力'>
        <View className='success-burst'><Text className='stamp'>助力成功！</Text></View>
        <Text className='bubble'><Text className='bubble__label'>小万老师</Text>好友已经恢复 3 颗心，可以回去继续闯关啦。</Text>
        <PrimaryButton className='action-gap' onClick={() => Taro.reLaunch({ url: '/pages/index/index' })}>我也去学一个主题</PrimaryButton>
      </AppShell>
    )
  }

  if (state === 'error') {
    return (
      <AppShell title='好友助力'>
        <StatusState
          tone='blue'
          icon='!'
          title='这次没帮上忙'
          copy={error}
          primaryText='去 AI 万物学堂看看'
          onPrimary={() => Taro.reLaunch({ url: '/pages/index/index' })}
        />
      </AppShell>
    )
  }

  return (
    <AppShell title='好友助力'>
      <View className='share-card assist-card'>
        <View className='share-card__top'><Mascot small /><View><Text className='share-card__title'>好友的脑细胞等你救场</Text><Text className='share-card__copy'>点一下，就能帮 TA 恢复 3 颗心。</Text></View></View>
      </View>
      <PrimaryButton disabled={state === 'loading'} onClick={assist}>
        {state === 'loading' ? '正在助力……' : '帮 TA 满血复活'}
      </PrimaryButton>
      <Text className='micro-copy'>每张助力卡只能成功使用一次</Text>
    </AppShell>
  )
}
