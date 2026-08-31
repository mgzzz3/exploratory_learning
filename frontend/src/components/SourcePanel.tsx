import { Button, Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import copyIcon from '../assets/icons/copy.svg'
import externalLinkIcon from '../assets/icons/external-link.svg'
import {
  formatRetrievedDate,
  isOpenableSourceUrl,
  sourceMethodLabel,
} from '../services/sourceReference'
import type { SourceReference } from '../types/api'

interface SourcePanelProps {
  retrievedAt: string | null
  sources: SourceReference[]
}

export function SourcePanel({ retrievedAt, sources }: SourcePanelProps) {
  if (sources.length === 0) return null

  const isH5 = process.env.TARO_ENV === 'h5'
  const retrievedDate = formatRetrievedDate(retrievedAt)

  const handleSource = async (source: SourceReference) => {
    if (!isOpenableSourceUrl(source.url)) {
      await Taro.showToast({ title: '这个资料链接无法打开', icon: 'none' })
      return
    }
    if (isH5) {
      window.open(source.url, '_blank', 'noopener,noreferrer')
      return
    }
    try {
      await Taro.setClipboardData({ data: source.url })
    } catch {
      await Taro.showToast({ title: '复制失败，请稍后重试', icon: 'none' })
    }
  }

  return (
    <View className='sources-panel'>
      <View className='sources-heading'>
        <View>
          {retrievedDate && <Text className='sources-kicker'>资料获取于 {retrievedDate}</Text>}
          <Text className='sources-title'>本局参考资料</Text>
        </View>
        <Text className='source-count'>{sources.length} 条</Text>
      </View>
      {sources.map((source) => (
        <View className='source-item' key={source.id}>
          <View className='source-item__top'>
            <Text className={`source-method ${source.acquisition_method === 'extract' ? 'source-method--extract' : ''}`}>
              {sourceMethodLabel(source.acquisition_method)}
            </Text>
            <Text className='source-title'>{source.title}</Text>
          </View>
          <Text className='source-domain'>{source.domain}</Text>
          <Button className='copy-action' onClick={() => handleSource(source)}>
            <Image src={isH5 ? externalLinkIcon : copyIcon} />
            {isH5 ? '打开链接' : '复制链接'}
          </Button>
        </View>
      ))}
    </View>
  )
}
