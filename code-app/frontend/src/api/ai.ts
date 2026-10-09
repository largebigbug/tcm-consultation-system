/**
 * AI 对话接口（批次 5 · 契约 §3.1 / §3.2 / §3.3）。
 *
 * 说明：
 * - `getAiStatus()` 走 `GET /api/ai/status`（普通 JSON，统一响应体）。
 * - `chatStream()` 走 `POST /api/ai/chat`（`text/event-stream`）。既有 `src/api/request.ts`
 *   的 `request()` 用 `res.json()` 一次性解析、**不支持流式**，故本文件自行 `fetch` +
 *   `ReadableStream` 逐片解析 SSE；鉴权沿用 `request.ts` 导出的 `getToken()`
 *   （token 存于 `localStorage['cp_token']`），请求头 `Authorization: Bearer <token>`。
 * - 本文件不修改 `request.ts`。
 */
import { getToken, http } from './request'

const BASE = '/api'

/* ========================= 类型 ========================= */

/** `GET /api/ai/status` 的 data（契约 §3.1） */
export interface AiStatus {
  enabled: boolean
  provider: string
  model: string
  configured: boolean
  hint: string
}

export interface AiChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** `POST /api/ai/chat` 请求体（契约 §3.2） */
export interface AiChatBody {
  message: string
  history: AiChatMessage[]
  context?: { screenId?: string }
}

export type AiRenderType = 'text' | 'table' | 'chart' | 'action'

export interface AiTextRenderPayload {
  text: string
}

export interface AiTableColumn {
  name: string
  label: string
}

/** 契约 §3.4 `table` */
export interface AiTableRenderPayload {
  columns: AiTableColumn[]
  rows: Record<string, any>[]
  total: number
  truncated: boolean
}

export type AiChartType = 'bar' | 'line' | 'pie'

/** 契约 §3.4 `chart` */
export interface AiChartRenderPayload {
  chartType: AiChartType
  xField: string
  yField: string
  rows: Record<string, any>[]
  title?: string
}

/** 契约 §3.4 `action`（只读：仅跳转 + 预填，不发起写请求） */
export interface AiActionRenderPayload {
  type: 'navigate'
  screenId: string
  behaviorId: string
  label: string
  prefill?: Record<string, any>
  permissionCode: string
}

export interface AiRenderPayload {
  renderType: AiRenderType
  payload: AiTextRenderPayload | AiTableRenderPayload | AiChartRenderPayload | AiActionRenderPayload
}

export type AiSseEventType =
  | 'message_start'
  | 'delta'
  | 'tool_call'
  | 'tool_result'
  | 'render_payload'
  | 'message_end'
  | 'error'

export interface AiSseEvent {
  type: AiSseEventType
  data: any
}

/* ========================= 通用 ========================= */

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

/** 尽量从统一响应体里取后端中文提示，取不到则用兜底文案 */
async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) {
      const body = await res.json()
      if (body && typeof body.message === 'string' && body.message) return body.message
    } else {
      const text = await res.text()
      if (text && text.length <= 200 && !text.includes('<')) return text
    }
  } catch {
    /* 非 JSON / 已消费的响应体，保留兜底提示 */
  }
  return fallback
}

/* ========================= GET /api/ai/status ========================= */

/**
 * 查询 AI 对话启用状态（契约 §3.1）。
 * 正常返回 `enabled/configured` 供页面渲染「未启用态」；
 * 网络异常 / 401 / 非 2xx 一律抛中文 Error，由组件渲染中文错误条。
 */
export async function getAiStatus(): Promise<AiStatus> {
  let res: Response
  try {
    res = await fetch(`${BASE}/ai/status`, {
      method: 'GET',
      headers: authHeaders({ Accept: 'application/json' }),
    })
  } catch {
    throw new Error('无法连接服务，请确认后端已启动')
  }
  if (res.status === 401) throw new Error('登录已过期，请重新登录')
  if (!res.ok) throw new Error(await readError(res, `获取 AI 状态失败（HTTP ${res.status}）`))
  let body: any
  try {
    body = await res.json()
  } catch {
    throw new Error('AI 状态响应格式不正确')
  }
  if (!body || body.success !== true || !body.data) {
    throw new Error((body && body.message) || '获取 AI 状态失败')
  }
  return body.data as AiStatus
}

/* ========================= GET /api/ai/config（批次 6 契约 §5，仅管理员、只读） ========================= */

/**
 * `GET /api/ai/config` 的 data：**只读展示**，绝不包含任何密钥。
 * `envKeys` 为启用 AI 所需的环境变量名（名称，不是值）。
 */
export interface AiConfig {
  provider: string
  model: string
  base_url: string
  configured: boolean
  envKeys: string[]
  hint: string
}

