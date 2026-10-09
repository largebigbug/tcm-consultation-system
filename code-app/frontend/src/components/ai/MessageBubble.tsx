/**
 * 消息气泡（批次 5 契约 §9）：
 * - 用户消息右对齐（品牌蓝底白字）、AI 消息左对齐（白底）；
 * - `text` 按段落/换行渲染（不引入 markdown 依赖）；
 * - `tool_call` 期间显示「正在查询…」；
 * - `table / chart / action` 交由对应 renderer；
 * - `error` 事件以中文错误条展示。
 */
import TableRenderer from './renderers/TableRenderer'
import ChartRenderer from './renderers/ChartRenderer'
import ActionRenderer from './renderers/ActionRenderer'
import type { AiUiMessage } from './chatModel'
import type {
  AiActionRenderPayload,
  AiChartRenderPayload,
  AiTableRenderPayload,
} from '../../api/ai'

/** 段落渲染：按换行切分，空行不产生空段落 */
export function splitParagraphs(text: string): string[] {
  return String(text || '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l !== '')
}

function RenderBlock({ render }: { render: AiUiMessage['renders'][number] }) {
  if (render.renderType === 'table') {
    return <TableRenderer payload={render.payload as AiTableRenderPayload} />
  }
  if (render.renderType === 'chart') {
    return <ChartRenderer payload={render.payload as AiChartRenderPayload} />
  }
  if (render.renderType === 'action') {
    return <ActionRenderer payload={render.payload as AiActionRenderPayload} />
  }
  return null
}

export default function MessageBubble({ message }: { message: AiUiMessage }) {
  const isUser = message.role === 'user'
  const paragraphs = splitParagraphs(message.content)
  const toolPending = message.status === 'tool'

  return (
    <div className={`ai-msg ${isUser ? 'ai-msg-user' : 'ai-msg-assistant'}`}>
      <div className="ai-msg-bubble">
        {paragraphs.map((p, i) => (
          <p key={i} className="ai-msg-paragraph">
            {p}
          </p>
        ))}

        {toolPending ? <div className="ai-msg-tool">正在查询…</div> : null}

        {message.toolCalls.map((t, i) => (
          <div key={`${t.toolCallId}-${i}`} className={`ai-tool-chip ${t.ok === false ? 'is-error' : ''}`}>
            <span className="ai-tool-name">{t.name || t.toolCallId}</span>
            {t.finished ? (
              <span className="ai-tool-summary">
                {t.ok === false ? `被拒绝：${t.error || '无权限执行该操作'}` : t.summary || '已完成'}
              </span>
            ) : (
              <span className="ai-tool-summary">执行中…</span>
            )}
          </div>
        ))}

        {message.renders.map((r, i) => (
          <div key={`${r.renderType}-${i}`} className="ai-render-block">
            <RenderBlock render={r} />
          </div>
        ))}

        {message.status === 'error' && message.error ? (
          <div className="ai-error-bar">{message.error}</div>
        ) : null}
        {message.status === 'stopped' ? <div className="ai-stopped-bar">已停止生成</div> : null}
      </div>
    </div>
  )
}
