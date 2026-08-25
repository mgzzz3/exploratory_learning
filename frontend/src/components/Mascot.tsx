import { View } from '@tarojs/components'

export function Mascot({ small = false }: { small?: boolean }) {
  return <View className={`mascot ${small ? 'mascot--small' : ''}`}><View className='mascot__mouth' /></View>
}
