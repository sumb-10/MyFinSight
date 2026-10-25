import type { ApiErrorBody } from "./types"

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1"
/** LLM 이 걸리는 호출(요청 생성·답변·수정 요청 등)은 한 턴에 1~3분이 걸릴 수 있다 (서버 LLM 제한 180초). 기본 호출은 60초. */
export const LLM_TIMEOUT_MS = 190_000

export class ApiError extends Error {
  code: string
  status: number
  fields?: Record<string, string>
  details?: Record<string, unknown>
  constructor(code: string, message_ko: string, status: number, fields?: Record<string, string>, details?: Record<string, unknown>) {
    super(message_ko)
    this.code = code
    this.status = status
    this.fields = fields
    this.details = details
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

export function errorMessage(e: unknown): string {
  if (isApiError(e)) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}

/** 모든 API 호출. 끊긴 서버는 NETWORK_UNAVAILABLE 오류가 되며 절대 성공처럼 보이지 않는다. */
export async function fetchJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const ctrl = new AbortController()
  const timer = window.setTimeout(() => ctrl.abort(), init?.timeoutMs ?? 60_000)
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: init?.signal ?? ctrl.signal,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers ?? {}) },
    })
  } catch (e) {
    if ((e as Error).name === "AbortError") throw new ApiError("TIMEOUT", "분석 서버 응답이 없습니다 (시간 초과). 잠시 뒤 다시 시도해 주세요.", 0)
    throw new ApiError("NETWORK_UNAVAILABLE", "분석 서버에 연결할 수 없습니다. 잠시 뒤 다시 시도하고, 계속되면 서버 관리자에게 분석 서버가 켜져 있는지 확인해 달라고 하세요.", 0)
  } finally {
    window.clearTimeout(timer)
  }
  const text = await res.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }
  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error
    if (err) throw new ApiError(err.code, err.message_ko, res.status, err.fields, err.details)
    throw new ApiError(`HTTP_${res.status}`, `서버 오류 (${res.status})`, res.status)
  }
  return body as T
}

type Init = RequestInit & { timeoutMs?: number }

export const api = {
  get: <T>(path: string, init?: Init) => fetchJson<T>(path, { ...init, method: "GET" }),
  post: <T>(path: string, body?: unknown, init?: Init) => fetchJson<T>(path, { ...init, method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown, init?: Init) => fetchJson<T>(path, { ...init, method: "PUT", body: JSON.stringify(body) }),
}
