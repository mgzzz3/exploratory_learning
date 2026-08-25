import type { CSSProperties, PropsWithChildren } from 'react'
import { useMemo } from 'react'
import { View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { MiniNav } from './MiniNav'
import { TabBar } from './TabBar'

interface AppShellProps extends PropsWithChildren {
  title?: string
  back?: boolean
  activeTab?: 'learn' | 'profile'
  onBack?: () => void
  className?: string
  hideTabBar?: boolean
}

export function AppShell({
  children,
  title = '',
  back = false,
  activeTab = 'learn',
  onBack,
  className = '',
  hideTabBar = false,
}: AppShellProps) {
  const metrics = useMemo(() => {
    try {
      const windowInfo = Taro.getWindowInfo()
      const status = windowInfo.statusBarHeight || 20
      if (process.env.TARO_ENV === 'weapp') {
        const menu = Taro.getMenuButtonBoundingClientRect()
        return {
          status,
          nav: Math.max(44, menu.bottom + menu.top - status * 2),
          right: windowInfo.windowWidth - menu.left + 8,
        }
      }
      return { status: 20, nav: 48, right: 100 }
    } catch {
      return { status: 20, nav: 48, right: 100 }
    }
  }, [])
  const style = {
    '--status-height': `${metrics.status}px`,
    '--nav-height': `${metrics.nav}px`,
    '--menu-right-space': `${metrics.right}px`,
  } as CSSProperties

  return (
    <View className={`app-shell ${className}`} style={style}>
      <MiniNav title={title} back={back} onBack={onBack} />
      <View className={`screen ${hideTabBar ? 'screen--no-tab' : ''}`}>{children}</View>
      {!hideTabBar && <TabBar active={activeTab} />}
    </View>
  )
}
