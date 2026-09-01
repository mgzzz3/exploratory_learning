import { useCallback, useEffect, useRef, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useLoad, useShareAppMessage } from '@tarojs/taro'

import { AppShell } from '../../../components/AppShell'
import { PrimaryButton, SecondaryButton } from '../../../components/ActionButton'
import { StatusState } from '../../../components/StatusState'
import { battleApi } from '../../../services/battle'
import { ensureLogin } from '../../../services/auth'
import { useBattleStore } from '../../../stores/battle'
import type { BattleRoom } from '../../../types/api'
import './index.scss'

type ViewMode = 'loading' | 'countdown' | 'failed'

export default function BattleRoomPage() {
  const setRoom = useBattleStore((state) => state.setRoom)
  const [room, setLocalRoom] = useState<BattleRoom | null>(null)
  const [mode, setMode] = useState<ViewMode>('loading')
  const [count, setCount] = useState(3)
  const [pending, setPending] = useState(false)
  const [networkError, setNetworkError] = useState(false)
  const roomIdRef = useRef('')
  const countdownRef = useRef(false)

  const applyRoom = useCallback((next: BattleRoom) => {
    setLocalRoom(next)
    setRoom(next)
  }, [setRoom])

  const loadRoom = useCallback(async () => {
    const roomId = roomIdRef.current
    if (!roomId) return
    try {
      await ensureLogin()
      applyRoom(await battleApi.status(roomId))
      setNetworkError(false)
    } catch {
      setNetworkError(true)
    }
  }, [applyRoom])

  useLoad((options) => {
    roomIdRef.current = options.id || ''
    loadRoom()
  })

  useShareAppMessage(() => ({
    title: room ? `来跟我对战「${room.topic}」！三道题见分晓` : '来跟我对战！三道题见分晓',
    path: roomIdRef.current ? `/pages/battle/join/index?id=${roomIdRef.current}` : '/pages/index/index',
  }))

  useEffect(() => {
    if (!room || countdownRef.current) return
    if (room.status === 'playing' && room.me.status === 'playing') {
      countdownRef.current = true
      setMode('countdown')
      return
    }
    if (room.status === 'playing' && room.me.status === 'finished') {
      Taro.redirectTo({ url: `/pages/battle/result/index?id=${room.id}` }).catch(() => undefined)
    }
  }, [room])

  useEffect(() => {
    if (mode !== 'countdown') return
    if (count === 0) {
      Taro.redirectTo({ url: `/pages/battle/play/index?id=${roomIdRef.current}` }).catch(() => undefined)
      return
    }
    const timer = setTimeout(() => setCount((value) => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [mode, count])

  useEffect(() => {
    if (!room || mode === 'countdown') return
    if (!['generating', 'waiting', 'playing'].includes(room.status)) return
    const timer = setInterval(loadRoom, 3000)
    return () => clearInterval(timer)
  }, [room, mode, loadRoom])

  const markReady = async () => {
    if (!room || pending) return
    setPending(true)
    try {
      applyRoom(await battleApi.ready(room.id))
    } catch (error) {
      Taro.showToast({ title: (error as Error).message, icon: 'none' })
    } finally {
      setPending(false)
    }
  }

  const quit = () => Taro.reLaunch({ url: '/pages/index/index' })

  if (networkError && !room) {
    return (
      <AppShell title='对战房间' back onBack={quit} className='battle-room'>
        <StatusState
          tone='blue'
          icon='⌁'
          title='网络开小差了'
          copy='检查网络后再试，房间还在等你。'
          primaryText='↻ 重新连接'
          onPrimary={loadRoom}
          secondaryText='返回首页'
          onSecondary={quit}
        />
      </AppShell>
    )
  }

  if (!room) {
    return <AppShell title='对战房间' back onBack={quit}><View className='spinner' /></AppShell>
  }

  if (mode === 'countdown') {
    return (
      <AppShell title='准备开战' hideTabBar className='battle-room battle-room--countdown'>
        <View className='countdown-stage'>
          <Text className='countdown-number'>{count === 0 ? '开战！' : count}</Text>
          <Text className='micro-copy'>统一起点已由服务端记录</Text>
        </View>
      </AppShell>
    )
  }

  if (room.status === 'error') {
    return (
      <AppShell title='出题失败' back onBack={quit} className='battle-room'>
        <StatusState
          tone='red'
          icon='!'
          title='对战题目没能生成'
          copy={`${room.error_message || '生成失败，请重新发起'}\n这场对战没有开始，也不会记胜负。`}
          primaryText='重新发起'
          onPrimary={quit}
        />
      </AppShell>
    )
  }

  if (room.status === 'void') {
    return (
      <AppShell title='对战过期' back onBack={quit} className='battle-room'>
        <StatusState
          tone='yellow'
          icon='!'
          title='邀请超时了'
          copy='题目就绪 3 分钟内没有好友加入。\n回到首页重新发起一场吧。'
          primaryText='回到首页'
          onPrimary={quit}
        />
      </AppShell>
    )
  }

  const generating = room.status === 'generating'
  const iAmReady = room.me.status !== 'joined'
  const bothReady = room.status === 'playing'

  return (
    <AppShell title='对战房间' back onBack={quit} className='battle-room'>
      <View className='share-card'>
        <Text className='share-card__title'>对战主题：{room.topic}</Text>
        <Text className='share-card__copy'>
          {generating ? '题目正在后台准备...' : '题目已就绪，等双方就绪立刻开战'}
        </Text>
        <View className='battle-ready-list'>
          <Text className='completion-sheet__line'>
            {room.me.nickname}（我）：{generating ? '等待出题' : iAmReady ? '已就绪 ✓' : '待就绪'}
          </Text>
          <Text className='completion-sheet__line'>
            {room.opponent
              ? `${room.opponent.nickname}：${room.opponent.status === 'joined' ? '待就绪' : '已就绪 ✓'}`
              : '等待好友加入...'}
          </Text>
        </View>
      </View>
      {generating ? (
        <View className='spinner battle-room__spinner' />
      ) : (
        <>
          <PrimaryButton onClick={markReady} disabled={pending || iAmReady || bothReady}>
            {bothReady ? '开战中...' : iAmReady ? '已就绪，等对方' : '我准备好了'}
          </PrimaryButton>
          {room.me.role === 'host' && !room.opponent && (
            <SecondaryButton className='action-gap' openType='share'>
              ↗ 邀请好友对战
            </SecondaryButton>
          )}
        </>
      )}
      <Text className='micro-copy'>就绪后统一倒计时开战，答题快慢也算分</Text>
    </AppShell>
  )
}
