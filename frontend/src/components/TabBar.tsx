import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

export function TabBar({ active }: { active: 'learn' | 'profile' }) {
  const go = (page: 'learn' | 'profile') => {
    if (page === active) return
    Taro.reLaunch({
      url: page === 'learn' ? '/pages/index/index' : '/pages/profile/index',
    })
  }

  return (
    <View className='tabbar'>
      <Button className={`tabbar__item ${active === 'learn' ? 'is-active' : ''}`} onClick={() => go('learn')}>
        <View className='tab-icon tab-icon--book' />
        <Text>学习</Text>
      </Button>
      <Button className={`tabbar__item ${active === 'profile' ? 'is-active' : ''}`} onClick={() => go('profile')}>
        <View className='tab-icon tab-icon--user' />
        <Text>我的</Text>
      </Button>
    </View>
  )
}
