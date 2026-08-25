import { Text, View } from '@tarojs/components'
import Taro, { useShareAppMessage } from '@tarojs/taro'

import { AppShell } from '../../components/AppShell'
import { Mascot } from '../../components/Mascot'
import { PrimaryButton, SecondaryButton } from '../../components/ActionButton'
import { useSessionStore } from '../../stores/session'
import './index.scss'

export default function SharePage() {
  const share = useSessionStore((state) => state.share)
  const topic = useSessionStore((state) => state.lastTopic) || '一个新主题'

  useShareAppMessage(() => ({
    title: `救救我的脑细胞！我在学${topic}`,
    path: share?.path || '/pages/index/index',
  }))

  const back = () => Taro.navigateBack()

  return (
    <AppShell title='呼叫朋友' back onBack={back} className='share-screen'>
      <View className='share-card'>
        <View className='share-card__top'>
          <Mascot small />
          <View><Text className='share-card__title'>救救我的脑细胞！</Text><Text className='share-card__copy'>我在学 {topic}，当前这关需要帮忙。</Text></View>
        </View>
        <View className='completion-sheet'>
          <Text className='completion-sheet__line'>当前进度：闯关暂停</Text>
          <Text className='completion-sheet__line'>好友助力后：恢复 3 颗心</Text>
        </View>
      </View>
      <PrimaryButton
        openType='share'
        disabled={!share}
        onClick={() => setTimeout(back, 500)}
      >
        ↗ 分享到好友 / 群聊
      </PrimaryButton>
      <SecondaryButton className='action-gap' onClick={back}>暂时不用</SecondaryButton>
      <Text className='micro-copy'>好友完成助力后，返回原题即可继续</Text>
    </AppShell>
  )
}
