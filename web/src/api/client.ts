import type { BaseResult } from '../types/api'

const configuredBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
export const API_BASE_URL = (configuredBase || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  status?: number
  code?: string | number
  detail?: string

  constructor(message: string, options: { status?: number; code?: string | number; detail?: string } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.detail = options.detail
  }
}

function textValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

export async function apiErrorFromResponse(response: Response, fallback = 'Request failed'): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`.trim() || fallback
  let code: string | number | undefined
  let detail: string | undefined

  try {
    const payload = (await response.json()) as {
      code?: string | number
      message?: string
      detail?: string | { code?: string | number; message?: string; detail?: string }
    }
    code = payload.code
    message = textValue(payload.message) || message
    if (typeof payload.detail === 'string') {
      message = textValue(payload.detail) || message
    } else if (payload.detail && typeof payload.detail === 'object') {
      code = payload.detail.code ?? code
      message = textValue(payload.detail.message) || message
      detail = textValue(payload.detail.detail)
    }
  } catch {
    // Keep the HTTP fallback message when no JSON error body exists.
  }

  return new ApiError(message || fallback, { status: response.status, code, detail })
}

export function apiUrl(path: string, params?: Record<string, string | number | undefined | null>): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(`${API_BASE_URL}${normalizedPath}`, window.location.origin)
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.toString()
}

export function getApiKey(): string {
  return localStorage.getItem('deepdesk.apiKey')?.trim() || (import.meta.env.VITE_API_KEY as string | undefined)?.trim() || ''
}

export function authHeaders(): Record<string, string> {
  const token = getApiKey()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  for (const [key, value] of Object.entries(authHeaders())) headers.set(key, value)
  return fetch(apiUrl(path), { ...init, headers })
}

export async function requestJson<T>(
  path: string,
  options: RequestInit & { params?: Record<string, string | number | undefined | null> } = {},
): Promise<T> {
  const { params, ...init } = options
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  for (const [key, value] of Object.entries(authHeaders())) headers.set(key, value)

  const response = await fetch(apiUrl(path, params), { ...init, headers })
  if (!response.ok) throw await apiErrorFromResponse(response)
  return (await response.json()) as T
}

export async function requestResult<T>(
  path: string,
  options: RequestInit & { params?: Record<string, string | number | undefined | null> } = {},
): Promise<T> {
  const result = await requestJson<BaseResult<T>>(path, options)
  if (result.code !== 200 || result.data === null) {
    throw new ApiError(result.message || 'Request failed', { code: result.code })
  }
  return result.data
}
