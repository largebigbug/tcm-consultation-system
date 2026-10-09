/**
 * UI-17 就诊与处方记录查询（frmVisitPrescriptionQuery，QUERY_LIST，含作废入口）—— 批次 3 子代理 B。
 *
 * 契约：`docs/批次3-实现契约.md` §6（作废入口 R-04 三分派）、§7（前端契约）、§3.4/§3.5（报表接口与导出）。
 * MU：`docs/批次3-屏幕规格（MU抽取）.md` frmVisitPrescriptionQuery（22 元素 / 3 动作），元素 id 已落到控件 `id` 上。
 *
 * 取数：`reportApi.query('QR-VISIT-PRESCRIPTION-001', 参数)`（主＝就诊、从＝处方，分页作用于主行）；
 *       列与表头一律取后端 `columns` / `masterDetail.childColumns`，页面不手写列；
 *       导出 `downloadReport('QR-VISIT-PRESCRIPTION-001', 'xlsx'|'csv', 查询条件)`。
 * 作废：选中从表行 → 下方作废区可用；POST 作废接口（权限 `prescription:cancel`），
 *       R-04 三分派（仅作废 / 作废并回冲库存 / 已发药阻断）**成功与失败的中文提示均取后端 message 原样展示**。
 */
import { useEffect, useMemo, useState } from 'react'
import { Ban, Download, RotateCcw, Search, X } from 'lucide-react'
import { DICT, dictLabel, metaApi, type DictItem, type DictionaryMap } from '../../api/meta'
import { clearToken, getToken } from '../../api/request'
import { REPORT, downloadReport, reportApi, type ReportColumn, type ReportResult } from '../../api/report'
import Pagination from '../../components/Pagination'
import ReportTable from '../../components/ReportTable'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const PAGE_SIZES = [20, 50, 100]

/** M5 派生的权限码（禁止手写新码） */
const PERM_QUERY = 'visit:query-visit-and-prescription'
const PERM_VOID = 'prescription:cancel'

/** api/meta.ts 未收敛的字典键（沿用批次 2 页面做法，按模型键直接使用） */
const DICT_USAGE_METHOD = 'DICT-PRESCRIPTION.USAGE_METHOD'

/** M2 前置口径（契约 §6）：仅这 4 个状态的处方可作废；ISSUED / VOIDED 置灰 */
const VOIDABLE_STATUS = ['DRAFT', 'PENDING_REVIEW', 'APPROVED', 'DISPENSING']

/**
 * 主表结果列（MU `grdVisitResult`：就诊号 | 患者编号 | 患者姓名 | 性别 | 年龄 | 就诊类型 |
 * 挂号时间 | 接诊时间 | 接诊医师 | 科室 | 就诊状态 | 处方张数 | 总剂数）。
 * 仅用于决定「从表维度列」不重复出现在主表（列本身仍取后端 `columns`，不在此手写表头）。
 */
const MASTER_COLUMNS = new Set([
  'visitNo',
  'patientNo',
  'patientName',
  'gender',
  'age',
  'visitType',
  'registerTime',
  'receiveTime',
  'doctorId',
  'deptCode',
  'visitStatus',
  'visitPrescriptionCount',
  'visitDoseTotal',
])

/** 契约 §3.4 冻结的主从元数据（ReportResult 类型未收敛，按契约结构读取） */
interface MasterDetail {
  level?: string
  childKey?: string
  childColumns?: ReportColumn[]
  grandchildKey?: string
  grandchildColumns?: ReportColumn[]
  detailRowKey?: string
}

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
  patientName: string
  visitNo: string
  prescriptionNo: string
  dateFrom: string
  dateTo: string
  visitStatus: string
  prescriptionStatus: string
  doctorId: string
  reviewerId: string
}

const emptyQuery = (): QueryState => ({
  patientName: '',
  visitNo: '',
  prescriptionNo: '',
  dateFrom: monthStart(),
  dateTo: monthEnd(),
  visitStatus: '',
  prescriptionStatus: '',
  doctorId: '',
  reviewerId: '',
})

const mapOf = (items?: DictItem[]) => Object.fromEntries((items || []).map((it) => [it.code, it.label]))

