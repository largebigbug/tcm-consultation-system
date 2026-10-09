import { useEffect, useMemo, useState } from 'react'
import { Download, RotateCcw, Search } from 'lucide-react'
import { REPORT, downloadReport, reportApi, type ReportColumn } from '../../api/report'
import { DICT, metaApi, type DictionaryMap } from '../../api/meta'
import { herbApi } from '../../api/herb'
import { formulaApi } from '../../api/formula'
import ReportTable from '../../components/ReportTable'
import Pagination from '../../components/Pagination'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

const PAGE_SIZES = [20, 50, 100]

/** MU frmHerbUsageStats（QUERY_LIST）：actQuery / actExport → Prescription_QueryHerbUsage */
const PERM = 'prescription:query-herb-usage'

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

/** MU cboStatDimension 统计维度：M7 参数 statsDimension，默认 HERB */
const STATS_DIMENSIONS = [
  { value: 'HERB', label: '按饮片' },
  { value: 'FORMULA_TEMPLATE', label: '按方剂模板' },
]

/** 维度不适用的列（列集合仍来自后端 columns，仅隐藏明显不适用的列） */
const HERB_ONLY_COLUMNS = ['herbCode', 'herbName', 'herbCategory', 'toxicityLevel']
const FORMULA_ONLY_COLUMNS = ['formulaCode', 'formulaName', 'formulaType', 'formulaRefCount', 'formulaRefRatio']

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
  prescribeDateFrom: string
  prescribeDateTo: string
  statsDimension: string
  herbCategory: string
  /** M7 参数 herbId 比对 herb.herbCode，故取饮片编码 */
  herbId: string
  herbLabel: string
  /** M7 参数 formulaTemplateId 比对 formula.formulaCode，故取方剂编码 */
  formulaTemplateId: string
  formulaLabel: string
  prescriptionType: string
}

/** 初值＝M7 参数默认值（prescribeDateFrom=MONTH_START、prescribeDateTo=MONTH_END、statsDimension=HERB） */
const defaultQuery = (): QueryState => ({
  prescribeDateFrom: monthStart(),
  prescribeDateTo: monthEnd(),
  statsDimension: 'HERB',
  herbCategory: '',
  herbId: '',
  herbLabel: '',
  formulaTemplateId: '',
  formulaLabel: '',
  prescriptionType: '',
})

const emptyQuery = (): QueryState => ({
  prescribeDateFrom: '',
  prescribeDateTo: '',
  statsDimension: '',
  herbCategory: '',
  herbId: '',
  herbLabel: '',
  formulaTemplateId: '',
  formulaLabel: '',
  prescriptionType: '',
})

