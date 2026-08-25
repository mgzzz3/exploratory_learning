import { useEffect, useRef, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow, useLoad, useShareAppMessage } from '@tarojs/taro'

import { AppShell } from '../../components/AppShell'
import { Mascot } from '../../components/Mascot'
import { PrimaryButton, SecondaryButton } from '../../components/ActionButton'
import { StatusState } from '../../components/StatusState'
import { api } from '../../services/api'
import { ensureLogin } from '../../services/auth'
import { ApiError } from '../../services/request'
import { useSessionStore } from '../../stores/session'
import type { AnswerResponse, Game, GameLevel } from '../../types/api'
import { newRequestId } from '../../utils/uuid'
import './index.scss'

type Feedback = 'correct' | 'wrong' | 'revived' | null

function levelLabel(game: Game): string {
  if (game.status === 'paused') return '本局已暂停'
  const labels = ['第 1 关 · 新手', '第 2 关 · 进阶', '第 3 关 · Boss']
  return labels[game.current_level]
}

function hearts(value: number): string {
  return '♥'.repeat(value) + '♡'.repeat(3 - value)
}

function elapsed(seconds: number | null): string {
  const value = seconds || 1
  return `${Math.floor(value / 60)} 分 ${String(value % 60).padStart(2, '0')} 秒`
}

