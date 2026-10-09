import { useEffect, useMemo, useState } from 'react'
import { Download, RotateCcw, Search } from 'lucide-react'
import { REPORT, downloadReport, reportApi, type ReportColumn } from '../../api/report'
import { DICT, metaApi, type DictionaryMap } from '../../api/meta'
import ReportTable from '../../components/ReportTable'
import Pagination from '../../components/Pagination'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const PAGE_SIZES = [20, 50, 100]

/** MU frmVisitStats（QUERY_LIST）：actQuery / actExport → Visit_QueryStats */
const PERM = 'visit:query-stats'

const pad = (n: number) => String(n).padStart(2, '0')

/** M7 参数默认值 MONTH_START → 当月首日 */
const monthStart = () => {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01`
}

/** M7 参数默认值 MONTH_END → 当月末日 */
const monthEnd = () => {
  const d = new Date()
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0)
  return `${last.getFullYear()}-${pad(last.getMonth() + 1)}-${pad(last.getDate())}`
}

/** 字典 → { code: label }，供 ReportTable 的 valueLabels 渲染 */
const labelMap = (dicts: DictionaryMap, key: string): Record<string, string> =>
  (dicts[key] || []).reduce<Record<string, string>>((m, it) => {
    m[it.code] = it.label
    return m
  }, {})

/** MU cboDateGranularity 日期粒度；M7 DATE_TRUNC 粒度仅接受 DAY / MONTH / YEAR */
const GRANULARITY = [
  { value: 'DAY', label: '按日' },
  { value: 'MONTH', label: '按月' },
  { value: 'YEAR', label: '按年' },
]

interface QueryState {
  registerDateFrom: string
  registerDateTo: string
  granularity: string
  deptCode: string
  doctorId: string
  visitType: string
  visitStatus: string
}

/** 初值＝M7 参数默认值（registerDateFrom=MONTH_START、registerDateTo=MONTH_END、granularity=DAY） */
const defaultQuery = (): QueryState => ({
  registerDateFrom: monthStart(),
  registerDateTo: monthEnd(),
  granularity: 'DAY',
  deptCode: '',
  doctorId: '',
  visitType: '',
  visitStatus: '',
})

const emptyQuery = (): QueryState => ({
  registerDateFrom: '',
  registerDateTo: '',
  granularity: '',
  deptCode: '',
  doctorId: '',
  visitType: '',
  visitStatus: '',
})

export default function VisitStats() {
  const { hasPerm } = useAuth()
  const canQuery = hasPerm(PERM)

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [query, setQuery] = useState<QueryState>(defaultQuery)
  const [applied, setApplied] = useState<QueryState>(defaultQuery)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [columns, setColumns] = useState<ReportColumn[]>([])
  const [rows, setRows] = useState<Record<string, any>[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<Record<string, any> | null>(null)
  const [loading, setLoading] = useState(false)
  const [format, setFormat] = useState<'xlsx' | 'csv'>('xlsx')

  /** 已应用条件 → M7 参数名（空值由 http.get 丢弃，后端 skipWhenParameterEmpty 生效） */
  const params = useMemo(
    () => ({
      registerDateFrom: applied.registerDateFrom || undefined,
      registerDateTo: applied.registerDateTo || undefined,
      granularity: applied.granularity || undefined,
      deptCode: applied.deptCode || undefined,
      doctorId: applied.doctorId || undefined,
      visitType: applied.visitType || undefined,
      visitStatus: applied.visitStatus || undefined,
    }),
    [applied],
  )

  const load = async () => {
    if (!canQuery) return
    setLoading(true)
    try {
      const res = await reportApi.query(REPORT.visitStats, { ...params, page, size })
      setColumns(res.columns || [])
      setRows(res.list || [])
      setTotal(res.total || 0)
      setSummary(res.summary ?? null)
    } catch (err: any) {
      // 契约：接口报错提示中文 message 并保留上次结果
      toast(err.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!canQuery) return
    metaApi.dictionaries().then(setDicts).catch(() => setDicts({}))
  }, [canQuery])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, size, applied, canQuery])

  const valueLabels = useMemo(
    () => ({
      deptCode: labelMap(dicts, DICT.VISIT_DEPT),
      visitType: labelMap(dicts, DICT.VISIT_TYPE),
      visitStatus: labelMap(dicts, DICT.VISIT_STATUS),
    }),
    [dicts],
  )

  const deptOptions = dicts[DICT.VISIT_DEPT] || []
  const visitTypeOptions = dicts[DICT.VISIT_TYPE] || []
  const visitStatusOptions = dicts[DICT.VISIT_STATUS] || []

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  /** 重置：清空全部条件并回到第 1 页 */
  const onReset = () => {
    const empty = emptyQuery()
    setQuery(empty)
    setApplied(empty)
    setPage(1)
  }

  const onExport = async () => {
    if (!canQuery) return
    try {
      await downloadReport(REPORT.visitStats, format, params)
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  if (!canQuery) {
    return (
      <div className="card">
        <div className="card-title">
          <h3>门诊量统计</h3>
        </div>
        <div className="text-secondary">当前账号无「门诊量统计」查询权限（{PERM}），请联系系统管理员。</div>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <h3>门诊量统计</h3>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">挂号日期从</label>
            <div className="field-control">
              <input
                type="date"
                value={query.registerDateFrom}
                onChange={(e) => setQuery({ ...query, registerDateFrom: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">挂号日期到</label>
            <div className="field-control">
              <input
                type="date"
                value={query.registerDateTo}
                onChange={(e) => setQuery({ ...query, registerDateTo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">日期粒度</label>
            <div className="field-control">
              <select
                value={query.granularity}
                onChange={(e) => setQuery({ ...query, granularity: e.target.value })}
              >
                <option value="">请选择</option>
                {GRANULARITY.map((it) => (
                  <option key={it.value} value={it.value}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">科室</label>
            <div className="field-control">
              <select value={query.deptCode} onChange={(e) => setQuery({ ...query, deptCode: e.target.value })}>
                <option value="">全部</option>
                {deptOptions.map((it) => (
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
                value={query.doctorId}
                onChange={(e) => setQuery({ ...query, doctorId: e.target.value })}
                placeholder="医师工号"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊类型</label>
            <div className="field-control">
              <select value={query.visitType} onChange={(e) => setQuery({ ...query, visitType: e.target.value })}>
                <option value="">全部</option>
                {visitTypeOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊状态</label>
            <div className="field-control">
              <select
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
        </div>
        <div className="toolbar-right">
          <button className="btn btn-secondary" onClick={onReset}>
            <RotateCcw size={14} /> 重置
          </button>
          <select
            style={{ width: 110 }}
            value={format}
            onChange={(e) => setFormat(e.target.value as 'xlsx' | 'csv')}
          >
            <option value="xlsx">XLSX</option>
            <option value="csv">CSV</option>
          </select>
          <button className="btn btn-secondary" onClick={onExport}>
            <Download size={14} /> 导出
          </button>
          <button className="btn btn-primary" onClick={onQuery}>
            <Search size={14} /> 查询
          </button>
        </div>
        <div className="text-secondary" style={{ marginTop: 8 }}>
          口径提示：就诊人数＝不重复患者数、就诊人次＝记录条数（Q-01 / REP-01）
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <ReportTable
          columns={columns}
          rows={rows}
          loading={loading}
          summary={summary}
          valueLabels={valueLabels}
          emptyText="暂无数据"
        />
        <div
          style={{
            padding: '14px 20px',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            gap: 16,
          }}
        >
          <div className="toolbar">
            <span className="text-secondary">每页</span>
            <select
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
          <Pagination page={page} size={size} total={total} onChange={setPage} />
        </div>
      </div>
    </div>
  )
}