const text = (v: any) => (v === null || v === undefined ? '' : String(v))

/**
 * 作废接口（契约 §6）：POST /api/prescriptions/<id>/cancel，body {reason}。
 *
 * 实测（隔离库探针）：后端现有路由为 `/api/prescription/<id>/cancel`（单数）且读 `cancel_reason`；
 * 契约写的是复数路径 + `reason`（前者返回「接口不存在」）。故两键同发、按「实际路径 → 契约路径」顺序兜底，
 * 既保证当前可运行，也在后端收口到契约路径时不需改前端。
 *
 * 这里用「带 Bearer 头 fetch」而非 `http.post`：http 封装只回传 `data`，会丢弃后端 `message`，
 * 而契约 §6 要求作废成功/失败的中文提示（R-04 三分派）一律原样展示后端 message。
 */
async function postForMessage(path: string, payload: Record<string, any>): Promise<{ data: any; message: string }> {
  const token = getToken()
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload || {}),
  })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('登录已过期')
  }
  const body = await res.json().catch(() => null)
  if (!body || body.success !== true) {
    throw new Error((body && body.message) || `请求失败（HTTP ${res.status}）`)
  }
  return { data: body.data, message: body.message || '' }
}

async function cancelPrescription(id: number | string, reason: string): Promise<{ data: any; message: string }> {
  const paths = [`/prescription/${id}/cancel`, `/prescriptions/${id}/cancel`]
  let lastErr: any = null
  for (const path of paths) {
    try {
      return await postForMessage(path, { cancel_reason: reason, reason })
    } catch (err: any) {
      lastErr = err
      const msg = String((err && err.message) || '')
      if (!/接口不存在|HTTP 404/.test(msg)) throw err // 业务失败（如已发药阻断）直接上抛，原样展示
    }
  }
  throw lastErr
}

