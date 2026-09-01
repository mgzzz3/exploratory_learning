import { useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useLoad } from '@tarojs/taro'

import { AppShell } from '../../../components/AppShell'
import { StatusState } from '../../../components/StatusState'
import { battleApi } from '../../../services/battle'
import { ensureLogin } from '../../../services/auth'
import { useBattleStore } from '../../../stores/battle'
import './index.scss'

interface JoinFailure {
  title: string
  copy: string
}

const FAILURE_COPY: Record<string, JoinFailure> = {
  BATTLE_FULL: { title: '房间已满', copy: '这场对战已经有两位玩家了。\n等下一局再约吧！' },
  BATTLE_EXPIRED: { title: '邀请已过期', copy: '这场对战超过 3 分钟没有开始。\n让房主重新发起一个。' },
  BATTLE_NOT_JOINABLE: { title: '现在进不去', copy: '这场对战不能加入，可能已经结束。' },
  BATTLE_NOT_FOUND: { title: '对战不存在', copy: '邀请卡片可能已失效，让房主重新分享。' },
}

export default function BattleJoinPage() {
  const setRoom = useBattleStore((state) => state.setRoom)
  const [failure, setFailure] = useState<JoinFailure | null>(null)
  const [joining, setJoining] = useState(true)

  const backHome = () => Taro.reLaunch({ url: '/pages/index/index' })

  useLoad(async (options) => {
    const roomId = options.id || ''
    if (!roomId) {
      setFailure({ title: '缺少对战信息', copy: '邀请卡片不完整，请让房主重新分享。' })
      setJoining(false)
      return
    }
    try {
      await ensureLogin()
      const room = await battleApi.join(roomId)
      setRoom(room)
      setJoining(false)
      await Taro.redirectTo({ url: `/pages/battle/room/index?id=${room.id}` })
    } catch (error) {
      const code = (error as { code?: string }).code || ''
      setFailure(FAILURE_COPY[code] || { title: '加入失败', copy: (error as Error).message })
      setJoining(false)
    }
  })

  if (joining) {
    return (
      <AppShell title='加入对战' back onBack={backHome} className='battle-join'>
        <View className='spinner' />
        <Text className='micro-copy'>正在进入对战房间...</Text>
      </AppShell>
    )
  }

  return (
    <AppShell title='加入对战' back onBack={backHome} className='battle-join'>
      {failure && (
        <StatusState
          tone='yellow'
          icon='!'
          title={failure.title}
          copy={failure.copy}
          primaryText='回到首页'
          onPrimary={backHome}
        />
      )}
    </AppShell>
  )
}