export default function HerbUsage() {
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
      prescribeDateFrom: applied.prescribeDateFrom || undefined,
      prescribeDateTo: applied.prescribeDateTo || undefined,
      statsDimension: applied.statsDimension || undefined,
      herbCategory: applied.herbCategory || undefined,
      herbId: applied.herbId || undefined,
      formulaTemplateId: applied.formulaTemplateId || undefined,
      prescriptionType: applied.prescriptionType || undefined,
    }),
    [applied],
  )

  const load = async () => {
    if (!canQuery) return
    setLoading(true)
    try {
      const res = await reportApi.query(REPORT.herbUsage, { ...params, page, size })
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
      herbCategory: labelMap(dicts, DICT.HERB_HERB_CATEGORY),
      toxicityLevel: labelMap(dicts, DICT.HERB_TOXICITY_LEVEL),
      formulaType: labelMap(dicts, DICT.FORMULA_FORMULA_TYPE),
    }),
    [dicts],
  )

  const categoryOptions = dicts[DICT.HERB_HERB_CATEGORY] || []
  const prescriptionTypeOptions = dicts[DICT.PRESCRIPTION_TYPE] || []

  /** 已应用维度：切换后隐藏另一维度的列（列集合仍取后端 columns） */
  const hiddenColumns = applied.statsDimension === 'FORMULA_TEMPLATE' ? HERB_ONLY_COLUMNS : FORMULA_ONLY_COLUMNS
  const byFormula = query.statsDimension === 'FORMULA_TEMPLATE'

  const onDimensionChange = (dimension: string) => {
    if (dimension === 'FORMULA_TEMPLATE') {
      setQuery({ ...query, statsDimension: dimension, herbCategory: '', herbId: '', herbLabel: '' })
    } else {
      setQuery({ ...query, statsDimension: dimension, formulaTemplateId: '', formulaLabel: '' })
    }
  }

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  /** 重置：清空全部条件（统计维度回落 M7 默认 HERB）并回到第 1 页 */
  const onReset = () => {
    const empty = emptyQuery()
    setQuery({ ...empty, statsDimension: 'HERB' })
    setApplied({ ...empty, statsDimension: 'HERB' })
    setPage(1)
  }

  const onExport = async () => {
    if (!canQuery) return
    try {
      await downloadReport(REPORT.herbUsage, format, params)
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  if (!canQuery) {
    return (
      <div className="card">
        <div className="card-title">
          <h3>方剂与饮片使用统计</h3>
        </div>
        <div className="text-secondary">
          当前账号无「方剂与饮片使用统计」查询权限（{PERM}），请联系系统管理员。
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <h3>方剂与饮片使用统计</h3>
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
            <label className="field-label">统计维度</label>
            <div className="field-control">
              <select value={query.statsDimension} onChange={(e) => onDimensionChange(e.target.value)}>
                <option value="">请选择</option>
                {STATS_DIMENSIONS.map((it) => (
                  <option key={it.value} value={it.value}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">饮片类别</label>
            <div className="field-control">
              <select
                value={query.herbCategory}
                disabled={byFormula}
                onChange={(e) => setQuery({ ...query, herbCategory: e.target.value })}
              >
                <option value="">全部</option>
                {categoryOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">饮片</label>
            <PopupSelect
              elementId="pslQryHerbId"
              title="选择饮片"
              columnLabel="饮片"
              display={query.herbLabel}
              loader={(kw) =>
                herbApi.list({ page: 1, size: 50, herb_name: kw || undefined }).then((res) =>
                  (res.list || []).map((h) => ({
                    value: h.herb_code,
                    label: `${h.herb_code} ${h.herb_name}`,
                    sub: h.alias_name || undefined,
                  })),
                )
              }
              onSelect={(opt) =>
                setQuery({ ...query, herbId: opt ? opt.value : '', herbLabel: opt ? opt.label : '' })
              }
            />
          </div>
          <div className="form-item">
            <label className="field-label">方剂模板</label>
            <PopupSelect
              elementId="pslQryFormulaTemplateId"
              title="选择方剂模板"
              columnLabel="方剂模板"
              display={query.formulaLabel}
              loader={(kw) =>
                formulaApi.list({ page: 1, size: 50, formula_name: kw || undefined }).then((res) =>
                  (res.list || []).map((f) => ({
                    value: f.formula_code,
                    label: `${f.formula_code} ${f.formula_name}`,
                    sub: f.formula_type || undefined,
                  })),
                )
              }
              onSelect={(opt) =>
                setQuery({
                  ...query,
                  formulaTemplateId: opt ? opt.value : '',
                  formulaLabel: opt ? opt.label : '',
                })
              }
            />
          </div>
          <div className="form-item">
            <label className="field-label">处方类型</label>
            <div className="field-control">
              <select
                value={query.prescriptionType}
                onChange={(e) => setQuery({ ...query, prescriptionType: e.target.value })}
              >
                <option value="">全部</option>
                {prescriptionTypeOptions.map((it) => (
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
          口径提示：按饮片与按方剂模板两个维度分别查询，避免重复统计（Q-03 / REP-03）；当前维度不适用的列显示「-」
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <ReportTable
          columns={columns}
          rows={rows}
          loading={loading}
          summary={summary}
          valueLabels={valueLabels}
          hiddenColumns={hiddenColumns}
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
