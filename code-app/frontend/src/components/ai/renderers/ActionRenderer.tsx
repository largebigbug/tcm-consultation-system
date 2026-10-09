/**
 * `action` 渲染（批次 5 契约 §3.4 / §9，用户口径 2「默认只读」）。
 *
 * **绝不发起写请求**：按钮只做 `react-router` 跳转；`prefill` 用
 * `navigate(path, { state: { prefill } })` 传递（目标页面若未消费则仅跳转，不报错）。
 * screenId → 路由映射见 `screenRoutes.ts`（19 屏，来自工具清单 §1）。
 */
import { useNavigate } from 'react-router-dom'
import { usePermission } from '../../../stores/userStore'
import { screenPath } from './screenRoutes'
import type { AiActionRenderPayload } from '../../../api/ai'

export default function ActionRenderer({ payload }: { payload: AiActionRenderPayload }) {
  const navigate = useNavigate()
  const hasPerm = usePermission()

  const path = screenPath(payload?.screenId)
  const label = payload?.label || '前往页面'
  const allowed = hasPerm(payload?.permissionCode)

  const go = () => {
    if (!path) return
    if (payload && payload.prefill && Object.keys(payload.prefill).length > 0) {
      navigate(path, { state: { prefill: payload.prefill } })
    } else {
      navigate(path)
    }
  }

  return (
    <div className="ai-action-render">
      <button className="btn btn-primary btn-sm" onClick={go} disabled={!path}>
        {label}
      </button>
      {!path ? <span className="ai-action-warn">未识别的页面标识：{String(payload?.screenId)}</span> : null}
      {path && !allowed ? (
        <span className="ai-action-warn">当前账号无「{payload?.permissionCode}」权限，提交将被拒绝</span>
      ) : null}
      <div className="ai-action-tip">只读模式：AI 不执行写操作，请在页面上确认提交</div>
    </div>
  )
}
