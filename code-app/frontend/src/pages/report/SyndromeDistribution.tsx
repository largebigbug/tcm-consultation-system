import { useEffect, useMemo, useState } from 'react'
import { Download, RotateCcw, Search } from 'lucide-react'
import { REPORT, downloadReport, reportApi, type ReportColumn } from '../../api/report'
import { DICT, metaApi, type DictionaryMap } from '../../api/meta'
import { syndromeApi } from '../../api/syndrome'
import ReportTable from '../../components/ReportTable'
import Pagination from '../../components/Pagination'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const PAGE_SIZES = [20, 50, 100]

/** MU frmSyndromeDist（QUERY_LIST）：actQuery / actExport → Diagnosis_QuerySyndromeDistribution */
const PERM = 'diagnosis:query-syndrome-distribution'

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

interface PopupOption {
  value: string
  label: string
  sub?: string
}

/** 跳选框（POPUP_SELECT）：只读输入框 + 「…」弹窗列表选择（沿用批次 1/2 页面内实现风格） */
function PopupSelect({
  elementId,
  title,
  columnLabel,
  display,
  placeholder,
  loader,
  onSelect,
}: {
  elementId: string
  title: string
  columnLabel: string
  display: string
  placeholder?: string
  loader: (keyword: string) => Promise<PopupOption[]>
  onSelect: (opt: PopupOption | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState<PopupOption[]>([])
  const [loading, setLoading] = useState(false)

  const search = (kw: string) => {
    setLoading(true)
    loader(kw)
      .then((list) => setRows(list))
      .catch((e: any) => {
        toast(e.message, 'error')
        setRows([])
      })
      .finally(() => setLoading(false))
  }

  return (
    <>
      <div className="field-control" style={{ display: 'flex', gap: 4 }}>
        <input
          id={elementId}
          className="table-input"
          readOnly
          value={display}
          placeholder={placeholder || '点击「…」选择'}
          style={{ flex: 1, minWidth: 90 }}
        />
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => {
            setKeyword('')
            setOpen(true)
            search('')
          }}
        >
          …
        </button>
      </div>
      <Modal
        title={title}
        open={open}
        onClose={() => setOpen(false)}
        width={640}
        footer={
          <>
            <button
              className="btn btn-secondary"
              onClick={() => {
                onSelect(null)
                setOpen(false)
              }}
            >
              清除
            </button>
            <button className="btn btn-secondary" onClick={() => setOpen(false)}>
              关闭
            </button>
          </>
        }
      >
        <div className="toolbar" style={{ marginBottom: 12 }}>
          <div className="form-item" style={{ flex: 1 }}>
            <label className="field-label">关键字</label>
            <div className="field-control">
              <input
                value={keyword}
                placeholder="输入名称后回车查询"
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') search(keyword)
                }}
              />
            </div>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => search(keyword)}>
            <Search size={14} /> 查询
          </button>
        </div>
        <div className="table-container" style={{ maxHeight: 320 }}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 70 }}>选择</th>
                <th>{columnLabel}</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={2} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    加载中…
                  </td>
                </tr>
              )}
              {!loading &&
                rows.map((r) => (
                  <tr key={r.value}>
                    <td>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          onSelect(r)
                          setOpen(false)
                        }}
                      >
                        选择
                      </button>
                    </td>
                    <td>
                      {r.label}
                      {r.sub ? <span className="text-secondary">（{r.sub}）</span> : null}
                    </td>
                  </tr>
                ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={2} style={{ textAlign: 'center', color: '#94a3b8' }}>
                    暂无数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Modal>
    </>
  )
}

interface QueryState {
  visitDateFrom: string
  visitDateTo: string
  diagnosisMethod: string
  syndromeNature: string
  syndromeId: string
  /** 仅用于界面回显（跳选框显示名），不下发接口 */
  syndromeLabel: string
  deptCode: string
  doctorId: string
}

/** 初值＝M7 参数默认值（visitDateFrom=MONTH_START、visitDateTo=MONTH_END） */
const defaultQuery = (): QueryState => ({
  visitDateFrom: monthStart(),
  visitDateTo: monthEnd(),
  diagnosisMethod: '',
  syndromeNature: '',
  syndromeId: '',
  syndromeLabel: '',
  deptCode: '',
  doctorId: '',
})

