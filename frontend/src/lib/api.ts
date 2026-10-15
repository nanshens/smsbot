let csrf = ''
export function setCsrf(value: string) { csrf = value }
export class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }
export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, { ...options, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...options.headers } })
  const result = response.status === 204 ? null : await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') window.dispatchEvent(new Event('session-expired'))
    throw new ApiError(typeof result.detail === 'string' ? result.detail : '请求失败', response.status)
  }
  return result
}
export const post = <T = any>(path: string, data?: unknown) => api<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) })
export const date = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
