import type { LearningInputType } from '../types/api'
import { ApiError } from './apiError'

export const MAX_KEYWORD_LENGTH = 80
export const MAX_URL_LENGTH = 2048

const URL_PATTERN = /^https?:\/\/[^/?#\s]+(?:[/?#][^\s]*)?$/i

export type ErrorTone = 'default' | 'blue' | 'red'
export type ErrorAction = 'retry' | 'edit' | 'home'

export interface GenerationErrorPresentation {
  code: string
  navTitle: string
  tone: ErrorTone
  symbol: 'alert' | 'check' | 'file' | 'link' | 'question' | 'search'
  title: string
  copy: string
  primaryText: string
  primaryAction: ErrorAction
  secondaryText?: string
  secondaryAction?: ErrorAction
  preservedInput: string
  interpretations: string[]
  isNetworkError: boolean
  requestId?: string
  reason?: string
}

interface PresentationTemplate {
  navTitle: string
  tone: ErrorTone
  symbol: GenerationErrorPresentation['symbol']
  title: string
  copy: string
  primaryText: string
  primaryAction: ErrorAction
  secondaryText?: string
  secondaryAction?: ErrorAction
}

const ERROR_PRESENTATIONS: Record<string, PresentationTemplate> = {
  CONTENT_BLOCKED: {
    navTitle: 'AI 万物学堂',
    tone: 'red',
    symbol: 'alert',
    title: '这个主题不能开局',
    copy: '换个健康、具体的学习主题再试试。\n例如：怎么做好时间管理',
    primaryText: '修改学习主题',
    primaryAction: 'edit',
  },
  INVALID_SOURCE_URL: {
    navTitle: '网页没打开',
    tone: 'red',
    symbol: 'link',
    title: '这个地址不能读取',
    copy: '请换成不含账号、密码或私有地址的\n公开 HTTP(S) 网页。',
    primaryText: '修改网址',
    primaryAction: 'edit',
  },
  PAGE_UNREADABLE: {
    navTitle: '网页没读完',
    tone: 'default',
    symbol: 'file',
    title: '页面内容没读出来',
    copy: '它可能需要登录、正文为空，\n或者内容太大了。',
    primaryText: '再读一次',
    primaryAction: 'retry',
    secondaryText: '换一个网址',
    secondaryAction: 'edit',
  },
  TOPIC_AMBIGUOUS: {
    navTitle: '需要你定个方向',
    tone: 'blue',
    symbol: 'question',
    title: '这个词有好几个意思',
    copy: '当前资料支持多个解释，请补充你想学的方向：',
    primaryText: '带回首页补充说明',
    primaryAction: 'edit',
  },
  SOURCES_INSUFFICIENT: {
    navTitle: '资料不够',
    tone: 'default',
    symbol: 'search',
    title: '还撑不起三关',
    copy: '现在找到的可靠资料太少。\n加上领域、版本或使用场景会更准。',
    primaryText: '把主题写具体一点',
    primaryAction: 'edit',
  },
  RESEARCH_AGENT_FAILED: {
    navTitle: '联网没有完成',
    tone: 'blue',
    symbol: 'alert',
    title: '这次联网没完成',
    copy: '联网研究未能完成，没有保存题目。',
    primaryText: '重试联网',
    primaryAction: 'retry',
    secondaryText: '修改主题',
    secondaryAction: 'edit',
  },
  GROUNDING_VALIDATION_FAILED: {
    navTitle: '题目没通过检查',
    tone: 'red',
    symbol: 'check',
    title: '题目和资料没对上',
    copy: '为了不让错误知识混进关卡，\n这次题目没有保存。',
    primaryText: '重新生成',
    primaryAction: 'retry',
    secondaryText: '修改主题',
    secondaryAction: 'edit',
  },
  SEARCH_UNAVAILABLE: {
    navTitle: '搜索暂时不可用',
    tone: 'blue',
    symbol: 'search',
    title: '联网搜索暂时忙',
    copy: '不是你的网络问题。\n资料服务恢复后可以直接重试。',
    primaryText: '重新搜索',
    primaryAction: 'retry',
    secondaryText: '稍后再试',
    secondaryAction: 'home',
  },
  URL_REQUIRES_RESEARCH: {
    navTitle: '暂不支持网页',
    tone: 'default',
    symbol: 'link',
    title: '当前模式还不能读网页',
    copy: '网址已经替你保留。\n现在可以改用知识关键词继续。',
    primaryText: '改成知识关键词',
    primaryAction: 'edit',
    secondaryText: '返回首页',
    secondaryAction: 'home',
  },
  NETWORK_ERROR: {
    navTitle: '连接中断',
    tone: 'blue',
    symbol: 'alert',
    title: '未收到生成结果',
    copy: '检查 Wi-Fi 或移动网络后重试。\n目前无法确认这次请求的结果。',
    primaryText: '重试联网',
    primaryAction: 'retry',
    secondaryText: '返回修改主题',
    secondaryAction: 'edit',
  },
  DEFAULT: {
    navTitle: '生成失败',
    tone: 'default',
    symbol: 'alert',
    title: '这次没搭好关卡',
    copy: '题目生成没有完成，当前输入已经替你保留。',
    primaryText: '重新生成',
    primaryAction: 'retry',
    secondaryText: '修改学习主题',
    secondaryAction: 'edit',
  },
}

export function classifyLearningInput(value: string): LearningInputType {
  return URL_PATTERN.test(value.trim()) ? 'url' : 'keyword'
}

export function validateLearningInput(value: string): string | null {
  const cleaned = value.trim()
  if (!cleaned) return '先扔进来一个学习主题'
  const inputType = classifyLearningInput(cleaned)
  if (inputType === 'url' && cleaned.length > MAX_URL_LENGTH) {
    return '网页地址最多 2048 个字符'
  }
  if (inputType === 'keyword' && cleaned.length > MAX_KEYWORD_LENGTH) {
    return '知识关键词最多 80 个字'
  }
  return null
}

export function learningInputHost(value: string): string {
  const match = value.trim().match(/^https?:\/\/([^/?#]+)/i)
  if (!match) return ''
  return match[1].replace(/^[^@]+@/, '').replace(/:\d+$/, '').toUpperCase()
}

function interpretationsFrom(error: ApiError): string[] {
  const value = error.details?.interpretations
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string').slice(0, 3)
}

export function getGenerationErrorPresentation(
  error: ApiError,
  preservedInput: string,
): GenerationErrorPresentation {
  const template = ERROR_PRESENTATIONS[error.code] || ERROR_PRESENTATIONS.DEFAULT
  const fallback = error.details?.fallback as {available?: unknown} | undefined
  const ineligible = error.code === 'RESEARCH_AGENT_FAILED' && fallback?.available === false
  return {
    code: error.code,
    ...template,
    ...(ineligible ? {title:'这个主题还需要资料', copy:'新知识、版本用法或尚未审核的主题，不能靠基础知识题代替联网资料。'} : {}),
    preservedInput,
    interpretations: interpretationsFrom(error),
    isNetworkError: error.isNetworkError,
    requestId: typeof error.details?.request_id === 'string' && /^[a-f0-9]{32}$/.test(error.details.request_id)
      ? error.details.request_id : undefined,
    reason: typeof error.details?.reason === 'string' && /^[A-Z_]{1,60}$/.test(error.details.reason)
      ? error.details.reason : undefined,
  }
}
