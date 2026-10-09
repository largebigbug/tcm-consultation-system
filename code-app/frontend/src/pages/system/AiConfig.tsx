import { useEffect, useState } from 'react'
import { RefreshCw, Server } from 'lucide-react'
import { getAiConfig, type AiConfig as AiConfigModel } from '../../api/ai'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/**
 * 配置大模型（批次 6 契约 §5、口径 3）：**只读展示**。
 *
 * - 数据源 `GET /api/ai/config`（仅管理员）；
 * - 只展示 provider / model / base_url / 是否已配置凭据 / 环境变量名 / 启用指引；
 * - **绝不显示、绝不提交任何密钥**；本页无写入口（如需在线改配置另开批次）。
 */
export const DEFAULT_ENV_KEYS = ['AI_PROVIDER', 'AI_MODEL', 'AI_BASE_URL', 'AI_API_KEY']

/** 环境变量 → 中文说明（仅解释用途，不含任何取值） */
export const ENV_KEY_HINTS: Record<string, string> = {
  AI_PROVIDER: '模型服务商标识（如 openai / deepseek 等），覆盖 config.yaml 中的 ai.provider',
  AI_MODEL: '模型名，覆盖 config.yaml 中的 ai.model',
  AI_BASE_URL: '服务地址（OpenAI 兼容接口的 base_url）',
  AI_API_KEY: '访问凭据。仅以环境变量注入，**不落库、不回显、不提交**',
}

export default function AiConfig() {
  const { hasPerm } = useAuth()
  const isAdmin = hasPerm('*')
  const [config, setConfig] = useState<AiConfigModel | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError('')
    getAiConfig()
      .then((data) => setConfig(data))
      .catch((err: any) => {
        setConfig(null)
        const msg = err?.message || '获取大模型配置失败'
        setError(msg)
        toast(msg, 'error')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const envKeys = config?.envKeys && config.envKeys.length > 0 ? config.envKeys : DEFAULT_ENV_KEYS

  const rowStyle: React.CSSProperties = { display: 'flex', gap: 12, marginBottom: 12, alignItems: 'baseline' }
  const labelStyle: React.CSSProperties = { width: 140, flexShrink: 0, color: 'var(--text-secondary)', textAlign: 'right' }
  const valueStyle: React.CSSProperties = { flex: 1, minWidth: 0, wordBreak: 'break-all' }

  if (!isAdmin) {
    return (
      <div className="card">
        <div className="card-title">
          <h3>配置大模型</h3>
        </div>
        <p style={{ color: '#dc2626' }}>无权限查看大模型配置（仅系统管理员可访问）。</p>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <h3>配置大模型（只读）</h3>
          <button className="btn btn-secondary btn-sm" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> 刷新
          </button>
        </div>

        <p className="text-secondary" style={{ marginBottom: 16 }}>
          本页仅展示当前生效配置，<strong>不显示、不接受任何密钥</strong>，也不提供在线修改入口。
        </p>

        {loading && <p className="text-secondary">加载中…</p>}

        {!loading && error && (
          <p style={{ color: '#dc2626' }}>
            获取配置失败：{error}
          </p>
        )}

        {!loading && config && (
          <>
            <div style={rowStyle}>
              <span style={labelStyle}>服务商（provider）</span>
              <span style={valueStyle} id="lblAiProvider">
                {config.provider || '—'}
              </span>
            </div>
            <div style={rowStyle}>
              <span style={labelStyle}>模型（model）</span>
              <span style={valueStyle} id="lblAiModel">
                {config.model || '—'}
              </span>
            </div>
            <div style={rowStyle}>
              <span style={labelStyle}>服务地址（base_url）</span>
              <span style={valueStyle} id="lblAiBaseUrl">
                {config.base_url || '—'}
              </span>
            </div>
            <div style={rowStyle}>
              <span style={labelStyle}>凭据是否已配置</span>
              <span style={valueStyle} id="lblAiConfigured">
                {config.configured ? (
                  <span className="badge badge-success">已配置</span>
                ) : (
                  <span className="badge badge-warning">未配置</span>
                )}
              </span>
            </div>
            {config.hint && (
              <div style={rowStyle}>
                <span style={labelStyle}>提示</span>
                <span style={valueStyle}>{config.hint}</span>
              </div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <div className="card-title">
          <h3>如何启用</h3>
          <span className="text-secondary">通过环境变量注入，服务重启后生效</span>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th style={{ width: 220 }}>环境变量名</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {envKeys.map((key) => (
                <tr key={key}>
                  <td>
                    <code>{key}</code>
                  </td>
                  <td className="text-secondary">{ENV_KEY_HINTS[key] || '启用 AI 对话所需的环境变量'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-secondary mt-16">
          <Server size={14} /> 凭据只允许由运行环境（环境变量）提供；本页与前端代码不保存、不传输任何明文密钥。
        </p>
      </div>
    </div>
  )
}
