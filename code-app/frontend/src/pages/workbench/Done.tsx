import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'
import { buildWorkbenchQuery, businessLink, workbenchApi, type DoneItem, type WorkbenchFilter } from '../../api/workbench'
import Pagination from '../../components/Pagination'
import { statusBadge } from '../../utils/status'
import { toast } from '../../components/toast'

const EMPTY_FILTER: WorkbenchFilter = { flowName: '', activityName: '', dateFrom: '', dateTo: '', status: '' }

/** 处理结果筛选项（flow_task.action 取值） */
const ACTION_OPTIONS = [
  { code: 'APPROVE', label: '通过' },
  { code: 'REJECT', label: '驳回' },
  { code: 'TERMINATE', label: '终止' },
]

/** 处理结果 → 徽标（沿用既有 Badge 体系；未识别取值回落 statusBadge） */
export function actionBadge(action?: string | null) {
  const code = String(action || '').toUpperCase()
  if (code === 'APPROVE') return { label: '通过', className: 'badge-success' }
  if (code === 'REJECT') return { label: '驳回', className: 'badge-danger' }
  if (code === 'TERMINATE') return { label: '终止', className: 'badge-neutral' }
  if (code === 'TRANSFER') return { label: '转办', className: 'badge-info' }
  if (code === 'URGE') return { label: '催办', className: 'badge-info' }
  return statusBadge(action || '')
}

export default function Done() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [size] = useState(10)
  const [data, setData] = useState<DoneItem[]>([])
  const [total, setTotal] = useState(0)
  const [draft, setDraft] = useState<WorkbenchFilter>(EMPTY_FILTER)
  const [filter, setFilter] = useState<WorkbenchFilter>(EMPTY_FILTER)

  const load = () => {
    workbenchApi
      .done(buildWorkbenchQuery(filter, page, size))
      .then((res) => {
        setData(res.list || [])
        setTotal(res.total || 0)
      })
      .catch((err: any) => toast(err.message, 'error'))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, filter])

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
      {/* 筛选（契约 §6）：处理结果按 action 过滤，分页与 total 由后端 SQL 保证自洽 */}
      <div className="card">
        <div className="toolbar">
          <div className="form-item">
            <label className="field-label">流程名称</label>
            <div className="field-control">
              <input
                id="txtFlowName"
                value={draft.flowName || ''}
                onChange={(e) => setDraft({ ...draft, flowName: e.target.value })}
                placeholder="模糊匹配"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">审批节点</label>
            <div className="field-control">
              <input
                id="txtActivityName"
                value={draft.activityName || ''}
                onChange={(e) => setDraft({ ...draft, activityName: e.target.value })}
                placeholder="模糊匹配"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">开始时间</label>
            <div className="field-control">
              <input
                id="dtpDateFrom"
                type="date"
                value={draft.dateFrom || ''}
                onChange={(e) => setDraft({ ...draft, dateFrom: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">结束时间</label>
            <div className="field-control">
              <input
                id="dtpDateTo"
                type="date"
                value={draft.dateTo || ''}
                onChange={(e) => setDraft({ ...draft, dateTo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">处理结果</label>
            <div className="field-control">
              <select
                id="cboActionStatus"
                value={draft.status || ''}
                onChange={(e) => setDraft({ ...draft, status: e.target.value })}
              >
                <option value="">全部</option>
                {ACTION_OPTIONS.map((o) => (
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
          <h3 style={{ fontWeight: 700 }}>我的已办</h3>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>流程名称</th>
                <th>业务单号</th>
                <th>审批节点</th>
                <th>处理结果</th>
                <th>审批意见</th>
                <th>处理时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => {
                const action = actionBadge(t.action)
                const link = businessLink(t.business_objects, t.business_object_refs, t.prescription_status)
                return (
                  <tr key={t.id}>
                    <td>{t.flow_name || '-'}</td>
                    <td>{t.business_key || '-'}</td>
                    <td>{t.activity_name}</td>
                    <td>
                      <span className={`badge ${action.className}`}>{action.label || '-'}</span>
                    </td>
                    <td>{t.comment || '-'}</td>
                    <td>{t.done_at || '-'}</td>
                    <td>
                      {link ? (
                        <button className="btn btn-secondary btn-sm" onClick={() => navigate(link)} title={link}>
                          <ExternalLink size={14} /> 业务单
                        </button>
                      ) : (
                        <span className="text-secondary">-</span>
                      )}
                    </td>
                  </tr>
                )
              })}
              {data.length === 0 && (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无已办
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