export default function GamePage() {
  const storeGameId = useSessionStore((state) => state.currentGameId)
  const setCurrentGame = useSessionStore((state) => state.setCurrentGame)
  const setShare = useSessionStore((state) => state.setShare)
  const vibration = useSessionStore((state) => state.settings.vibration_enabled)
  const gameIdRef = useRef('')
  const [game, setGame] = useState<Game | null>(null)
  const [displayLevel, setDisplayLevel] = useState<GameLevel | null>(null)
  const [answerResult, setAnswerResult] = useState<AnswerResponse | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [pending, setPending] = useState(false)
  const [networkError, setNetworkError] = useState(false)
  const [adPreview, setAdPreview] = useState(false)

  useLoad((options) => {
    gameIdRef.current = options.id || storeGameId || ''
  })

  const loadGame = async () => {
    const gameId = gameIdRef.current || storeGameId
    if (!gameId) {
      await Taro.reLaunch({ url: '/pages/index/index' })
      return
    }
    try {
      await ensureLogin()
      const latest = await api.getGame(gameId)
      setGame(latest)
      setDisplayLevel(latest.level)
      setCurrentGame(latest.status === 'completed' ? null : latest.id)
      setNetworkError(false)
    } catch {
      setNetworkError(true)
    }
  }

  useDidShow(() => { loadGame() })

  useShareAppMessage(() => ({
    title: game?.status === 'completed' ? `我用三关学会了${game.topic}` : '来 AI 万物学堂轻松学点东西',
    path: '/pages/index/index',
  }))

  useEffect(() => {
    if (feedback !== 'correct' || !answerResult) return
    const timer = setTimeout(() => {
      setGame(answerResult.game)
      setDisplayLevel(answerResult.game.level)
      setFeedback(null)
      setSelected(null)
      setAnswerResult(null)
    }, 2000)
    return () => clearTimeout(timer)
  }, [feedback, answerResult])

  const quit = () => {
    setCurrentGame(null)
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  const vibrate = () => {
    if (vibration) Taro.vibrateShort({ type: 'light' }).catch(() => undefined)
  }

  const choose = async (option: number) => {
    if (!game || pending || feedback || game.status !== 'active') return
    const before = game
    setPending(true)
    setSelected(option)
    try {
      const result = await api.answer(game.id, option, newRequestId())
      setAnswerResult(result)
      vibrate()
      if (result.result === 'completed') {
        setGame(result.game)
        setDisplayLevel(null)
        setCurrentGame(null)
        setSelected(null)
      } else if (result.result === 'correct') {
        setDisplayLevel(before.level)
        setFeedback('correct')
      } else {
        setGame(result.game)
        setDisplayLevel(result.game.level)
        setFeedback('wrong')
      }
    } catch (error) {
      const apiError = error as ApiError
      if (apiError.isNetworkError) setNetworkError(true)
      else Taro.showToast({ title: apiError.message, icon: 'none' })
      setSelected(null)
    } finally {
      setPending(false)
    }
  }

  const finishWrongFeedback = () => {
    setFeedback(null)
    setSelected(null)
    setAnswerResult(null)
  }

  const applyAdRevive = async () => {
    if (!game) return
    try {
      const revived = await api.reviveWithAd(game.id, newRequestId(), true)
      setGame(revived)
      setDisplayLevel(revived.level)
      setFeedback('revived')
      vibrate()
    } catch (error) {
      Taro.showToast({ title: (error as Error).message, icon: 'none' })
    } finally {
      setAdPreview(false)
    }
  }

  const watchAd = async () => {
    if (!game) return
    if (process.env.TARO_ENV === 'h5') {
      setAdPreview(true)
      setTimeout(applyAdRevive, 1800)
      return
    }
    if (!REWARDED_AD_UNIT_ID) {
      Taro.showToast({ title: '广告位暂未配置', icon: 'none' })
      return
    }
    const ad = Taro.createRewardedVideoAd({ adUnitId: REWARDED_AD_UNIT_ID })
    const ended = await new Promise<boolean>((resolve) => {
      const close = (result: { isEnded?: boolean }) => {
        ad.offClose(close)
        resolve(Boolean(result?.isEnded))
      }
      const fail = () => {
        ad.offError(fail)
        resolve(false)
      }
      ad.onClose(close)
      ad.onError(fail)
      ad.show().catch(() => ad.load().then(() => ad.show()).catch(fail))
    })
    ad.destroy()
    if (ended) await applyAdRevive()
    else Taro.showToast({ title: '完整观看后才能恢复脑力', icon: 'none' })
  }

  const askFriend = async () => {
    if (!game) return
    try {
      const share = await api.createShare(game.id)
      setShare(share)
      await Taro.navigateTo({ url: '/pages/share/index' })
    } catch (error) {
      Taro.showToast({ title: (error as Error).message, icon: 'none' })
    }
  }

  if (networkError) {
    return (
      <AppShell title='连接中断' back onBack={quit} className='game-screen'>
        <StatusState
          tone='blue'
          icon='⌁'
          title='网络开小差了'
          copy={'检查 Wi-Fi 或移动网络后再试。\n当前闯关进度不会丢失。'}
          primaryText='↻ 重新连接'
          onPrimary={loadGame}
          secondaryText='返回首页'
          onSecondary={quit}
        />
      </AppShell>
    )
  }

  if (!game) {
    return <AppShell title='闯关' back onBack={quit}><View className='spinner' /></AppShell>
  }

  if (game.status === 'completed') {
    return (
      <AppShell title='通关小报' back onBack={quit} className='game-screen'>
        <View className='completion-hero'>
          <Text className='stamp'>{game.topic} 萌新毕业</Text>
          <Text className='completion-title'>三关，全拿下！</Text>
          <Text className='hero-subtitle'>本局用时 {elapsed(game.elapsed_seconds)}</Text>
        </View>
        <View className='completion-sheet'>
          {game.summary.map((item) => <Text className='completion-sheet__line' key={item}>✓ {item}</Text>)}
        </View>
        <PrimaryButton onClick={quit}>再学一个主题</PrimaryButton>
        <SecondaryButton className='action-gap' openType='share'>↗ 分享通关小报</SecondaryButton>
      </AppShell>
    )
  }

  const level = displayLevel || game.level
  return (
    <AppShell
      title={game.topic}
      back
      onBack={quit}
      className={`game-screen ${level?.tier === 'boss' ? 'app-shell--boss' : ''}`}
    >
      <View className='game-hud'>
        <Text className='level-badge'>{feedback === 'correct' ? `第 ${game.current_level + 1} 关 · 通过` : levelLabel(game)}</Text>
        <View className='progress'><View className='progress__bar' style={{ width: `${feedback === 'correct' ? 33 + game.current_level * 33 : game.progress}%` }} /></View>
        <Text className='hearts'>{hearts(game.hearts)}</Text>
      </View>

      {feedback === 'correct' && answerResult ? (
        <>
          <View className='success-burst'><Text className='stamp'>脑子到账！</Text></View>
          <Text className='bubble'>{answerResult.message}</Text>
          {level && (
            <View className='options'>
              <Button className='option option--correct'>
                <Text className='option__key'>{level.options[selected || 0]?.key}</Text>
                <Text>{level.options[selected || 0]?.text}</Text>
                <Text className='option__state'>✓</Text>
              </Button>
            </View>
          )}
          <Text className='micro-copy'>2 秒后自动进入下一关</Text>
        </>
      ) : feedback === 'revived' ? (
        <>
          <View className='success-burst'><Text className='stamp'>满血回来！</Text></View>
          <Text className='bubble'><Text className='bubble__label'>小万老师</Text>电量充足。刚才那道题还在，慢慢看清条件和题目。</Text>
          <PrimaryButton className='revive-button' onClick={() => setFeedback(null)}>继续挑战 {level?.tier === 'boss' ? 'Boss' : ''}</PrimaryButton>
        </>
      ) : level ? (
        <>
          {level.tier === 'boss' ? (
            <>
              <Text className='boss-banner'>{game.hearts === 1 ? '最后 1 颗心' : '期末大魔王'}</Text>
              <Text className='bubble bubble--question'>{level.question}</Text>
            </>
          ) : (
            <View className='chat'>
              <View className='chat-row'><Mascot small /><Text className='bubble'><Text className='bubble__label'>小万老师</Text>{level.intro}</Text></View>
              <Text className='bubble bubble--question'><Text className='bubble__label'>{level.title}</Text>{level.question}</Text>
            </View>
          )}
          <View className='options'>
            {level.options.map((option) => (
              <Button
                key={option.index}
                className={`option ${selected === option.index && feedback === 'wrong' ? 'option--wrong' : ''}`}
                {...(pending || Boolean(feedback) || game.status !== 'active' ? { disabled: true } : {})}
                onClick={() => choose(option.index)}
              >
                <Text className='option__key'>{option.key}</Text>
                <Text>{option.text}</Text>
                <Text className='option__state'>{selected === option.index && feedback === 'wrong' ? '×' : ''}</Text>
              </Button>
            ))}
          </View>
        </>
      ) : null}

      {game.hearts === 1 && !feedback && game.status === 'active' && <Text className='toast'>再答错一次将暂停本局</Text>}

      {feedback === 'wrong' && answerResult && (
        <><View className='scrim' /><View className='modal'>
          <Text className='stamp'>先别急</Text>
          <Text className='modal__title'>换个大白话再看一次</Text>
          <Text className='teacher-note'>{answerResult.explanation}</Text>
          <PrimaryButton onClick={finishWrongFeedback}>懂了，继续</PrimaryButton>
        </View></>
      )}

      {game.status === 'paused' && !feedback && (
        <><View className='scrim' /><View className='modal modal--low'>
          <View className='energy-hero'><View className='energy-icon'><Text className='energy-icon-text'>×</Text></View></View>
          <Text className='modal__title'>脑细胞欠费了</Text>
          <Text className='modal__copy'>补满 3 颗心，回来继续打 {level?.tier === 'boss' ? 'Boss' : '这一关'}。</Text>
          <View className='modal-actions'>
            <PrimaryButton onClick={watchAd}>▷ 看视频 · 满血复活</PrimaryButton>
            <SecondaryButton className='secondary-action--blue' onClick={askFriend}>↗ 呼叫朋友帮忙</SecondaryButton>
          </View>
        </View></>
      )}

      {adPreview && (
        <View className='ad-screen'>
          <View className='ad-screen__top'><Text>广告</Text><Text>完整观看后获得 3 颗心</Text></View>
          <View className='ad-screen__content'><View><Text className='ad-play'>▷</Text><Text className='ad-screen__title'>学习间歇，放松一下</Text><Text className='ad-screen__copy'>开发预览广告即将结束</Text></View></View>
          <Text className='ad-screen__footer'>中途退出将无法获得奖励</Text>
        </View>
      )}
    </AppShell>
  )
}
