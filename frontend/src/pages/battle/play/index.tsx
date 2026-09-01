import { useEffect, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useLoad } from '@tarojs/taro'

import { AppShell } from '../../../components/AppShell'
import { StatusState } from '../../../components/StatusState'
import { battleApi } from '../../../services/battle'
import { ensureLogin } from '../../../services/auth'
import { ApiError } from '../../../services/request'
import { newRequestId } from '../../../utils/uuid'
import { useBattleStore } from '../../../stores/battle'
import { useSessionStore } from '../../../stores/session'
import type { BattleQuestion } from '../../../types/api'
import './index.scss'

type Feedback = 'correct' | 'wrong' | null

export default function BattlePlayPage() {
  const setRoom = useBattleStore((state) => state.setRoom)
  const vibration = useSessionStore((state) => state.settings.vibration_enabled)
  const roomIdRef = useRef('')
  const [question, setQuestion] = useState<BattleQuestion | null>(null)
  const [topic, setTopic] = useState('')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [pending, setPending] = useState(false)
  const [networkError, setNetworkError] = useState(false)
  const [conflict, setConflict] = useState(false)
  const attemptIdRef = useRef('')

  const vibrate = () => {
    if (vibration) Taro.vibrateShort({ type: 'light' }).catch(() => undefined)
  }

  const loadRoom = async () => {
    const roomId = roomIdRef.current
    if (!roomId) return
    try {
      await ensureLogin()
      const room = await battleApi.status(roomId)
      setRoom(room)
      setTopic(room.topic)
      if (room.status === 'finished' || room.status === 'void') {
        await Taro.redirectTo({ url: `/pages/battle/result/index?id=${roomId}` })
        return
      }
      if (room.question) {
        setQuestion(room.question)
        attemptIdRef.current = newRequestId()
      }
      setNetworkError(false)
    } catch {
      setNetworkError(true)
    }
  }

  useLoad((options) => {
    roomIdRef.current = options.id || ''
    loadRoom()
  })

  useEffect(() => {
    if (!conflict) return
    const timer = setTimeout(() => Taro.redirectTo({ url: `/pages/battle/result/index?id=${roomIdRef.current}` }), 600)
    return () => clearTimeout(timer)
  }, [conflict])

  const choose = async (option: number) => {
    if (!question || pending || feedback !== null) return
    setPending(true)
    setSelected(option)
    try {
      const response = await battleApi.answer(roomIdRef.current, option, attemptIdRef.current)
      setFeedback(response.result === 'wrong' ? 'wrong' : 'correct')
      vibrate()
      const advance = () => {
        if (response.result === 'completed' || !response.question) {
          Taro.redirectTo({ url: `/pages/battle/result/index?id=${roomIdRef.current}` }).catch(() => undefined)
          return
        }
        setQuestion(response.question)
        attemptIdRef.current = newRequestId()
        setFeedback(null)
        setSelected(null)
      }
      setTimeout(advance, 900)
    } catch (error) {
      const apiError = error as ApiError
      if (apiError.isNetworkError) {
        setNetworkError(true)
        setSelected(null)
      } else if (apiError.code === 'BATTLE_ALREADY_ANSWERED' || apiError.code === 'BATTLE_FINISHED') {
        setConflict(true)
      } else {
        Taro.showToast({ title: apiError.message, icon: 'none' })
        setSelected(null)
      }
    } finally {
      setPending(false)
    }
  }

  const quit = () => Taro.reLaunch({ url: '/pages/index/index' })

  if (networkError) {
    return (
      <AppShell title='对战答题' back onBack={quit} className='battle-play'>
        <StatusState
          tone='blue'
          icon='⌁'
          title='网络开小差了'
          copy='检查网络后再试，你的答案没有丢。'
          primaryText='↻ 重新连接'
          onPrimary={loadRoom}
          secondaryText='返回首页'
          onSecondary={quit}
        />
      </AppShell>
    )
  }

  if (conflict) {
    return (
      <AppShell title='对战答题' hideTabBar className='battle-play'>
        <StatusState
          tone='yellow'
          icon='✓'
          title='本场已结束'
          copy='正在带你去看结果...'
          primaryText='立即查看'
          onPrimary={() => Taro.redirectTo({ url: `/pages/battle/result/index?id=${roomIdRef.current}` })}
        />
      </AppShell>
    )
  }

  if (!question) {
    return <AppShell title='对战答题' back onBack={quit}><View className='spinner' /></AppShell>
  }

  return (
    <AppShell title={topic} hideTabBar className={`battle-play ${question.tier === 'boss' ? 'app-shell--boss' : ''}`}>
      <View className='game-hud'>
        <Text className='level-badge'>第 {question.position + 1} / 3 题</Text>
        <View className='progress'>
          <View className='progress__bar' style={{ width: `${(question.position / 3) * 100}%` }} />
        </View>
        <Text className='battle-clock'>计时中</Text>
      </View>
      <View className='bubble bubble--question'>
        <Text className='bubble__label'>{question.title}</Text>
        <Text>{question.intro}</Text>
      </View>
      <View className='bubble'>
        <Text className='bubble__label'>问题</Text>
        <Text>{question.question}</Text>
      </View>
      <View className='options'>
        {question.options.map((option) => (
          <View
            key={option.index}
            className={`option ${selected === option.index ? (feedback === 'correct' ? 'option--correct' : feedback === 'wrong' ? 'option--wrong' : '') : ''}`}
            onClick={() => choose(option.index)}
          >
            <Text className='option__key'>{option.key}</Text>
            <Text className='option__text'>{option.text}</Text>
            <Text className='option__state'>
              {selected === option.index && feedback === 'correct' ? '✓' : selected === option.index && feedback === 'wrong' ? '×' : ''}
            </Text>
          </View>
        ))}
      </View>
      <Text className='micro-copy battle-play__hint'>答对答错都会进入下一题，结果页看答案</Text>
    </AppShell>
  )
}
