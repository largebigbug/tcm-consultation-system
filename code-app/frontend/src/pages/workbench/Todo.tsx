import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, ExternalLink, Inbox, Megaphone, Share2, X } from 'lucide-react'
import {
  assigneeLabel,
  buildWorkbenchQuery,
  businessLink,
  canHandleTask,
  workbenchApi,
  type AssigneeOption,
  type TodoItem,
  type WorkbenchFilter,
} from '../../api/workbench'
import Pagination from '../../components/Pagination'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const EMPTY_FILTER: WorkbenchFilter = { flowName: '', activityName: '', dateFrom: '', dateTo: '' }

export default function Todo() {
  const navigate = useNavigate()
  const { user, permissions } = useAuth()
  const isAdmin = permissions.includes('*')

  const [page, setPage] = useState(1)
  const [size] = useState(10)
  const [data, setData] = useState<TodoItem[]>([])
  const [total, setTotal] = useState(0)
  const [draft, setDraft] = useState<WorkbenchFilter>(EMPTY_FILTER)
  const [filter, setFilter] = useState<WorkbenchFilter>(EMPTY_FILTER)
  const [current, setCurrent] = useState<TodoItem | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  const [transferTarget, setTransferTarget] = useState<TodoItem | null>(null)
  const [options, setOptions] = useState<AssigneeOption[]>([])
  const [assigneeId, setAssigneeId] = useState('')

  const load = async () => {
    try {
      const res = await workbenchApi.todo(buildWorkbenchQuery(filter, page, size))
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

  const onSearch = () => {
    setPage(1)
    setFilter({ ...draft })
  }

  const onReset = () => {
    setDraft(EMPTY_FILTER)
    setFilter({ ...EMPTY_FILTER })
    setPage(1)
  }

  const open = (t: TodoItem) => {
    setCurrent(t)
    setComment('')
  }

  /** 审批动作：**只有「通过」与「驳回」**（D-25：退回等同驳回，前端不提供退回） */
  const doAction = async (action: 'approve' | 'reject') => {
    if (!current) return
    if (action === 'reject' && !comment.trim()) {
      toast('驳回时必须填写审批意见', 'error')
      return
    }
    setBusy(true)
    try {
      if (action === 'approve') await workbenchApi.approve(current.id, comment)
      else await workbenchApi.reject(current.id, comment)
      toast(action === 'approve' ? '审批通过' : '已驳回')
      setCurrent(null)
      load()
    } catch (err: any) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const onUrge = async (t: TodoItem) => {
    try {
      await workbenchApi.urge(t.id)
      toast('已催办')
      load()
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const openTransfer = async (t: TodoItem) => {
    setTransferTarget(t)
    setAssigneeId('')
    try {
      const opts = await workbenchApi.assigneeOptions()
      setOptions(opts || [])
    } catch (err: any) {
      setOptions([])
      toast(err.message, 'error')
    }
  }

  const doTransfer = async () => {
    if (!transferTarget) return
    if (!assigneeId) {
      toast('请选择转办对象', 'error')
      return
    }
    setBusy(true)
    try {
      await workbenchApi.transfer(transferTarget.id, Number(assigneeId))
      toast('已转办')
      setTransferTarget(null)
      load()
    } catch (err: any) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {/* 筛选（契约 §6）：参数下发后端 SQL，前端不做过滤，保证与 total 自洽 */}
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
          <h3 style={{ fontWeight: 700 }}>我的待办</h3>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>流程名称</th>
                <th>业务单号</th>
                <th>审批节点</th>
                <th>提交时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => {
                const allowed = canHandleTask(t, user, isAdmin)
                const link = businessLink(t.business_objects, t.business_object_refs, t.prescription_status)
                return (
                  <tr key={t.id}>
                    <td>{t.flow_name || '-'}</td>
                    <td>{t.business_key || '-'}</td>
                    <td>{t.activity_name}</td>
                    <td>{t.started_at || t.created_at || '-'}</td>
                    <td>
                      <div className="toolbar">
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={!allowed}
                          onClick={() => open(t)}
                          title={allowed ? '处理该任务' : '该任务不属于当前用户'}
                        >
                          <Inbox size={14} /> 处理
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          id={`btnTransfer-${t.id}`}
                          disabled={!allowed}
                          onClick={() => openTransfer(t)}
                        >
                          <Share2 size={14} /> 转办
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          id={`btnUrge-${t.id}`}
                          disabled={!allowed}
                          onClick={() => onUrge(t)}
                        >
                          <Megaphone size={14} /> 催办
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
                  <td colSpan={5} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无待办
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

      <Modal
        title="审批处理"
        open={!!current}
        onClose={() => setCurrent(null)}
        footer={
          <>
            {/* D-25：退回等同驳回 → 只保留「驳回」「通过」两个按钮（前端不提供「退回」） */}
            <button className="btn btn-danger" onClick={() => doAction('reject')} disabled={busy}>
              <X size={14} /> 驳回
            </button>
            <button className="btn btn-primary" onClick={() => doAction('approve')} disabled={busy}>
              <Check size={14} /> 通过
            </button>
          </>
        }
      >
        <p className="text-secondary" style={{ marginBottom: 12 }}>
          流程：{current?.flow_name || '-'}（{current?.business_key}） · 节点：{current?.activity_name}
        </p>
        <div className="prop-row">
          <label>审批意见</label>
          <textarea
            id="txaComment"
            rows={3}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="驳回时必填"
          />
        </div>
      </Modal>

      <Modal
        title="转办"
        open={!!transferTarget}
        onClose={() => setTransferTarget(null)}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setTransferTarget(null)} disabled={busy}>
              取消
            </button>
            <button className="btn btn-primary" onClick={doTransfer} disabled={busy}>
              <Share2 size={14} /> 确认转办
            </button>
          </>
        }
      >
        <p className="text-secondary" style={{ marginBottom: 12 }}>
          将任务「{transferTarget?.activity_name}」（{transferTarget?.business_key}）转给其他办理人：
        </p>
        <div className="prop-row">
          <label>转办对象</label>
          <select id="cboAssignee" value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
            <option value="">请选择…</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {assigneeLabel(o)}
              </option>
            ))}
          </select>
        </div>
      </Modal>
    </div>
  )
}
