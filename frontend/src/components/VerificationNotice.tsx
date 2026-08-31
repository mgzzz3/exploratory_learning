import { Image, Text, View } from '@tarojs/components'
import alertIcon from '../assets/icons/alert.svg'
import { BASIC_NOTICE } from '../services/gameVerification'
import './VerificationNotice.scss'

export function VerificationNotice() {
  return (
    <View className='basic-notice'>
      <Image className='basic-notice__icon' src={alertIcon} aria-hidden />
      <View>
        <Text className='basic-notice__title'>{BASIC_NOTICE}</Text>
        <Text className='basic-notice__copy'>仅供基础学习，请结合实际情况判断。</Text>
      </View>
    </View>
  )
}
