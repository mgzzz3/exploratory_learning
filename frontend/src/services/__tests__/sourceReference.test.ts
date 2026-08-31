import { describe, expect, it } from 'vitest'

import {
  formatRetrievedDate,
  isOpenableSourceUrl,
  sourceMethodLabel,
} from '../sourceReference'

describe('formatRetrievedDate', () => {
  it('将 API 时间稳定显示为原型日期格式', () => {
    expect(formatRetrievedDate('2026-08-28T13:40:00Z')).toBe('2026.08.28')
  })

  it('空检索时间不生成虚构日期', () => {
    expect(formatRetrievedDate(null)).toBe('')
  })
})

describe('sourceMethodLabel', () => {
  it('区分搜索摘要与整页读取', () => {
    expect(sourceMethodLabel('search')).toBe('搜索')
    expect(sourceMethodLabel('extract')).toBe('整页读取')
  })
})

describe('isOpenableSourceUrl', () => {
  it.each([
    ['https://docs.example.com/article', true],
    ['http://example.com', true],
    ['javascript:alert(1)', false],
    ['file:///etc/passwd', false],
    ['ftp://example.com/file', false],
    ['', false],
  ] as const)('校验 %s', (url, expected) => {
    expect(isOpenableSourceUrl(url)).toBe(expected)
  })
})
