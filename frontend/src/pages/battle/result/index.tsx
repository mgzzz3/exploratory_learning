import { useCallback, useEffect, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useLoad } from '@tarojs/taro'

import { AppShell } from '../../../components/AppShell'
import { PrimaryButton } from '../../../components/ActionButton'
import { StatusState } from '../../../components/StatusState'
import { battleApi } from '../../../services/battle'
import { ensureLogin } from '../../../services/auth'
import { useBattleStore } from '../../../stores/battle'
import type { BattleResult, BattleRoom } from '../../../types/api'
import './index.scss'

const RESULT_COPY = {
  win: { stamp: 'WIN', title: '你赢了！' },
  lose: { stamp: 'LOSE', title: '惜败一局' },
  draw: { stamp: 'DRAW', title: '平分秋色' },
} as const

function elapsed(seconds: number | null): string {
  const value = seconds || 1
  return `${Math.floor(value / 60)} 分 ${String(value % 60).padStart(2, '0')} 秒`
}

export default function BattleResultPage() {
  const setRoom = useBattleStore((state) => state.setRoom)
  const setResult = useBattleStore((state) => state.setResult)
  const [room, setLocalRoom] = useState<BattleRoom | null>(null)
  const [result, setLocalResult] = useState<BattleResult | null>(null)
  const [networkError, setNetworkError] = useState(false)
  const roomIdRef = useRef('')

  const refresh = useCallback(async () => {
    const roomId = roomIdRef.current
    if (!roomId) return
    try {
      await ensureLogin()
      const latestRoom = await battleApi.status(roomId)
      setLocalRoom(latestRoom)
      setRoom(latestRoom)
      if (latestRoom.status === 'finished') {
        const detail = await battleApi.result(roomId)
        setLocalResult(detail)
        setResult(detail)
      }
      setNetworkError(false)
    } catch {
      setNetworkError(true)
    }
  }, [setRoom, setResult])

  useLoad((options) => {
    roomIdRef.current = options.id || ''
    refresh()
  })

  useEffect(() => {
    if (!room || room.status === 'finished' || room.status === 'void') return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [room, refresh])

  const backHome = () => Taro.reLaunch({ url: '/pages/index/index' })

  if (networkError && !room) {
    return (
      <AppShell title='对战结果' back onBack={backHome} className='battle-result'>
        <StatusState
          tone='blue'
          icon='⌁'
          title='网络开小差了'
          copy='结果已经保存在服务端，重新连接即可查看。'
          primaryText='↻ 重新连接'
          onPrimary={refresh}
          secondaryText='返回首页'
          onSecondary={backHome}
        />
      </AppShell>
    )
  }

  if (!room) {
    return <AppShell title='对战结果' back onBack={backHome}><View className='spinner' /></AppShell>
  }

  if (room.status === 'void') {
    return (
      <AppShell title='对战过期' back onBack={backHome} className='battle-result'>
        <StatusState
          tone='yellow'
          icon='!'
          title='对战超时作废'
          copy='3 分钟内没有分出胜负，本场不记输赢。'
          primaryText='回到首页'
          onPrimary={backHome}
        />
      </AppShell>
    )
  }

  if (!result) {
    return (
      <AppShell title='对战结果' hideTabBar className='battle-result'>
        <View className='battle-waiting'>
          <View className='spinner' />
          <Text className='state-title'>你已答完，等对方交卷</Text>
          <Text className='micro-copy'>对方完成或 3 分钟到，这里会自动出结果</Text>
        </View>
      </AppShell>
    )
  }

  const outcome = result.my_result || 'draw'
  const copy = RESULT_COPY[outcome]

  return (
    <AppShell title='对战结果' back onBack={backHome} className='battle-result'>
      <View className='completion-hero'>
        <Text className='stamp'>{copy.stamp}</Text>
        <Text className='completion-title'>{copy.title}</Text>
        <Text className='hero-subtitle'>{result.topic}</Text>
      </View>
      <View className='completion-sheet'>
        <Text className='completion-sheet__line'>我：答对 {result.my_correct_count} / 3 · 用时 {elapsed(result.my_total_seconds)}</Text>
        <Text className='completion-sheet__line'>
          对手：答对 {result.opponent_correct_count ?? '-'} / 3
          {result.opponent_total_seconds !== null ? ` · 用时 ${elapsed(result.opponent_total_seconds)}` : ''}
        </Text>
      </View>
      {result.review.map((item) => (
        <View className='battle-review' key={item.position}>
          <Text className='battle-review__title'>{item.position + 1}. {item.title}</Text>
          <Text className='battle-review__question'>{item.question}</Text>
          <View className='battle-review__options'>
            {item.options.map((option) => (
              <Text
                key={option.index}
                className={`battle-review__option ${option.index === item.correct_option ? 'battle-review__option--correct' : ''} ${option.index === item.selected_option && !item.is_correct ? 'battle-review__option--wrong' : ''}`}
              >
                {option.key}. {option.text}
                {option.index === item.correct_option ? ' ← 正确答案' : option.index === item.selected_option ? ' ← 你的选择' : ''}
              </Text>
            ))}
          </View>
          {!item.is_correct && <Text className='battle-review__explanation'>{item.explanation}</Text>}
        </View>
      ))}
      <PrimaryButton onClick={backHome}>回到首页</PrimaryButton>
    </AppShell>
  )
}
