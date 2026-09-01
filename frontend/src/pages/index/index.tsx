import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Button, Image, Text, Textarea, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, useUnload } from '@tarojs/taro'

import alertIcon from '../../assets/icons/alert.svg'
import bookIcon from '../../assets/icons/book.svg'
import checkIcon from '../../assets/icons/check.svg'
import fileIcon from '../../assets/icons/file.svg'
import linkIcon from '../../assets/icons/link.svg'
import questionIcon from '../../assets/icons/question.svg'
import searchIcon from '../../assets/icons/search.svg'
import { PrimaryButton, SecondaryButton } from '../../components/ActionButton'
import { AppShell } from '../../components/AppShell'
import { Mascot } from '../../components/Mascot'
import { VerificationNotice } from '../../components/VerificationNotice'
import { api } from '../../services/api'
import { ensureLogin } from '../../services/auth'
import { CreationFlow } from '../../services/creationFlow'
import type { Game } from '../../types/api'
import {
  classifyLearningInput,
  type ErrorAction,
  type GenerationErrorPresentation,
  validateLearningInput,
} from '../../services/gameCreation'
import { useSessionStore } from '../../stores/session'
import './index.scss'

const SUGGESTIONS = ['Python 基础', '高情商聊天', '咖啡拉花', '理财小白']

const STATE_ICONS: Record<GenerationErrorPresentation['symbol'], string> = {
  alert: alertIcon,
  check: checkIcon,
  file: fileIcon,
  link: linkIcon,
  question: questionIcon,
  search: searchIcon,
}

