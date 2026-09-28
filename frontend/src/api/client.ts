/** 统一请求封装：拼后端地址、带上当前操作人工号、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 当前操作人工号：写操作据此在服务端核对车站归属、角色权限与当班状态。 */
function operatorHeaders(init?: RequestInit): HeadersInit {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  const operatorId = localStorage.getItem('powersupply.operatorId')
  if (operatorId) {
    headers.set('X-Operator-Id', operatorId)
  }
  return headers
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    ...init,
    headers: operatorHeaders(init),
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 读取后端结构化错误：越权时带上 missing_permission，重复操作时带上 duplicate。 */
export async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json()
    const detail = data?.detail
    if (detail && typeof detail === 'object' && detail.message) {
      return String(detail.message)
    }
    if (typeof detail === 'string' && detail) {
      return detail
    }
    if (data?.message) {
      return String(data.message)
    }
  } catch {
    /* 忽略非 JSON 错误体 */
  }
  return fallback
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
