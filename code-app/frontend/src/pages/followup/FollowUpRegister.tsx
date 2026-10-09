/**
 * UI-11 复诊随访登记（frmFollowUp，LIST_MAINTENANCE）—— 批次 3 子代理 B。
 *
 * 契约：`docs/批次3-实现契约.md` §5（屏结构/接口/权限）、§7（前端契约）。
 * MU：`docs/批次3-屏幕规格（MU抽取）.md` frmFollowUp（25 元素 / 4 动作），元素 id 已落到控件 `id` 上。
 *
 * 接口（批次 2 已实现，本批加权限交叉）：
 *   GET  /api/followup                       列表（follow_up:complete 或 follow_up:query-completion）
 *   GET  /api/followup/<id>                  详情
 *   POST /api/followup/<id>/complete         评价（follow_up:complete；实际随访日期与本次就诊必填）
 *   POST /api/followup/<id>/mark-lost        标记失访（follow_up:mark-lost；二次确认 + 失访原因必填）
 *   导出 RPT-FOLLOWUP-COMPLETION-001（follow_up:query-completion）走 downloadReport（带 Bearer 头 fetch）
 *
 * 权限：无 `follow_up:complete` 的账号（如科室管理员 keshi）可查询/导出，但「评价」「标记失访」置灰并提示。
 * 后端校验失败（如「计划随访日期尚未超期，不可标记失访」）一律 toast 原样展示中文提示，前端不自造文案。
 */
import { useEffect, useMemo, useState } from 'react'
import { Check, Download, Search, UserX, X } from 'lucide-react'
import { followupApi, type FollowUp } from '../../api/followup'
import { DICT, dictLabel, metaApi, type DictItem, type DictionaryMap } from '../../api/meta'
import { http } from '../../api/request'
import { REPORT, downloadReport, type ReportColumn } from '../../api/report'
import Pagination from '../../components/Pagination'
import ReportTable from '../../components/ReportTable'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const PAGE_SIZES = [20, 50, 100]

/** M5 派生的权限码（禁止手写新码） */
const PERM_QUERY = 'follow_up:query-completion'
const PERM_COMPLETE = 'follow_up:complete'
const PERM_MARK_LOST = 'follow_up:mark-lost'

const pad2 = (n: number) => String(n).padStart(2, '0')

/** 日期默认值（契约 §7：MONTH_START / MONTH_END → 当月起止） */
function monthStart(): string {
  const d = new Date()
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-01`
}
function monthEnd(): string {
  const d = new Date()
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(last.getDate())}`
}

interface QueryState {
  patient_name: string
  planned_from: string
  planned_to: string
  record_status: string
}

const emptyQuery = (): QueryState => ({
  patient_name: '',
  planned_from: monthStart(),
  planned_to: monthEnd(),
  record_status: '',
})

/** 下部登记面板（MU：txtFollowUpNo / lblPatientName / pslSourceVisitId / dtpPlannedFollowUpDate /
 *  dtpActualFollowUpDate / pslActualVisitId / cboEfficacyLevel / cboFollowUpStatus /
 *  txaSymptomChange / chkContinueMedication / txaRemark） */
interface FormState {
  id: number
  patient_id: number | null
  followUpNo: string
  patientName: string
  sourceVisitNo: string
  plannedDate: string
  actualDate: string
  actualVisitId: string
  efficacyLevel: string
  recordStatus: string
  symptomChange: string
  continueMedication: boolean
  remark: string
}

const toForm = (row: FollowUp): FormState => ({
  id: row.id,
  patient_id: row.patient_id ?? null,
  followUpNo: row.follow_up_no || '',
  patientName: row.patient_name || '',
  sourceVisitNo: row.visit_no || '',
  plannedDate: (row.planned_follow_up_date || '').slice(0, 10),
  actualDate: (row.actual_follow_up_date || '').slice(0, 10),
  actualVisitId: row.actual_visit_id === null || row.actual_visit_id === undefined ? '' : String(row.actual_visit_id),
  efficacyLevel: row.efficacy_level || '',
  recordStatus: row.record_status || '',
  symptomChange: row.symptom_change || '',
  continueMedication: row.continue_medication === 1 || row.continue_medication === true,
  remark: row.remark || '',
})