export default function VisitPrescriptionQuery() {
  const { hasPerm } = useAuth()
  const canQuery = hasPerm(PERM_QUERY)
  const canVoid = hasPerm(PERM_VOID)

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [query, setQuery] = useState<QueryState>(emptyQuery)
  const [applied, setApplied] = useState<QueryState>(emptyQuery)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)

  const [columns, setColumns] = useState<ReportColumn[]>([])
  const [rows, setRows] = useState<Record<string, any>[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<Record<string, any> | null>(null)
  const [masterDetail, setMasterDetail] = useState<MasterDetail | null>(null)
  const [loading, setLoading] = useState(false)

  const [selectedVisit, setSelectedVisit] = useState<Record<string, any> | null>(null)
  const [selectedPrescription, setSelectedPrescription] = useState<Record<string, any> | null>(null)
  const [voidReason, setVoidReason] = useState('')
  const [voiding, setVoiding] = useState(false)
  const [exportFormat, setExportFormat] = useState<'xlsx' | 'csv'>('xlsx')

  useEffect(() => {
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
  }, [])

  const buildParams = (q: QueryState): Record<string, any> => ({
    patientName: q.patientName || undefined,
    visitNo: q.visitNo || undefined,
    prescriptionNo: q.prescriptionNo || undefined,
    registerDateFrom: q.dateFrom || undefined,
    registerDateTo: q.dateTo || undefined,
    visitStatus: q.visitStatus || undefined,
    prescriptionStatus: q.prescriptionStatus || undefined,
    doctorId: q.doctorId || undefined,
    reviewerId: q.reviewerId || undefined,
  })

  const load = async () => {
    setLoading(true)
    try {
      const res: ReportResult = await reportApi.query<ReportResult>(REPORT.visitPrescription, {
        ...buildParams(applied),
        page,
        size,
      })
      setColumns(res.columns || [])
      setRows(res.list || [])
      setTotal(res.total || 0)
      setSummary(res.summary ?? null)
      setMasterDetail(((res as any).masterDetail as MasterDetail) || null)
    } catch (err: any) {
      // 接口报错：toast 中文提示并保留上次结果
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

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  const onReset = () => {
    const empty = emptyQuery()
    setQuery(empty)
    setApplied(empty)
    setPage(1)
    setSelectedVisit(null)
    setSelectedPrescription(null)
    setVoidReason('')
  }

  const onExport = async () => {
    try {
      await downloadReport(REPORT.visitPrescription, exportFormat, buildParams(applied))
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  // ------------------------------------------------------------ 主从联动
  const detailRowKey = masterDetail?.detailRowKey || 'id'

  const childColumns: ReportColumn[] = useMemo(
    () => masterDetail?.childColumns || [],
    [masterDetail],
  )

  const childRows: Record<string, any>[] = useMemo(() => {
    const key = masterDetail?.childKey || 'prescriptions'
    const list = selectedVisit ? selectedVisit[key] : null
    return Array.isArray(list) ? list : []
  }, [selectedVisit, masterDetail])

  /** 兜底列：后端未提供 masterDetail.childColumns 时，用从表行键生成（避免整屏不可用；仍非页面手写列） */
  const fallbackChildColumns: ReportColumn[] = useMemo(() => {
    if (childColumns.length > 0 || childRows.length === 0) return []
    const keys = Array.from(new Set(childRows.flatMap((r) => Object.keys(r))))
    return keys.filter((k) => k !== 'items').map((k) => ({ name: k, label: k }))
  }, [childColumns, childRows])

  const effectiveChildColumns = childColumns.length > 0 ? childColumns : fallbackChildColumns

  const hiddenForMaster = useMemo(
    () => columns.filter((c) => !MASTER_COLUMNS.has(c.name)).map((c) => c.name),
    [columns],
  )

  const onSelectVisit = (row: Record<string, any>) => {
    setSelectedVisit(row)
    setSelectedPrescription(null)
    setVoidReason('')
  }

  const onSelectPrescription = (row: Record<string, any>) => {
    setSelectedPrescription(row)
    setVoidReason('')
  }

  const prescriptionId = (row: Record<string, any> | null) => {
    if (!row) return null
    return row[detailRowKey] ?? row.id ?? row.prescriptionId ?? null
  }

  const isVoidable = (status: any) => VOIDABLE_STATUS.includes(text(status).toUpperCase())

  const voidableNow = !!selectedPrescription && isVoidable(selectedPrescription.prescriptionStatus)

  const onVoid = async () => {
    if (!selectedPrescription) {
      toast('请先在处方从表中选择一行', 'error')
      return
    }
    if (!canVoid) {
      toast('当前账号无 prescription:cancel 权限，不能作废处方', 'error')
      return
    }
    if (!voidableNow) {
      toast(
        `处方状态「${dictLabel(dicts, DICT.PRESCRIPTION_STATUS, text(selectedPrescription.prescriptionStatus))}」不可作废（仅 DRAFT/PENDING_REVIEW/APPROVED/DISPENSING）`,
        'error',
      )
      return
    }
    const reason = voidReason.trim()
    if (!reason) {
      toast('作废原因必填', 'error')
      return
    }
    const id = prescriptionId(selectedPrescription)
    if (id === null) {
      toast('该处方行缺少处方标识，无法作废', 'error')
      return
    }
    setVoiding(true)
    try {
      const res = await cancelPrescription(id, reason)
      // R-04 三分派结果（仅作废 / 作废并回冲库存 / 已发药阻断）——后端中文 message 原样展示
      toast(res.message || '处方已作废')
      setSelectedPrescription(null)
      setVoidReason('')
      await load() // 成功后刷新主 / 从表
    } catch (err: any) {
      toast(err.message, 'error') // 如「处方已发药，不能作废」
    } finally {
      setVoiding(false)
    }
  }

  const valueLabels = useMemo(
    () => ({
      // 主表字典列
      gender: mapOf(dicts[DICT.PATIENT_GENDER]),
      deptCode: mapOf(dicts[DICT.VISIT_DEPT]),
      visitType: mapOf(dicts[DICT.VISIT_TYPE]),
      visitStatus: mapOf(dicts[DICT.VISIT_STATUS]),
      // 从表（处方 / 明细）字典列
      prescriptionStatus: mapOf(dicts[DICT.PRESCRIPTION_STATUS]),
      prescriptionType: mapOf(dicts[DICT.PRESCRIPTION_TYPE]),
      usageMethod: mapOf(dicts[DICT_USAGE_METHOD]),
      itemDecoctionMethod: mapOf(dicts[DICT.PRESCRIPTION_DECOCTION_METHOD]),
    }),
    [dicts],
  )

  const visitStatusOptions = dicts[DICT.VISIT_STATUS] || []
  const prescriptionStatusOptions = dicts[DICT.PRESCRIPTION_STATUS] || []
  const selectedStatusLabel = selectedPrescription
    ? dictLabel(dicts, DICT.PRESCRIPTION_STATUS, text(selectedPrescription.prescriptionStatus))
    : ''

  if (!canQuery) {
    return (
      <div>
        <div className="card">
          <div className="card-title">
            <h3>就诊与处方记录查询</h3>
          </div>
          <p className="text-secondary">
            当前账号无 `visit:query-visit-and-prescription` 权限，无法查询就诊与处方记录。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      {/* 查询区（MU：txtQryPatientName / txtQryVisitNo / txtQryPrescriptionNo / dtpQryDateFrom-To /
          cboQryVisitStatus / cboQryPrescriptionStatus / txtQryDoctorId / txtQryReviewerId） */}
      <div className="card">
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">患者姓名</label>
            <div className="field-control">
              <input
                id="txtQryPatientName"
                value={query.patientName}
                onChange={(e) => setQuery({ ...query, patientName: e.target.value })}
                placeholder="模糊匹配"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊号</label>
            <div className="field-control">
              <input
                id="txtQryVisitNo"
                value={query.visitNo}
                onChange={(e) => setQuery({ ...query, visitNo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">处方号</label>
            <div className="field-control">
              <input
                id="txtQryPrescriptionNo"
                value={query.prescriptionNo}
                onChange={(e) => setQuery({ ...query, prescriptionNo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">挂号日期</label>
            <div className="field-control" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                id="dtpQryDateFrom"
                type="date"
                value={query.dateFrom}
                onChange={(e) => setQuery({ ...query, dateFrom: e.target.value })}
              />
              <span className="text-secondary">~</span>
              <input
                id="dtpQryDateTo"
                type="date"
                value={query.dateTo}
                onChange={(e) => setQuery({ ...query, dateTo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊状态</label>
            <div className="field-control">
              <select
                id="cboQryVisitStatus"
                value={query.visitStatus}
                onChange={(e) => setQuery({ ...query, visitStatus: e.target.value })}
              >
                <option value="">全部</option>
                {visitStatusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">处方状态</label>
            <div className="field-control">
              <select
                id="cboQryPrescriptionStatus"
                value={query.prescriptionStatus}
                onChange={(e) => setQuery({ ...query, prescriptionStatus: e.target.value })}
              >
                <option value="">全部</option>
                {prescriptionStatusOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">接诊医师</label>
            <div className="field-control">
              <input
                id="txtQryDoctorId"
                value={query.doctorId}
                onChange={(e) => setQuery({ ...query, doctorId: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">审核药师</label>
            <div className="field-control">
              <input
                id="txtQryReviewerId"
                value={query.reviewerId}
                onChange={(e) => setQuery({ ...query, reviewerId: e.target.value })}
              />
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
          <button id="btnReset" className="btn btn-secondary" onClick={onReset}>
            <RotateCcw size={14} /> 重置
          </button>
          <button id="btnExport" className="btn btn-secondary" onClick={onExport}>
            <Download size={14} /> 导出
          </button>
          <button id="btnQuery" className="btn btn-primary" onClick={onQuery}>
            <Search size={14} /> 查询
          </button>
        </div>
      </div>

      {/* 主表：就诊记录（grdVisitResult） */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="card-title" style={{ padding: '14px 20px 0' }}>
          <h3>主表：就诊记录</h3>
          <span className="text-secondary">点击一行就诊记录 → 下方从表刷新为该就诊的处方</span>
        </div>
        <div id="grdVisitResult">
          <ReportTable
            columns={columns}
            rows={rows}
            loading={loading}
            summary={summary}
            valueLabels={valueLabels}
            rowKey="id"
            hiddenColumns={hiddenForMaster}
            emptyDisplay="-"
            emptyText="暂无就诊记录"
            selectedKey={selectedVisit ? selectedVisit.id : null}
            onRowClick={onSelectVisit}
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

      {/* 从表：处方（grdPrescriptionResult） */}
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="card-title" style={{ padding: '14px 20px 0' }}>
          <h3>从表：处方</h3>
          <span className="text-secondary">
            {selectedVisit ? `就诊号 ${text(selectedVisit.visitNo)} · 处方 ${childRows.length} 张` : '未选择就诊记录'}
          </span>
        </div>
        <div id="grdPrescriptionResult">
          {effectiveChildColumns.length > 0 ? (
            <ReportTable
              columns={effectiveChildColumns}
              rows={childRows}
              valueLabels={valueLabels}
              rowKey={detailRowKey}
              emptyDisplay="-"
              emptyText={selectedVisit ? '该就诊暂无处方记录' : '请先在上方主表中选择一行就诊记录'}
              selectedKey={prescriptionId(selectedPrescription)}
              onRowClick={onSelectPrescription}
              rowActions={(row) => {
                const ok = canVoid && isVoidable(row.prescriptionStatus)
                const st = dictLabel(dicts, DICT.PRESCRIPTION_STATUS, text(row.prescriptionStatus)) || '-'
                return (
                  <button
                    className="btn btn-secondary btn-sm"
                    disabled={!ok}
                    title={
                      !canVoid
                        ? '无 prescription:cancel 权限'
                        : ok
                          ? '作废该处方'
                          : `处方状态「${st}」不可作废（仅 DRAFT / PENDING_REVIEW / APPROVED / DISPENSING 可作废）`
                    }
                    onClick={() => onSelectPrescription(row)}
                  >
                    <Ban size={14} /> 作废
                  </button>
                )
              }}
            />
          ) : (
            <div style={{ padding: '16px 20px' }} className="text-secondary">
              {selectedVisit
                ? '后端未返回从表列定义（masterDetail.childColumns 为空）'
                : '请先在上方主表中选择一行就诊记录'}
            </div>
          )}
        </div>
      </div>

      {/* 作废区（MU：txtVoidPrescriptionNo 只读 / txaVoidReason 必填 / btnVoid 作废 / btnVoidCancel 取消） */}
      <div className="card">
        <div className="card-title">
          <h3>处方作废</h3>
          <span className="text-secondary">
            先选中从表一行处方；仅 DRAFT / PENDING_REVIEW / APPROVED / DISPENSING 可作废，ISSUED / VOIDED 置灰
          </span>
        </div>
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label required">处方号</label>
            <div className="field-control">
              <input
                id="txtVoidPrescriptionNo"
                value={selectedPrescription ? text(selectedPrescription.prescriptionNo) : ''}
                disabled
                placeholder="选中从表处方行后回显"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">处方状态</label>
            <div className="field-control">
              <input value={selectedStatusLabel} disabled />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label required">作废原因</label>
            <div className="field-control">
              <textarea
                id="txaVoidReason"
                rows={2}
                value={voidReason}
                disabled={!selectedPrescription}
                placeholder="作废原因必填"
                onChange={(e) => setVoidReason(e.target.value)}
              />
            </div>
          </div>
        </div>
        {!canVoid ? (
          <div className="text-secondary" style={{ marginTop: 6 }}>
            当前账号无 `prescription:cancel` 权限：可查询 / 导出，但不能作废处方。
          </div>
        ) : null}
        <div className="toolbar-right">
          <button
            id="btnVoidCancel"
            className="btn btn-secondary"
            onClick={() => {
              setSelectedPrescription(null)
              setVoidReason('')
            }}
            disabled={!selectedPrescription}
          >
            <X size={14} /> 取消
          </button>
          <button
            id="btnVoid"
            className="btn btn-primary"
            disabled={!canVoid || !voidableNow || !voidReason.trim() || voiding}
            onClick={onVoid}
          >
            <Ban size={14} /> 作废
          </button>
        </div>
      </div>
    </div>
  )
}
