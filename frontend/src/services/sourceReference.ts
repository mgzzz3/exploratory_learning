import type { AcquisitionMethod } from '../types/api'

const OPENABLE_URL_PATTERN = /^https?:\/\/[^/?#\s]+(?:[/?#][^\s]*)?$/i

export function formatRetrievedDate(value: string | null): string {
  if (!value) return ''
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return match ? `${match[1]}.${match[2]}.${match[3]}` : ''
}

export function sourceMethodLabel(method: AcquisitionMethod): string {
  return method === 'extract' ? '整页读取' : '搜索'
}

export function isOpenableSourceUrl(url: string): boolean {
  return OPENABLE_URL_PATTERN.test(url.trim())
}
