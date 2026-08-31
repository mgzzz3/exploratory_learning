import { describe, expect, it } from 'vitest'

import {
  classifyLearningInput,
  getGenerationErrorPresentation,
  validateLearningInput,
} from '../gameCreation'
import { ApiError } from '../apiError'

describe('classifyLearningInput', () => {
  it.each([
    ['Python 基础', 'keyword'],
    ['Node.js 运行时', 'keyword'],
    ['https://docs.langchain.com/oss/python/integrations/tools/tavily_extract', 'url'],
    ['http://example.com/article?q=1', 'url'],
    ['请学习 https://example.com', 'keyword'],
    ['https://example.com https://example.org', 'keyword'],
  ] as const)('将 %s 判定为 %s', (value, expected) => {
    expect(classifyLearningInput(value)).toBe(expected)
  })
})

describe('validateLearningInput', () => {
  it('接受 80 字符关键词与 2048 字符 URL 边界', () => {
    expect(validateLearningInput('知'.repeat(80))).toBeNull()
    expect(validateLearningInput(`https://example.com/${'a'.repeat(2028)}`)).toBeNull()
  })

  it('拒绝空输入、过长关键词和过长 URL', () => {
    expect(validateLearningInput('')).toBe('先扔进来一个学习主题')
    expect(validateLearningInput('知'.repeat(81))).toBe('知识关键词最多 80 个字')
    expect(validateLearningInput(`https://example.com/${'a'.repeat(2029)}`)).toBe('网页地址最多 2048 个字符')
  })
})

describe('getGenerationErrorPresentation', () => {
  it('后端明确不授予许可时使用已确认的未获准原型文案', () => {
    const presentation = getGenerationErrorPresentation(new ApiError({code:'RESEARCH_AGENT_FAILED',
      message:'失败', status:502, details:{fallback:{available:false}}}), 'Harness Engineering')
    expect(presentation.title).toBe('这个主题还需要资料')
    expect(presentation.code).toBe('RESEARCH_AGENT_FAILED')
    expect(presentation.primaryText).toBe('重试联网')
  })
  it.each([
    'INVALID_SOURCE_URL',
    'PAGE_UNREADABLE',
    'TOPIC_AMBIGUOUS',
    'SOURCES_INSUFFICIENT',
    'RESEARCH_AGENT_FAILED',
    'GROUNDING_VALIDATION_FAILED',
    'SEARCH_UNAVAILABLE',
    'URL_REQUIRES_RESEARCH',
  ])('为业务错误 %s 返回专用状态，不归类为网络错误', (code) => {
    const presentation = getGenerationErrorPresentation(new ApiError({
      message: '服务端错误',
      code,
      status: 422,
      details: { interpretations: ['含义一', '含义二'] },
    }), 'Harness Engineering')

    expect(presentation).not.toBeNull()
    expect(presentation?.code).toBe(code)
    expect(presentation?.isNetworkError).toBe(false)
    expect(presentation?.preservedInput).toBe('Harness Engineering')
  })

  it('保留歧义候选解释且最多展示三个', () => {
    const presentation = getGenerationErrorPresentation(new ApiError({
      message: '主题不明确',
      code: 'TOPIC_AMBIGUOUS',
      status: 422,
      details: { interpretations: ['方向一', '方向二', '方向三', '方向四'] },
    }), 'Harness Engineering')

    expect(presentation?.interpretations).toEqual(['方向一', '方向二', '方向三'])
  })

  it('只把无 HTTP 响应的失败归类为网络错误', () => {
    const presentation = getGenerationErrorPresentation(new ApiError({
      message: '网络开小差了，请检查连接后重试',
      code: 'NETWORK_ERROR',
      isNetworkError: true,
    }), 'Python 基础')

    expect(presentation?.isNetworkError).toBe(true)
  })
})
