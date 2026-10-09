/**
 * 右侧 AI 对话面板（批次 5 契约 §9）。
 *
 * - 消息区 + 输入区；`Enter` 发送 / `Shift+Enter` 换行；
 * - 流式（含工具调用）期间禁用重复发送，并显示「停止」按钮（AbortController）；
 * - `GET /api/ai/status` 返回 enabled:false / configured:false → 展示中文 hint + 「重试」按钮，输入区禁用；
 * - 未启用/取状态失败时**自动重试一次**，且从别的标签页切回时再查一次（服务刚重启/页面停留过久可自愈）；
 * - 历史仅前端内存（≤10 轮），刷新即清空，不使用 localStorage；
 * - 发送时把当前页面作为 `context.screenId` 上报（若识别得到）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { chatStream, getAiStatus, isAbortError } from '../../api/ai'
import type { AiSseEvent, AiStatus } from '../../api/ai'
import { screenIdByPath } from './renderers/screenRoutes'
import MessageBubble from './MessageBubble'
import {
  applyEvent,
  buildHistory,
  capTurns,
  createAssistantMessage,
  createUserMessage,
  isBusy,
} from './chatModel'
import type { AiUiMessage } from './chatModel'
import './ai-chat.css'

export default function AiChatPanel() {
  const location = useLocation()
  const [messages, setMessages] = useState<AiUiMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [statusErr, setStatusErr] = useState('')
  const [statusLoading, setStatusLoading] = useState(true)

  const ctrlRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const seqRef = useRef(0)
  const autoRetriedRef = useRef(false)   // 「未启用/失败」只自动重试一次，避免死循环
  const nextId = () => `ai-${Date.now()}-${++seqRef.current}`

  const loadStatus = useCallback(() => {
    setStatusLoading(true)
    setStatusErr('')
    getAiStatus()
      .then((s) => setStatus(s))
      .catch((e: any) => {
        setStatus(null)
        setStatusErr(e?.message || '获取 AI 状态失败')
      })
      .finally(() => setStatusLoading(false))
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  // 卸载时中断未完成的流
  useEffect(() => () => ctrlRef.current?.abort(), [])

  // 新消息到达时滚到底部
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const notEnabled = !!status && (!status.enabled || !status.configured)
  const inputDisabled = statusLoading || !!statusErr || !status || status.enabled !== true || status.configured !== true

  const busy = streaming || messages.some((m) => m.role === 'assistant' && isBusy(m))

  // 自愈 1：未启用或取状态失败 → 2.5s 后自动重试一次（服务重启、页面停留过久时不至于一直卡在旧状态）
  useEffect(() => {
    if (statusLoading || (!notEnabled && !statusErr) || autoRetriedRef.current) return
    autoRetriedRef.current = true
    const timer = setTimeout(() => loadStatus(), 2500)
    return () => clearTimeout(timer)
  }, [statusLoading, notEnabled, statusErr, loadStatus])

  // 自愈 2：从别的标签页切回来时，若仍是「未启用/失败」态就再查一次
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === 'visible' && (notEnabled || statusErr)) loadStatus()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [notEnabled, statusErr, loadStatus])

  const patchAssistant = useCallback((id: string, evt: AiSseEvent) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? applyEvent(m, evt) : m)))
  }, [])

  const stop = () => {
    ctrlRef.current?.abort()
  }

  const send = async () => {
    const text = input.trim()
    if (!text || busy || inputDisabled) return

    const history = buildHistory(messages)
    const userMsg = createUserMessage(nextId(), text)
    const aiMsg = createAssistantMessage(nextId())

    setMessages((prev) => capTurns([...prev, userMsg, aiMsg]))
    setInput('')
    setStreaming(true)

    const screenId = screenIdByPath(location.pathname)
    const body = { message: text, history, context: screenId ? { screenId } : undefined }

    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    try {
      await chatStream(body, (evt) => patchAssistant(aiMsg.id, evt), ctrl.signal)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMsg.id && (m.status === 'streaming' || m.status === 'tool')
            ? { ...m, status: 'done' }
            : m,
        ),
      )
    } catch (err: any) {
      if (isAbortError(err)) {
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsg.id && isBusy(m) ? { ...m, status: 'stopped' } : m)),
        )
      } else {
        const message = err?.message || '对话失败，请稍后重试'
        setMessages((prev) =>
          prev.map((m) => (m.id === aiMsg.id ? { ...m, status: 'error', error: message } : m)),
        )
      }
    } finally {
      ctrlRef.current = null
      setStreaming(false)
      setMessages((prev) => capTurns(prev))
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void send()
    }
  }

  const banner = useMemo(() => {
    if (statusLoading) return <div className="ai-status-bar">正在检查 AI 对话状态…</div>
    if (statusErr) {
      return (
        <div className="ai-status-bar is-error">
          <span>{statusErr}</span>
          <button className="btn btn-secondary btn-sm" onClick={loadStatus}>
            重试
          </button>
        </div>
      )
    }
    if (notEnabled) {
      return (
        <div className="ai-status-bar is-warn">
          <span>{status?.hint || 'AI 对话未启用'}</span>
          <button className="btn btn-secondary btn-sm" onClick={loadStatus}>
            重试
          </button>
        </div>
      )
    }
    return null
  }, [statusLoading, statusErr, notEnabled, status, loadStatus])

  return (
    <div className="ai-chat-body">
      {banner}

      <div className="ai-msg-list" ref={listRef}>
        {messages.length === 0 && !banner ? (
          <div className="ai-empty">
            <p>我是中医问诊系统智能助理（只读）。</p>
            <p className="ai-empty-hint">
              可以问我「本月门诊量多少」「饮片库存预警有哪些」，或让我引导你到某个页面录入。
            </p>
          </div>
        ) : null}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
      </div>

      <div className="ai-input-area">
        <textarea
          className="ai-input"
          rows={3}
          placeholder={inputDisabled ? 'AI 对话未启用' : '请输入问题，Enter 发送 / Shift+Enter 换行'}
          value={input}
          disabled={inputDisabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="ai-input-actions">
          <span className="ai-input-hint">Enter 发送 · Shift+Enter 换行</span>
          {busy ? (
            <button className="btn btn-secondary btn-sm" onClick={stop}>
              停止
            </button>
          ) : (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => void send()}
              disabled={inputDisabled || !input.trim()}
            >
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