const mapOf = (items?: DictItem[]) => Object.fromEntries((items || []).map((it) => [it.code, it.label]))

/**
 * 随访登记列表列（`grdFollowUpList`）：
 * 后端 `GET /api/followup` 只回数据行、不返回列元数据（列元数据是 M7 报表口径，随访屏为 LIST_MAINTENANCE），
 * 故列表列按 MU frmFollowUp 的 `grdFollowUpList` 列序（随访号/患者/上次就诊/计划随访/实际随访/疗效/状态）
 * 固定声明后交给公共 ReportTable 渲染（不在此屏另写表格实现）。
 */
const LIST_COLUMNS: ReportColumn[] = [
  { name: 'follow_up_no', label: '随访号', dataType: 'String' },
  { name: 'patient_name', label: '患者', dataType: 'String' },
  { name: 'visit_no', label: '上次就诊', dataType: 'String' },
  { name: 'planned_follow_up_date', label: '计划随访', dataType: 'Date', format: 'yyyy-MM-dd' },
  { name: 'actual_follow_up_date', label: '实际随访', dataType: 'Date', format: 'yyyy-MM-dd' },
  { name: 'efficacy_level', label: '疗效', dataType: 'Enum' },
  { name: 'record_status', label: '状态', dataType: 'Enum' },
]