export default function Index() {
  const setLastTopic = useSessionStore((state) => state.setLastTopic)
  const setCurrentGame = useSessionStore((state) => state.setCurrentGame)
  const [flow] = useState(() => new CreationFlow(
    { ...api, ensureSession: ensureLogin },
    useSessionStore.getState().lastTopic,
    useSessionStore.getState().user?.id || null,
  ))
  const { topic, view, error: generationError, canUseBasic, expiresAt } = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  const [focusInput, setFocusInput] = useState(false)
  const visible = useRef(true)

  useEffect(() => useSessionStore.subscribe(state => flow.changeIdentity(state.user?.id || null)), [flow])
  useEffect(() => () => flow.leave(), [flow])
  useEffect(() => {
    if (!expiresAt || view === 'basic-loading') return
    const timer = setTimeout(flow.checkExpiry, Math.max(0, expiresAt - Date.now()))
    return () => clearTimeout(timer)
  }, [flow, expiresAt, view])
  const leave = () => { visible.current = false; flow.leave() }
  useDidHide(leave)
  useUnload(leave)

  useDidShow(() => {
    visible.current = true
    flow.checkExpiry()
    const currentGameId = useSessionStore.getState().currentGameId
    if (currentGameId) {
      Taro.navigateTo({ url: `/pages/game/index?id=${currentGameId}` }).catch(() => undefined)
    }
  })

  const inputType = classifyLearningInput(topic)
  const hasTopic = Boolean(topic.trim())

  const returnHome = (focus = false) => {
    flow.leave()
    setFocusInput(focus)
  }

  const enterGame = async (game: Game | null) => {
    if (!game || !visible.current) return
    setCurrentGame(game.id)
    try { await Taro.navigateTo({ url: `/pages/game/index?id=${game.id}` }) }
    catch { Taro.showToast({ title: '游戏已保存，请重新进入', icon: 'none' }) }
  }

  const generate = async () => {
    const validationMessage = validateLearningInput(topic)
    if (validationMessage) {
      Taro.showToast({ title: validationMessage, icon: 'none' })
      return
    }

    setLastTopic(topic.trim())
    setFocusInput(false)
    await enterGame(await flow.startOnline())
  }

  const generateBasic = async () => { await enterGame(await flow.confirmBasic()) }
  const preservedInput = (
    <View className='preserved-input'>
      <Image src={inputType === 'url' ? linkIcon : bookIcon} aria-hidden />
      <Text>{topic}</Text>
    </View>
  )

  const handleErrorAction = (action: ErrorAction) => {
    if (action === 'retry') {
      generate()
      return
    }
    returnHome(action === 'edit')
  }

  if (view === 'confirm') {
    return (
      <AppShell title='确认学习方式' back onBack={() => returnHome(true)} className='basic-recovery'>
        <View className='basic-confirm'>
          <View className='state-illustration'><Image className='state-icon' src={bookIcon} aria-hidden /></View>
          <Text className='state-title'>先学基础知识？</Text>
          {preservedInput}
          <VerificationNotice />
          <Text className='state-copy'>本次只学习通用沟通原则，不查询网页或最新资料。AI 仍可能出错，请结合实际情况判断。</Text>
          <Text className='state-copy'>这一标识会一直保留在本局题目和通关页中。</Text>
          <PrimaryButton className='action-gap' onClick={generateBasic}>我已了解，生成基础知识题</PrimaryButton>
          <SecondaryButton className='action-gap' onClick={flow.returnToFailure}>暂不选择，返回</SecondaryButton>
        </View>
      </AppShell>
    )
  }

  if (view === 'loading' || view === 'basic-loading') {
    const basic = view === 'basic-loading'
    return (
      <AppShell title={basic ? '正在生成' : '正在准备'} back onBack={() => returnHome()} className='basic-recovery'>
        {basic && <VerificationNotice />}
        <View className='loading-stage'>
          <View>
            <View className='loading-doodle' aria-hidden><View className='loading-book' /><View className='loading-pencil' /></View>
            <Text className='loading-copy-title'>
              {basic ? '正在生成基础知识题' : '正在联网准备题目'}
            </Text>
            <Text className='loading-copy-subtitle' aria-live='polite'>
              {basic ? '本次不会进行联网核验' : inputType === 'url' ? '将读取页面、生成题目并校验事实' : '将查询资料、生成题目并校验事实'}
            </Text>
          </View>
        </View>
        {preservedInput}
        <Text className='micro-copy'>请稍候，完成后会自动进入关卡。</Text>
        <SecondaryButton className='action-gap' onClick={() => returnHome()}>取消并返回</SecondaryButton>
      </AppShell>
    )
  }

  if ((view === 'error' || view === 'basic-error' || view === 'expired') && generationError) {
    const expired = view === 'expired'
    const basicFailed = view === 'basic-error'
    const showPreservedInput = ![
      'CONTENT_BLOCKED',
      'TOPIC_AMBIGUOUS',
      'SOURCES_INSUFFICIENT',
    ].includes(generationError.code)
    const tone = generationError.tone === 'default' ? 'yellow' : generationError.tone
    return (
      <AppShell title={expired ? '请重新联网' : basicFailed ? '生成未完成' : generationError.navTitle} back onBack={() => returnHome()} className='basic-recovery'>
        <View className='error-state error-state--research'>
          <View>
            <View className={`state-illustration state-illustration--${tone}`}>
              <Image className='state-icon' src={STATE_ICONS[generationError.symbol]} />
            </View>
            <Text className='state-title'>{expired ? '这次选择已过期' : basicFailed ? '基础知识题也没生成成功' : generationError.title}</Text>
            <Text className='state-copy' aria-live='polite'>
              {expired ? '基础知识许可已过期或不再适用。\n请重新联网后，再选择学习方式。'
                : basicFailed ? '没有保存本次题目。你可以主动重试，或重新联网获取资料。'
                : generationError.code === 'TOPIC_AMBIGUOUS'
                ? `“${generationError.preservedInput}” 可能指：`
                : generationError.copy}
            </Text>
            {basicFailed && <VerificationNotice />}
            {generationError.interpretations.length > 0 && (
              <View className='meaning-list'>
                {generationError.interpretations.map((item) => <Text key={item}>{item}</Text>)}
              </View>
            )}
            {generationError.code === 'SOURCES_INSUFFICIENT' && (
              <View className='rewrite-example'>
                <Text className='rewrite-example__label'>试试这样写</Text>
                <Text>“{new Date().getFullYear()} 年 {generationError.preservedInput} 的具体领域或用法”</Text>
              </View>
            )}
            {showPreservedInput && (
              <View className='preserved-input'>
                <Image src={classifyLearningInput(generationError.preservedInput) === 'url' ? linkIcon : bookIcon} aria-hidden />
                <Text>{generationError.preservedInput}</Text>
              </View>
            )}
            <PrimaryButton onClick={() => basicFailed ? generateBasic() : expired || canUseBasic ? generate() : handleErrorAction(generationError.primaryAction)}>
              {basicFailed ? '重试基础知识题' : expired ? '重新联网' : canUseBasic ? '重试联网' : generationError.primaryText}
            </PrimaryButton>
            {canUseBasic && !basicFailed ? (
              <View className='basic-offer'>
                <VerificationNotice />
                <Text className='basic-offer__copy'>这个主题可以先练通用基础知识，但题目可能不准确，不包含最新资料。</Text>
                <SecondaryButton className='action-gap' onClick={flow.selectBasic}>选择基础知识题</SecondaryButton>
                <Button className='text-action' onClick={() => returnHome(true)}>修改主题</Button>
              </View>
            ) : (basicFailed || expired) ? (
              <SecondaryButton className='action-gap' onClick={() => basicFailed ? generate() : returnHome(true)}>
                {basicFailed ? '改为重试联网' : '修改主题'}
              </SecondaryButton>
            ) : generationError.secondaryText && generationError.secondaryAction && (
              <SecondaryButton
                className='action-gap'
                onClick={() => handleErrorAction(generationError.secondaryAction as ErrorAction)}
              >
                {generationError.secondaryText}
              </SecondaryButton>
            )}
          </View>
        </View>
      </AppShell>
    )
  }

  const isUrl = inputType === 'url'
  return (
    <AppShell>
      <Text className='brand-sticker'>AI 万物学堂</Text>
      <View className={`home-hero ${isUrl ? 'home-hero--compact' : ''}`}>
        <Mascot />
        <Text className='hero-title'>
          {isUrl ? '网页也能扔进来！' : hasTopic ? '这题，我来出！' : '不会？扔进来！'}
        </Text>
        <Text className='hero-subtitle'>
          {isUrl
            ? '我会先读懂页面，再搭三关'
            : hasTopic ? `三道题，把 ${topic.trim()} 讲明白` : '今天想轻松学点什么？'}
        </Text>
      </View>
      <Text className='field-label'>知识关键词或公开网页</Text>
      <View className={`input-shell ${isUrl ? 'input-shell--url' : ''}`}>
        {isUrl && <Text className='input-kind'><Image src={linkIcon} />网页</Text>}
        <Textarea
          className={`topic-field topic-field--textarea ${isUrl ? 'topic-field--long' : ''}`}
          value={topic}
          focus={focusInput}
          maxlength={2048}
          disableDefaultPadding
          placeholder='比如：Python 基础，或粘贴一张公开网页'
          onBlur={() => setFocusInput(false)}
          onInput={(event) => flow.edit(event.detail.value)}
        />
        {isUrl && <Text className='field-count'>{topic.length} / 2048</Text>}
      </View>
      {isUrl && <Text className='field-help'>支持公开 HTTP(S) 页面；需要登录的页面无法读取</Text>}
      {!isUrl && (
        <View className='chips'>
          {SUGGESTIONS.map((item) => (
            <Button className='chip' key={item} onClick={() => flow.edit(item)}>{item}</Button>
          ))}
        </View>
      )}
      <PrimaryButton onClick={generate}>
        {isUrl ? '读取网页 · 生成三关' : hasTopic ? '生成我的闯关' : '开一局 · 3 关学明白'}
      </PrimaryButton>
      <SecondaryButton
        className='action-gap'
        onClick={() => Taro.navigateTo({ url: '/pages/battle/create/index' }).catch(() => undefined)}
      >
        ⚔ 约好友 · 对战一局
      </SecondaryButton>
      <Text className='micro-copy'>
        {isUrl
          ? '原网址会保留，失败后不用重新粘贴'
          : hasTopic ? '复杂主题最长约 90 秒' : 'AI 会先查资料，再生成题目'}
      </Text>
    </AppShell>
  )
}
