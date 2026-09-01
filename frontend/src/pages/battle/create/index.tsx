import { useState } from 'react'
import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { AppShell } from '../../../components/AppShell'
import { Mascot } from '../../../components/Mascot'
import { PrimaryButton } from '../../../components/ActionButton'
import { battleApi } from '../../../services/battle'
import { ensureLogin } from '../../../services/auth'
import { validateLearningInput } from '../../../services/gameCreation'
import { useBattleStore } from '../../../stores/battle'
import './index.scss'

const SUGGESTIONS = ['Python 基础', '咖啡拉花', '高情商聊天', '理财小白']

export default function BattleCreatePage() {
  const setRoom = useBattleStore((state) => state.setRoom)
  const [topic, setTopic] = useState('')
  const [pending, setPending] = useState(false)

  const create = async () => {
    const validationMessage = validateLearningInput(topic)
    if (validationMessage) {
      Taro.showToast({ title: validationMessage, icon: 'none' })
      return
    }
    if (pending) return
    setPending(true)
    try {
      await ensureLogin()
      const room = await battleApi.create(topic.trim())
      setRoom(room)
      await Taro.navigateTo({ url: `/pages/battle/room/index?id=${room.id}` })
    } catch (error) {
      Taro.showToast({ title: (error as Error).message, icon: 'none' })
    } finally {
      setPending(false)
    }
  }

  return (
    <AppShell title='发起对战' back onBack={() => Taro.navigateBack()} className='battle-create'>
      <View className='home-hero'>
        <Mascot small />
        <Text className='hero-title'>拉个朋友，比一比！</Text>
        <Text className='hero-subtitle'>你出关键词，两人答同一套题</Text>
      </View>
      <Text className='field-label'>对战关键词</Text>
      <View className='input-shell'>
        <Textarea
          className='topic-field topic-field--textarea'
          value={topic}
          maxlength={80}
          disableDefaultPadding
          placeholder='比如：Python 基础'
          onInput={(event) => setTopic(event.detail.value)}
        />
      </View>
      <View className='chips'>
        {SUGGESTIONS.map((item) => (
          <Button className='chip' key={item} onClick={() => setTopic(item)}>{item}</Button>
        ))}
      </View>
      <PrimaryButton onClick={create} disabled={pending}>
        {pending ? '正在出题...' : '发起好友对战'}
      </PrimaryButton>
      <Text className='micro-copy'>发起后马上可以分享邀请，题目在后台准备</Text>
    </AppShell>
  )
}
