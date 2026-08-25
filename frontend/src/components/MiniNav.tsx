import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

interface MiniNavProps {
  title: string
  back: boolean
  onBack?: () => void
}

export function MiniNav({ title, back, onBack }: MiniNavProps) {
  const goBack = () => {
    if (onBack) onBack()
    else Taro.navigateBack()
  }

  return (
    <View className='mini-nav'>
      <View className='mini-nav__left'>
        {back && (
          <Button className='icon-button mini-nav__back' onClick={goBack} aria-label='返回'>
            <Text className='back-icon' />
          </Button>
        )}
      </View>
      <Text className='mini-nav__title'>{title}</Text>
      {process.env.TARO_ENV === 'h5' && (
        <View className='capsule' aria-hidden>
          <View className='capsule__dots'><Text>•</Text><Text>•</Text><Text>•</Text></View>
          <View className='capsule__divider' />
          <View className='capsule__close' />
        </View>
      )}
    </View>
  )
}
