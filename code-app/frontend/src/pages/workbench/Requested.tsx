import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ExternalLink, Eye } from 'lucide-react'
import {
  buildWorkbenchQuery,
  businessLink,
  workbenchApi,
  type RequestedItem,
  type WorkbenchFilter,
} from '../../api/workbench'
import { flowApi } from '../../api/flow'
import Pagination from '../../components/Pagination'
import { toast } from '../../components/toast'
import { Badge } from '../../utils/status'

const EMPTY_FILTER: WorkbenchFilter = { status: '' }

/** 实例状态筛选（契约 §6：RUNNING / APPROVED / REJECTED / TERMINATED 四态） */
export const INSTANCE_STATUS_OPTIONS = [
  { code: 'RUNNING', label: '运行中' },
  { code: 'APPROVED', label: '已通过' },
  { code: 'REJECTED', label: '已驳回' },
  { code: 'TERMINATED', label: '已终止' },
]

/** 解析 current_activity_ids（JSON 数组串 / 裸串）→ 活动 id 列表 */
export function parseActivities(raw: string | null | undefined): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map((x) => String(x))
  } catch {
    // 非 JSON，按原文展示
  }
  return [String(raw)]
}

/** 活动 id → 活动名（缺映射时回落 id），多个活动以「、」连接 */
export function formatActivities(raw: string | null | undefined, nameMap?: Record<string, string>): string {
  const ids = parseActivities(raw)
  if (ids.length === 0) return '-'
  return ids.map((id) => nameMap?.[id] || id).join('、')
}

export default function Requested() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [size] = useState(10)
  const [data, setData] = useState<RequestedItem[]>([])
  const [total, setTotal] = useState(0)
  const [draft, setDraft] = useState<WorkbenchFilter>(EMPTY_FILTER)
  const [filter, setFilter] = useState<WorkbenchFilter>(EMPTY_FILTER)
  /** def_id → (活动 id → 活动名)，用于把 current_activity_ids 显示成活动名 */
  const [nodeNames, setNodeNames] = useState<Record<number, Record<string, string>>>({})

  const load = async () => {
    try {
      const res = await workbenchApi.requested(buildWorkbenchQuery(filter, page, size))
      setData(res.list || [])
      setTotal(res.total || 0)
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, filter])

  // 当前节点：current_activity_ids → 活动名（按 def_id 缓存流程图里的节点名；取不到时回落 id）
  useEffect(() => {
    const missing = Array.from(new Set(data.map((r) => Number(r.def_id)))).filter((id) => id && !nodeNames[id])
    if (missing.length === 0) return
    let cancelled = false
    Promise.all(
      missing.map((id) =>
        flowApi
          .getGraph(id)
          .then((g) => [id, g] as const)
          .catch(() => [id, null] as const),
      ),
    ).then((pairs) => {
      if (cancelled) return
      setNodeNames((prev) => {
        const next = { ...prev }
        pairs.forEach(([id, g]) => {
          const map: Record<string, string> = {}
          const nodes: any[] = (g && (g.nodes || (g.node_graph && g.node_graph.nodes))) || []
          nodes.forEach((n) => {
            if (n && n.id) map[String(n.id)] = String(n.name || n.label || n.id)
          })
          next[id] = map
        })
        return next
      })
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const onSearch = () => {
    setPage(1)
    setFilter({ ...draft })
  }

  const onReset = () => {
    setDraft(EMPTY_FILTER)
    setFilter({ ...EMPTY_FILTER })
    setPage(1)
  }

  return (
    <div>
      {/* 筛选（契约 §6）：流程状态四态 */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">流程状态</label>
            <div className="field-control">
              <select
                id="cboInstanceStatus"
                value={draft.status || ''}
                onChange={(e) => setDraft({ ...draft, status: e.target.value })}
              >
                <option value="">全部</option>
                {INSTANCE_STATUS_OPTIONS.map((o) => (
                  <option key={o.code} value={o.code}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn btn-primary btn-sm" onClick={onSearch}>
            查询
          </button>
          <button className="btn btn-secondary btn-sm" onClick={onReset}>
            重置
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--divider-color)' }}>
          <h3 style={{ fontWeight: 700 }}>我的申请</h3>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>流程名称</th>
                <th>业务单号</th>
                <th>流程状态</th>
                <th>当前节点</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => {
                const link = businessLink(row.business_objects, row.business_object_refs, row.prescription_status)
                return (
                  <tr key={row.id}>
                    <td>{row.flow_name || '-'}</td>
                    <td>{row.business_key || '-'}</td>
                    <td>
                      <Badge status={row.status} />
                    </td>
                    <td>{formatActivities(row.current_activity_ids, nodeNames[Number(row.def_id)])}</td>
                    <td>{row.started_at || '-'}</td>
                    <td>{row.ended_at || '-'}</td>
                    <td>
                      <div className="toolbar">
                        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/flow/instances')}>
                          <Eye size={14} /> 查看
                        </button>
                        {link && (
                          <button className="btn btn-secondary btn-sm" onClick={() => navigate(link)} title={link}>
                            <ExternalLink size={14} /> 业务单
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
              {data.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无申请
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div style={{ padding: '14px 20px', display: 'flex', justifyContent: 'flex-end' }}>
          <Pagination page={page} size={size} total={total} onChange={setPage} />
        </div>
      </div>
    </div>
  )
}
