export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') msg = body.detail
      else if (body && typeof body === 'object') msg = JSON.stringify(body)
    } catch {
      // 非 JSON 错误体时退回 statusText
    }
    throw new Error(msg || res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
