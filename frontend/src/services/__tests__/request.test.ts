import { describe, expect, it } from 'vitest'

import { parseApiErrorResponse } from '../apiError'

describe('parseApiErrorResponse', () => {
  it('保留 HTTP 业务错误的 code、details 与状态码', () => {
    const error = parseApiErrorResponse(422, {
      error: {
        code: 'TOPIC_AMBIGUOUS',
        message: '这个主题可能有多种意思，请补充说明',
        details: { interpretations: ['方向一', '方向二'] },
      },
    })

    expect(error.code).toBe('TOPIC_AMBIGUOUS')
    expect(error.status).toBe(422)
    expect(error.details).toEqual({ interpretations: ['方向一', '方向二'] })
    expect(error.isNetworkError).toBe(false)
  })

  it('为无标准错误体的 HTTP 失败提供稳定兜底', () => {
    const error = parseApiErrorResponse(502, '<html>bad gateway</html>')

    expect(error.code).toBe('HTTP_ERROR')
    expect(error.status).toBe(502)
    expect(error.isNetworkError).toBe(false)
  })
})
