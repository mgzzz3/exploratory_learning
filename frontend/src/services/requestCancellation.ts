// 跨小程序/H5 的请求取消信号；不依赖小程序中未必存在的 AbortController。
export class RequestCancellation {
  cancelled = false
  private listeners = new Set<() => void>()

  subscribe(listener: () => void): () => void {
    if (this.cancelled) listener()
    else this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  cancel(): void {
    if (this.cancelled) return
    this.cancelled = true
    this.listeners.forEach(listener => listener())
    this.listeners.clear()
  }
}
