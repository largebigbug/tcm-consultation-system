import { useEffect, useMemo, useState } from 'react'
import { Download, RotateCcw, Search } from 'lucide-react'
import { REPORT, downloadReport, reportApi, type ReportColumn } from '../../api/report'
import { DICT, metaApi, type DictionaryMap } from '../../api/meta'
import ReportTable from '../../components/ReportTable'
import Pagination from '../../components/Pagination'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const PAGE_SIZES = [20, 50, 100]

/** MU frmOverdoseLedger（QUERY_LIST）：actQuery / actExport → Prescription_QueryOverdoseReview */
const PERM = 'prescription:query-overdose-review'

/** 字典 → { code: label }，供 ReportTable 的 valueLabels 渲染 */
const labelMap = (dicts: DictionaryMap, key: string): Record<string, string> =>
  (dicts[key] || []).reduce<Record<string, string>>((m, it) => {
    m[it.code] = it.label
    return m
  }, {})

/**
 * MU cboQryTriggerType 触发类型：M7 参数默认 BOTH，
 * OVERDOSE＝单剂剂量超常用量上限、TOXIC＝饮片毒性分级为有毒/剧毒。
 */
const TRIGGER_TYPES = [
  { value: 'BOTH', label: '全部' },
  { value: 'OVERDOSE', label: '超量' },
  { value: 'TOXIC', label: '毒性' },
]

interface QueryState {
  prescribeDateFrom: string
  prescribeDateTo: string
  triggerType: string
  prescriptionStatus: string
  reviewerId: string
  reviewResult: string
}

/** 初值＝M7 参数默认值（triggerType=BOTH） */
const emptyQuery = (): QueryState => ({
  prescribeDateFrom: '',
  prescribeDateTo: '',
  triggerType: 'BOTH',
  prescriptionStatus: '',
  reviewerId: '',
  reviewResult: '',
})

export default function OverdoseLedger() {
  const { hasPerm } = useAuth()
  const canQuery = hasPerm(PERM)

  const [dicts, setDicts] = useState<DictionaryMap>({})
  const [query, setQuery] = useState<QueryState>(emptyQuery)
  const [applied, setApplied] = useState<QueryState>(emptyQuery)
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
      prescribeDateFrom: applied.prescribeDateFrom || undefined,
      prescribeDateTo: applied.prescribeDateTo || undefined,
      triggerType: applied.triggerType || undefined,
      prescriptionStatus: applied.prescriptionStatus || undefined,
      reviewerId: applied.reviewerId || undefined,
      reviewResult: applied.reviewResult || undefined,
    }),
    [applied],
  )

  const load = async () => {
    if (!canQuery) return
    setLoading(true)
    try {
      const res = await reportApi.query(REPORT.overdoseLedger, { ...params, page, size })
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
      toxicityLevel: labelMap(dicts, DICT.HERB_TOXICITY_LEVEL),
      prescriptionStatus: labelMap(dicts, DICT.PRESCRIPTION_STATUS),
    }),
    [dicts],
  )

  const statusOptions = dicts[DICT.PRESCRIPTION_STATUS] || []

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  /** 重置：清空全部条件（触发类型回落 M7 默认 BOTH）并回到第 1 页 */
  const onReset = () => {
    const empty = emptyQuery()
    setQuery(empty)
    setApplied(empty)
    setPage(1)
  }

  const onExport = async () => {
    if (!canQuery) return
    try {
      await downloadReport(REPORT.overdoseLedger, format, params)
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  if (!canQuery) {
    return (
      <div className="card">
        <div className="card-title">
          <h3>超量·毒性处方审核台账</h3>
        </div>
        <div className="text-secondary">
          当前账号无「超量·毒性处方审核台账」查询权限（{PERM}），请联系系统管理员。
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <h3>超量·毒性处方审核台账</h3>
        </div>
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">开方日期从</label>
            <div className="field-control">
              <input
                type="date"
                value={query.prescribeDateFrom}
                onChange={(e) => setQuery({ ...query, prescribeDateFrom: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">开方日期到</label>
            <div className="field-control">
              <input
                type="date"
                value={query.prescribeDateTo}
                onChange={(e) => setQuery({ ...query, prescribeDateTo: e.target.value })}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">触发类型</label>
            <div className="field-control">
              <select
                value={query.triggerType}
                onChange={(e) => setQuery({ ...query, triggerType: e.target.value })}
              >
                {TRIGGER_TYPES.map((it) => (
                  <option key={it.value} value={it.value}>
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
                value={query.prescriptionStatus}
                onChange={(e) => setQuery({ ...query, prescriptionStatus: e.target.value })}
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
          <div className="form-item">
            <label className="field-label">审核药师</label>
            <div className="field-control">
              <input
                value={query.reviewerId}
                onChange={(e) => setQuery({ ...query, reviewerId: e.target.value })}
                placeholder="药师工号"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">处理结果</label>
            <div className="field-control">
              {/* M7：reviewResult 与 prescription.prescriptionStatus 同取值域（条件 C07） */}
              <select
                value={query.reviewResult}
                onChange={(e) => setQuery({ ...query, reviewResult: e.target.value })}
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
          口径提示：超量＝单剂剂量＞常用量上限、毒性＝饮片毒性分级为有毒/剧毒；仅列示含明细且命中触发条件的处方（REP-06）
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