const emptyQuery = (): QueryState => ({
  visitDateFrom: '',
  visitDateTo: '',
  diagnosisMethod: '',
  syndromeNature: '',
  syndromeId: '',
  syndromeLabel: '',
  deptCode: '',
  doctorId: '',
})

export default function SyndromeDistribution() {
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

  /** 已应用条件 → M7 参数名（空值由 http.get 丢弃） */
  const params = useMemo(
    () => ({
      visitDateFrom: applied.visitDateFrom || undefined,
      visitDateTo: applied.visitDateTo || undefined,
      diagnosisMethod: applied.diagnosisMethod || undefined,
      syndromeNature: applied.syndromeNature || undefined,
      syndromeId: applied.syndromeId || undefined,
      deptCode: applied.deptCode || undefined,
      doctorId: applied.doctorId || undefined,
    }),
    [applied],
  )

  const load = async () => {
    if (!canQuery) return
    setLoading(true)
    try {
      const res = await reportApi.query(REPORT.syndromeDist, { ...params, page, size })
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
      diagnosisMethod: labelMap(dicts, DICT.SYNDROME_DIAG_METHOD),
      syndromeNature: labelMap(dicts, DICT.SYNDROME_NATURE),
    }),
    [dicts],
  )

  const methodOptions = dicts[DICT.SYNDROME_DIAG_METHOD] || []
  const natureOptions = dicts[DICT.SYNDROME_NATURE] || []
  const deptOptions = dicts[DICT.VISIT_DEPT] || []

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
      await downloadReport(REPORT.syndromeDist, format, params)
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  if (!canQuery) {
    return (
      <div className="card">
        <div className="card-title">
          <h3>证型分布统计</h3>
        </div>
        <div className="text-secondary">
          当前账号无「证型分布统计」查询权限（{PERM}），请联系系统管理员。
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <h3>证型分布统计</h3>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">就诊日期从</label>
            <div className="field-control">
              <input
                type="date"
                value={query.visitDateFrom}
                onChange={(e) => setQuery({ ...query, visitDateFrom: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">就诊日期到</label>
            <div className="field-control">
              <input
                type="date"
                value={query.visitDateTo}
                onChange={(e) => setQuery({ ...query, visitDateTo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">辨证体系</label>
            <div className="field-control">
              <select
                value={query.diagnosisMethod}
                onChange={(e) => setQuery({ ...query, diagnosisMethod: e.target.value })}
              >
                <option value="">全部</option>
                {methodOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">证型性质</label>
            <div className="field-control">
              <select
                value={query.syndromeNature}
                onChange={(e) => setQuery({ ...query, syndromeNature: e.target.value })}
              >
                <option value="">全部</option>
                {natureOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">证型</label>
            <PopupSelect
              elementId="pslQrySyndromeId"
              title="选择证型"
              columnLabel="证型"
              display={query.syndromeLabel}
              loader={(kw) =>
                syndromeApi.list({ page: 1, size: 50, syndrome_name: kw || undefined }).then((res) =>
                  (res.list || []).map((s) => ({
                    value: String(s.id),
                    label: `${s.syndrome_code} ${s.syndrome_name}`,
                    sub: s.diagnosis_method || undefined,
                  })),
                )
              }
              onSelect={(opt) =>
                setQuery({
                  ...query,
                  syndromeId: opt ? opt.value : '',
                  syndromeLabel: opt ? opt.label : '',
                })
              }
            />
          </div>
          <div className="form-item">
            <label className="field-label">汇总维度</label>
            <div className="field-control">
              {/* MU cboSummaryDimension：M7 RPT-SYNDROME-DIST-001 分组口径固定为「按证型」，
                  模型未定义汇总维度参数，故仅提供该口径一项，不下发额外参数 */}
              <select defaultValue="BY_SYNDROME">
                <option value="BY_SYNDROME">按证型</option>
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
          口径提示：占比分子分母使用相同筛选条件（Q-02 / REP-02）
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
