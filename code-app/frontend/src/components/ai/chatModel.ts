/**
 * 对话界面纯逻辑（无 React 依赖，便于离线自测）。
 *
 * - `applyEvent`：把一条 SSE 事件归约到某条 AI 消息上（四类渲染的分派就在此处）；
 * - 历史对话仅前端内存（契约 §9：≤10 轮，刷新即清空，不使用 localStorage）；
 * - `text` 渲染不引入 markdown：按段落/换行处理，见 `appendText` 的收敛规则。
 */
import type { AiChatMessage, AiRenderPayload, AiSseEvent } from '../../api/ai'

export type AiMessageStatus = 'streaming' | 'tool' | 'done' | 'error' | 'stopped'

export interface AiToolCallInfo {
  toolCallId: string
  name: string
  ok?: boolean
  summary?: string
  error?: string
  /** 是否已收到 tool_result（用于「正在查询…」状态判定） */
  finished?: boolean
}

export interface AiUiMessage {
  id: string
  role: 'user' | 'assistant'
  /** 流式累积的正文（delta 累加；`text` render_payload 按 appendText 收敛） */
  content: string
  /** table / chart / action 三类结构化渲染，按到达顺序 */
  renders: AiRenderPayload[]
  toolCalls: AiToolCallInfo[]
  status: AiMessageStatus
  error?: string
}

/** 一轮历史 = 1 条 user + 1 条 assistant */
export const MAX_TURNS = 10

export function createUserMessage(id: string, content: string): AiUiMessage {
  return { id, role: 'user', content, renders: [], toolCalls: [], status: 'done' }
}

export function createAssistantMessage(id: string): AiUiMessage {
  return { id, role: 'assistant', content: '', renders: [], toolCalls: [], status: 'streaming' }
}

/**
 * 正文收敛：delta 分片与 `text` 型 render_payload 可能表达同一段文字，避免重复。
 * - 新文本已包含于旧文本末尾 → 忽略；
 * - 新文本以旧文本开头（后端回吐全文）→ 用新文本替换；
 * - 否则追加。
 */
export function appendText(prev: string, next: string): string {
  if (!next) return prev
  if (!prev) return next
  if (prev.endsWith(next)) return prev
  if (next.startsWith(prev)) return next
  return prev + next
}

/** 把一条 SSE 事件归约到 AI 消息（四类渲染分派 + 工具状态） */
export function applyEvent(msg: AiUiMessage, evt: AiSseEvent): AiUiMessage {
  const data = evt?.data || {}
  switch (evt.type) {
    case 'message_start':
      return msg

    case 'delta': {
      const text = String(data.text ?? '')
      if (!text) return msg
      return { ...msg, content: msg.content + text, status: msg.status === 'tool' ? 'tool' : 'streaming' }
    }

    case 'tool_call': {
      const name = String(data.name ?? 'tool')
      const toolCallId = String(data.toolCallId ?? name)
      return {
        ...msg,
        status: 'tool',
        toolCalls: [...msg.toolCalls, { toolCallId, name, finished: false }],
      }
    }

    case 'tool_result': {
      const toolCallId = String(data.toolCallId ?? '')
      const info: AiToolCallInfo = {
        toolCallId,
        name: '',
        ok: !!data.ok,
        summary: String(data.summary ?? ''),
        error: data.error ? String(data.error) : undefined,
        finished: true,
      }
      let matched = false
      const toolCalls = msg.toolCalls.map((t) => {
        if (t.toolCallId !== toolCallId) return t
        matched = true
        return { ...t, ...info, name: t.name }
      })
      if (!matched) toolCalls.push(info)
      return { ...msg, status: 'streaming', toolCalls }
    }

    case 'render_payload': {
      const renderType = data.renderType
      const payload = data.payload
      if (!renderType || !payload) return msg
      if (renderType === 'text') {
        const text = String(payload.text ?? '')
        if (!text) return msg
        return { ...msg, content: appendText(msg.content, text) }
      }
      return { ...msg, renders: [...msg.renders, { renderType, payload } as AiRenderPayload] }
    }

    case 'message_end': {
      const finishReason = String(data.finishReason ?? 'stop')
      if (finishReason === 'error') {
        return { ...msg, status: 'error', error: msg.error || 'AI 返回异常，请稍后重试' }
      }
      return { ...msg, status: 'done' }
    }

    case 'error':
      return { ...msg, status: 'error', error: String(data.message ?? 'AI 服务异常，请稍后重试') }

    default:
      return msg
  }
}

/** 仅保留最近 maxTurns 轮（≤20 条消息）；刷新即清空 */
export function capTurns(messages: AiUiMessage[], maxTurns = MAX_TURNS): AiUiMessage[] {
  const max = maxTurns * 2
  return messages.length > max ? messages.slice(messages.length - max) : messages
}

/** 构造请求体 history（≤10 轮，不含本轮问题） */
export function buildHistory(messages: AiUiMessage[], maxTurns = MAX_TURNS): AiChatMessage[] {
  const kept = capTurns(messages, maxTurns)
  return kept.map((m) => ({
    role: m.role,
    content: m.content && m.content.trim() ? m.content : m.role === 'assistant' ? '（已返回结构化结果）' : '',
  }))
}

/** 流式中（含工具调用中）状态判定：用于禁用重复发送 */
export function isBusy(msg: AiUiMessage): boolean {
  return msg.status === 'streaming' || msg.status === 'tool'
}