/**
 * 查询当前大模型生效配置（契约 §3、§5 口径 3）。
 * 仅管理员可访问；非管理员由后端拒绝（403 / 中文），此处原样抛中文 Error。
 */
export function getAiConfig(): Promise<AiConfig> {
  return http.get<AiConfig>('/ai/config')
}

/* ========================= SSE 解析 ========================= */

/** 找到缓冲区中最早出现的 SSE 事件分隔符（`\n\n` 或 `\r\n\r\n`） */
function findBoundary(s: string): { index: number; length: number } | null {
  const lf = s.indexOf('\n\n')
  const crlf = s.indexOf('\r\n\r\n')
  if (lf === -1 && crlf === -1) return null
  if (crlf === -1) return { index: lf, length: 2 }
  if (lf === -1) return { index: crlf, length: 4 }
  return crlf < lf ? { index: crlf, length: 4 } : { index: lf, length: 2 }
}

function parseBlock(block: string): AiSseEvent | null {
  let eventName = 'message'
  const dataLines: string[] = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line || line.startsWith(':')) continue
    const idx = line.indexOf(':')
    const field = idx === -1 ? line : line.slice(0, idx)
    let value = idx === -1 ? '' : line.slice(idx + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') eventName = value
    else if (field === 'data') dataLines.push(value)
  }
  if (dataLines.length === 0) return null
  const raw = dataLines.join('\n')
  let data: any = { raw }
  try {
    data = JSON.parse(raw)
  } catch {
    data = { raw }
  }
  return { type: eventName as AiSseEventType, data }
}

export interface SseParser {
  /** 追加一个网络分片（可能切断事件），返回本次已凑齐的完整事件 */
  push(chunk: string): AiSseEvent[]
  /** 流结束时冲刷残留缓冲区 */
  flush(): AiSseEvent[]
}

/** 逐片 SSE 解析器：容忍事件被任意切分（含 CRLF / LF 混用） */
export function createSseParser(): SseParser {
  let buffer = ''
  return {
    push(chunk: string): AiSseEvent[] {
      buffer += chunk
      const out: AiSseEvent[] = []
      for (;;) {
        const b = findBoundary(buffer)
        if (!b) break
        const block = buffer.slice(0, b.index)
        buffer = buffer.slice(b.index + b.length)
        const evt = parseBlock(block)
        if (evt) out.push(evt)
      }
      return out
    },
    flush(): AiSseEvent[] {
      const rest = buffer
      buffer = ''
      const trimmed = rest.trim()
      if (!trimmed) return []
      const evt = parseBlock(trimmed)
      return evt ? [evt] : []
    },
  }
}

/** 是否为用户主动中断（AbortController.abort()） */
export function isAbortError(err: unknown): boolean {
  const e = err as any
  return !!e && (e.name === 'AbortError' || e.code === 20)
}

/* ========================= POST /api/ai/chat (SSE) ========================= */

export type AiEventHandler = (event: AiSseEvent) => void

/**
 * 发起流式对话（契约 §3.2 / §3.3）。
 *
 * - 逐片读取 `ReadableStream`，用 `TextDecoder(stream:true)` 解 UTF-8（中文不会被切断）；
 * - 每个完整 SSE 事件立即回调 `onEvent`；
 * - `signal` 供「停止」按钮使用：abort 后 promise 以 AbortError 拒绝（用 `isAbortError` 判定）；
 * - 未启用（503）或非事件流响应 → 抛中文 Error，由组件渲染中文错误条。
 */
export async function chatStream(
  body: AiChatBody,
  onEvent: AiEventHandler,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/ai/chat`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
    body: JSON.stringify(body),
    signal,
  })

  if (res.status === 401) throw new Error('登录已过期，请重新登录')
  if (res.status === 403) throw new Error(await readError(res, '无权限使用 AI 对话'))
  if (res.status === 503) throw new Error(await readError(res, 'AI 对话未启用'))
  if (!res.ok) throw new Error(await readError(res, `对话请求失败（HTTP ${res.status}）`))

  const ct = res.headers.get('content-type') || ''
  if (!ct.includes('text/event-stream')) {
    throw new Error(await readError(res, '对话请求未返回事件流'))
  }
  if (!res.body) throw new Error('当前环境不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = createSseParser()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      const text = decoder.decode(value, { stream: true })
      if (!text) continue
      for (const evt of parser.push(text)) onEvent(evt)
    }
    const tail = decoder.decode()
    const events = tail ? [...parser.push(tail), ...parser.flush()] : parser.flush()
    for (const evt of events) onEvent(evt)
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* 已释放，忽略 */
    }
  }
}
