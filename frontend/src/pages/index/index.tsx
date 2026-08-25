import { useEffect, useState } from 'react'
import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'

import { AppShell } from '../../components/AppShell'
import { Mascot } from '../../components/Mascot'
import { PrimaryButton } from '../../components/ActionButton'
import { StatusState } from '../../components/StatusState'
import { api } from '../../services/api'
import { ensureLogin } from '../../services/auth'
import { ApiError } from '../../services/request'
import { useSessionStore } from '../../stores/session'
import './index.scss'

const SUGGESTIONS = ['Python 基础', '高情商聊天', '咖啡拉花', '理财小白']
type HomeState = 'home' | 'loading' | 'blocked' | 'generation-error' | 'network-error'

export default function Index() {
  const lastTopic = useSessionStore((state) => state.lastTopic)
  const currentGameId = useSessionStore((state) => state.currentGameId)
  const setLastTopic = useSessionStore((state) => state.setLastTopic)
  const setCurrentGame = useSessionStore((state) => state.setCurrentGame)
  const [topic, setTopic] = useState(lastTopic)
  const [view, setView] = useState<HomeState>('home')
  const [progress, setProgress] = useState(18)

  useDidShow(() => {
    ensureLogin().catch(() => setView('network-error'))
    if (currentGameId) {
      Taro.navigateTo({ url: `/pages/game/index?id=${currentGameId}` }).catch(() => undefined)
    }
  })

  useEffect(() => {
    if (view !== 'loading') return
    const timer = setInterval(() => {
      setProgress((value) => Math.min(91, value + Math.ceil((92 - value) / 5)))
    }, 450)
    return () => clearInterval(timer)
  }, [view])

  const generate = async () => {
    const cleaned = topic.trim()
    if (!cleaned) {
      Taro.showToast({ title: '先扔进来一个学习主题', icon: 'none' })
      return
    }
    setTopic(cleaned)
    setLastTopic(cleaned)
    setProgress(18)
    setView('loading')
    try {
      await ensureLogin()
      const game = await api.createGame(cleaned)
      setCurrentGame(game.id)
      setProgress(100)
      await Taro.navigateTo({ url: `/pages/game/index?id=${game.id}` })
      setView('home')
    } catch (error) {
      const apiError = error as ApiError
      if (apiError.code === 'CONTENT_BLOCKED') setView('blocked')
      else if (apiError.code === 'AI_GENERATION_FAILED') setView('generation-error')
      else setView('network-error')
    }
  }

  if (view === 'loading') {
    return (
      <AppShell title='正在筑界' back onBack={() => setView('home')}>
        <View className='loading-stage'>
          <View>
            <View className='loading-doodle'><View className='loading-book' /><View className='loading-pencil' /></View>
            <Text className='loading-copy-title'>正在把 {topic}{'\n'}讲成人话……</Text>
            <Text className='loading-copy-subtitle'>搭关卡 · 挑比喻 · 藏 Boss</Text>
          </View>
        </View>
        <View className='progress progress--large'><View className='progress__bar' style={{ width: `${progress}%` }} /></View>
        <Text className='micro-copy'>偷看一句：每个概念，都能找到一个生活里的比喻。</Text>
      </AppShell>
    )
  }

  if (view === 'blocked') {
    return (
      <AppShell title='AI 万物学堂'>
        <StatusState
          tone='red'
          icon='⌾'
          title='这个主题不能开局'
          copy={'换个健康、具体的学习主题再试试。\n例如：怎么做好时间管理'}
          primaryText='重新检查'
          onPrimary={generate}
          input={{ value: topic, placeholder: '输入新的学习主题', onInput: setTopic }}
        />
      </AppShell>
    )
  }

  if (view === 'generation-error') {
    return (
      <AppShell title='生成失败' back onBack={() => setView('home')}>
        <StatusState
          icon='!'
          title='这次没搭好关卡'
          copy={`AI 返回的题目格式不完整。\n“${topic}”已经替你保留。`}
          primaryText='↻ 重新生成'
          onPrimary={generate}
          secondaryText='修改学习主题'
          onSecondary={() => setView('home')}
        />
      </AppShell>
    )
  }

  if (view === 'network-error') {
    return (
      <AppShell title='连接中断' back onBack={() => setView('home')}>
        <StatusState
          tone='blue'
          icon='⌁'
          title='网络开小差了'
          copy={'检查 Wi-Fi 或移动网络后再试。\n当前闯关进度不会丢失。'}
          primaryText='↻ 重新连接'
          onPrimary={generate}
          secondaryText='返回首页'
          onSecondary={() => setView('home')}
        />
      </AppShell>
    )
  }

  const hasTopic = Boolean(topic.trim())
  return (
    <AppShell>
      <Text className='brand-sticker'>AI 万物学堂</Text>
      <View className='home-hero'>
        <Mascot />
        <Text className='hero-title'>{hasTopic ? '这题，我来出！' : '不会？扔进来！'}</Text>
        <Text className='hero-subtitle'>
          {hasTopic ? `三道题，把 ${topic.trim()} 讲明白` : '今天想轻松学点什么？'}
        </Text>
      </View>
      <Input
        className='topic-field'
        value={topic}
        maxlength={80}
        placeholder='比如：Python 基础'
        confirmType='go'
        onInput={(event) => setTopic(event.detail.value)}
        onConfirm={generate}
      />
      <View className='chips'>
        {SUGGESTIONS.map((item) => (
          <Button className='chip' key={item} onClick={() => setTopic(item)}>{item}</Button>
        ))}
      </View>
      <PrimaryButton onClick={generate}>
        {hasTopic ? '生成我的闯关' : '开一局 · 3 关学明白'}
      </PrimaryButton>
      <Text className='micro-copy'>{hasTopic ? '预计 5～10 秒完成' : 'AI 生成题目，随时可以退出'}</Text>
    </AppShell>
  )
}