export default function FollowUpRegister() {
  const { hasPerm } = useAuth()
  const canQuery = hasPerm(PERM_QUERY) || hasPerm(PERM_COMPLETE)
  const canComplete = hasPerm(PERM_COMPLETE)
  const canMarkLost = hasPerm(PERM_MARK_LOST)

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [query, setQuery] = useState<QueryState>(emptyQuery)
  const [applied, setApplied] = useState<QueryState>(emptyQuery)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [rows, setRows] = useState<FollowUp[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState<FormState | null>(null)
  const [visitOpts, setVisitOpts] = useState<any[]>([])
  const [visitOptsError, setVisitOptsError] = useState('')
  const [exportFormat, setExportFormat] = useState<'xlsx' | 'csv'>('xlsx')
  const [confirmLost, setConfirmLost] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
  }, [])

  const load = async () => {
    setLoading(true)
    try {
      const res = await followupApi.list({
        page,
        size,
        patient_name: applied.patient_name || undefined,
        record_status: applied.record_status || undefined,
        // MU dtpQryPlannedFrom / dtpQryPlannedTo → 后端 scheduled_from / scheduled_to（计划随访日期区间）
        scheduled_from: applied.planned_from || undefined,
        scheduled_to: applied.planned_to || undefined,
      })
      setRows(res.list || [])
      setTotal(res.total || 0)
    } catch (err: any) {
      // 接口报错：保留上次结果，仅提示
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!canQuery) return // 无权限：不发起请求
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, size, applied, canQuery])

  /** 本次就诊跳选框（MU pslActualVisitId）：GET /api/visit/options（需 visit:register，部分角色 403 → 退回手填） */
  const loadVisitOptions = async (patientId: number | null | undefined) => {
    setVisitOpts([])
    setVisitOptsError('')
    if (!patientId) return
    try {
      const list = await http.get<any[]>('/visit/options', { patient_id: patientId })
      setVisitOpts(list || [])
    } catch (err: any) {
      setVisitOptsError(err.message || '就诊跳选框加载失败')
    }
  }

  const selectRow = (row: FollowUp) => {
    setForm(toForm(row))
    setConfirmLost(false)
    loadVisitOptions(row.patient_id)
  }

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  const onExport = async () => {
    try {
      // 导出参数＝报表 RPT-FOLLOWUP-COMPLETION-001 的参数名（计划随访日期区间 + 随访状态）
      await downloadReport(REPORT.followupCompletion, exportFormat, {
        plannedDateFrom: applied.planned_from || undefined,
        plannedDateTo: applied.planned_to || undefined,
        recordStatus: applied.record_status || undefined,
      })
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const refreshSelected = async (id: number) => {
    try {
      const fresh = await followupApi.get(id)
      if (fresh) setForm(toForm(fresh))
    } catch {
      /* 详情刷新失败不影响列表刷新 */
    }
  }

  const onComplete = async () => {
    if (!form) return
    if (!canComplete) {
      toast('当前账号无 follow_up:complete 权限，不能执行「评价」', 'error')
      return
    }
    if (!form.actualDate) {
      toast('实际随访日期必填', 'error')
      return
    }
    if (!form.actualVisitId) {
      toast('本次就诊必填', 'error')
      return
    }
    setBusy(true)
    try {
      await followupApi.complete(form.id, {
        actual_visit_id: form.actualVisitId,
        actual_follow_up_date: form.actualDate,
        efficacy_level: form.efficacyLevel || undefined,
        symptom_change: form.symptomChange || undefined,
        continue_medication: form.continueMedication ? 1 : 0,
        remark: form.remark || undefined,
      })
      toast('随访登记完成')
      await refreshSelected(form.id)
      await load()
    } catch (err: any) {
      toast(err.message, 'error') // 后端中文提示原样展示（如 R-05 日期顺序校验）
    } finally {
      setBusy(false)
    }
  }

  const onConfirmMarkLost = async () => {
    if (!form) return
    const reason = form.remark.trim()
    if (!reason) {
      toast('失访原因必填', 'error')
      return
    }
    setBusy(true)
    try {
      await followupApi.markLost(form.id, reason)
      toast('已标记失访')
      setConfirmLost(false)
      await refreshSelected(form.id)
      await load()
    } catch (err: any) {
      // 例如「计划随访日期（2026-10-07）尚未超期，不可标记失访」——原样展示
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const onCancel = () => {
    setForm(null)
    setConfirmLost(false)
    setVisitOpts([])
    setVisitOptsError('')
  }

  const valueLabels = useMemo(
    () => ({
      efficacy_level: mapOf(dicts[DICT.EFFICACY_LEVEL]),
      record_status: mapOf(dicts[DICT.FOLLOWUP_STATUS]),
    }),
    [dicts],
  )

  const statusOptions = dicts[DICT.FOLLOWUP_STATUS] || []
  const efficacyOptions = dicts[DICT.EFFICACY_LEVEL] || []
  const canCompleteNow = canComplete && form?.recordStatus === 'PENDING'

  if (!canQuery) {
    return (
      <div>
        <div className="card">
          <div className="card-title">
            <h3>复诊随访登记</h3>
          </div>
          <p className="text-secondary">
            当前账号无 `follow_up:query-completion`（`follow_up:complete`）权限，无法查询随访记录。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      {/* 查询区：txtQryPatientName / dtpQryPlannedFrom ~ dtpQryPlannedTo / cboQryRecordStatus */}
      <div className="card">
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">患者姓名</label>
            <div className="field-control">
              <input
                id="txtQryPatientName"
                value={query.patient_name}
                onChange={(e) => setQuery({ ...query, patient_name: e.target.value })}
                placeholder="模糊匹配"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">计划随访日期</label>
            <div className="field-control" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                id="dtpQryPlannedFrom"
                type="date"
                value={query.planned_from}
                onChange={(e) => setQuery({ ...query, planned_from: e.target.value })}
              />
              <span className="text-secondary">~</span>
              <input
                id="dtpQryPlannedTo"
                type="date"
                value={query.planned_to}
                onChange={(e) => setQuery({ ...query, planned_to: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">随访状态</label>
            <div className="field-control">
              <select
                id="cboQryRecordStatus"
                value={query.record_status}
                onChange={(e) => setQuery({ ...query, record_status: e.target.value })}
              >
                <option value="">全部</option>
                {statusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="toolbar-right">
          <select
            id="cboExportFormat"
            style={{ width: 110 }}
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value as 'xlsx' | 'csv')}
          >
            <option value="xlsx">XLSX</option>
            <option value="csv">CSV</option>
          </select>
          {canQuery && (
            <button id="btnExport" className="btn btn-secondary" onClick={onExport}>
              <Download size={14} /> 导出
            </button>
          )}
          <button id="btnQuery" className="btn btn-primary" onClick={onQuery}>
            <Search size={14} /> 查询
          </button>
        </div>
        <div className="text-secondary" style={{ marginTop: 8 }}>
          计划随访日期默认当月起止；列表按「计划随访日期」区间 + 随访状态过滤。
        </div>
      </div>

      {/* 列表：grdFollowUpList + lblPaging / cboPageSize / btnPrev / btnNext */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div id="grdFollowUpList">
          <ReportTable
            columns={LIST_COLUMNS}
            rows={rows}
            loading={loading}
            valueLabels={valueLabels}
            rowKey="id"
            emptyDisplay="-"
            emptyText="暂无随访数据"
            selectedKey={form?.id ?? null}
            onRowClick={(row) => selectRow(row as FollowUp)}
            rowActions={(row) => (
              <>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={!canComplete}
                  title={canComplete ? '登记复诊（评价）' : '无 follow_up:complete 权限'}
                  onClick={() => selectRow(row as FollowUp)}
                >
                  <Check size={14} /> 评价
                </button>{' '}
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={!canMarkLost}
                  title={canMarkLost ? '标记失访' : '无 follow_up:mark-lost 权限'}
                  onClick={() => selectRow(row as FollowUp)}
                >
                  <UserX size={14} /> 失访
                </button>
              </>
            )}
          />
        </div>
        <div
          style={{ padding: '14px 20px', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 16 }}
        >
          <div className="toolbar" id="lblPaging">
            <span className="text-secondary">每页</span>
            <select
              id="cboPageSize"
              style={{ width: 90 }}
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value))
                setPage(1)
              }}
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s} 条
                </option>
              ))}
            </select>
          </div>
          <div id="pager">
            <Pagination page={page} size={size} total={total} onChange={setPage} />
          </div>
        </div>
      </div>

      {/* 下部登记面板（MU 弹窗表单；此处按本批口径常驻页下部，选中行后可用） */}
      <div className="card">
        <div className="card-title">
          <h3>随访评价登记 / 标记失访</h3>
          <span className="text-secondary">
            {form ? `随访号 ${form.followUpNo}` : '请先在上方随访列表中点击一行（或点行内「评价 / 失访」）'}
            {form && form.recordStatus !== 'PENDING' ? ' · 该记录非「待随访」状态，仅可查看' : ''}
          </span>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label required">随访号</label>
            <div className="field-control">
              <input id="txtFollowUpNo" value={form?.followUpNo || ''} disabled placeholder="选择随访记录后回显" />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input id="lblPatientName" value={form?.patientName || ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">上次就诊</label>
            <div className="field-control">
              <input id="pslSourceVisitId" value={form?.sourceVisitNo || ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">计划随访日期</label>
            <div className="field-control">
              <input id="dtpPlannedFollowUpDate" value={form?.plannedDate || ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">实际随访日期</label>
            <div className="field-control">
              <input
                id="dtpActualFollowUpDate"
                type="date"
                value={form?.actualDate || ''}
                disabled={!form || !canCompleteNow}
                onChange={(e) => setForm((s) => (s ? { ...s, actualDate: e.target.value } : s))}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">本次就诊</label>
            <div className="field-control">
              {visitOpts.length > 0 ? (
                <select
                  id="pslActualVisitId"
                  value={form?.actualVisitId || ''}
                  disabled={!form || !canCompleteNow}
                  onChange={(e) => setForm((s) => (s ? { ...s, actualVisitId: e.target.value } : s))}
                >
                  <option value="">请选择该患者的就诊记录…</option>
                  {visitOpts.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.visit_no} · {v.register_time || ''} · 医师 {v.doctor_id || ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  id="pslActualVisitId"
                  value={form?.actualVisitId || ''}
                  disabled={!form || !canCompleteNow}
                  placeholder="就诊记录 ID（跳选框不可用时手填）"
                  onChange={(e) => setForm((s) => (s ? { ...s, actualVisitId: e.target.value } : s))}
                />
              )}
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">疗效评价</label>
            <div className="field-control">
              <select
                id="cboEfficacyLevel"
                value={form?.efficacyLevel || ''}
                disabled={!form || !canCompleteNow}
                onChange={(e) => setForm((s) => (s ? { ...s, efficacyLevel: e.target.value } : s))}
              >
                <option value="">未评价</option>
                {efficacyOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">随访状态</label>
            <div className="field-control">
              <input
                id="cboFollowUpStatus"
                value={dictLabel(dicts, DICT.FOLLOWUP_STATUS, form?.recordStatus) || ''}
                disabled
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">是否继续用药</label>
            <div className="field-control">
              <input
                id="chkContinueMedication"
                type="checkbox"
                style={{ width: 'auto' }}
                checked={!!form?.continueMedication}
                disabled={!form || !canCompleteNow}
                onChange={(e) => setForm((s) => (s ? { ...s, continueMedication: e.target.checked } : s))}
              />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">症状变化</label>
            <div className="field-control">
              <textarea
                id="txaSymptomChange"
                rows={2}
                value={form?.symptomChange || ''}
                disabled={!form || !canCompleteNow}
                onChange={(e) => setForm((s) => (s ? { ...s, symptomChange: e.target.value } : s))}
              />
            </div>
          </div>
          <div className="form-item span-3">
            <label className="field-label">备注 / 失访原因</label>
            <div className="field-control">
              <textarea
                id="txaRemark"
                rows={2}
                value={form?.remark || ''}
                disabled={!form}
                placeholder="标记失访时此栏为「失访原因」（必填）"
                onChange={(e) => setForm((s) => (s ? { ...s, remark: e.target.value } : s))}
              />
            </div>
          </div>
        </div>
        {visitOptsError ? (
          <div className="text-secondary" style={{ marginTop: 6 }}>
            就诊跳选框不可用（{visitOptsError}），「本次就诊」可手工填写就诊记录 ID。
          </div>
        ) : null}
        {!canComplete ? (
          <div className="text-secondary" style={{ marginTop: 6 }}>
            当前账号无 `follow_up:complete` 权限：可查询 / 导出，但不能评价。
          </div>
        ) : null}
        {!canMarkLost ? (
          <div className="text-secondary" style={{ marginTop: 6 }}>
            当前账号无 `follow_up:mark-lost` 权限：不能标记失访。
          </div>
        ) : null}
        <div className="toolbar-right">
          <button id="btnCancel" className="btn btn-secondary" onClick={onCancel} disabled={!form}>
            <X size={14} /> 取消
          </button>
          <button
            id="btnMarkLost"
            className="btn btn-secondary"
            disabled={!form || !canMarkLost || busy}
            title={canMarkLost ? '标记失访（需二次确认，计划随访日期须已超期）' : '无 follow_up:mark-lost 权限'}
            onClick={() => {
              if (!form) return
              if (!form.remark.trim()) {
                toast('失访原因必填', 'error')
                return
              }
              setConfirmLost(true)
            }}
          >
            <UserX size={14} /> 标记失访
          </button>
          <button
            id="btnSave"
            className="btn btn-primary"
            disabled={!form || !canCompleteNow || busy}
            title={canComplete ? '登记复诊（评价）' : '无 follow_up:complete 权限'}
            onClick={onComplete}
          >
            <Check size={14} /> 评价
          </button>
        </div>
      </div>

      {/* 标记失访二次确认 */}
      <Modal
        title="确认标记失访"
        open={confirmLost}
        onClose={() => setConfirmLost(false)}
        width={520}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setConfirmLost(false)}>
              取消
            </button>
            <button className="btn btn-primary" disabled={busy} onClick={onConfirmMarkLost}>
              确定标记失访
            </button>
          </>
        }
      >
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label">随访号</label>
            <div className="field-control">
              <input value={form?.followUpNo || ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">患者</label>
            <div className="field-control">
              <input value={form?.patientName || ''} disabled />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label">失访原因</label>
            <div className="field-control">
              <input value={form?.remark || ''} disabled />
            </div>
          </div>
        </div>
        <p className="text-secondary">确认后随访状态变为「已失访」；计划随访日期须已超期，否则后端会返回中文提示。</p>
      </Modal>
    </div>
  )
}
