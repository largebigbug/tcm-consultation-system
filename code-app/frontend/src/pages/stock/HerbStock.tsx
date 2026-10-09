import { useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw, RotateCcw, Search, Warehouse } from 'lucide-react'
import { downloadReport, reportApi, type ReportColumn } from '../../api/report'
import { DICT, metaApi, type DictionaryMap } from '../../api/meta'
import { herbApi } from '../../api/herb'
import { http } from '../../api/request'
import ReportTable from '../../components/ReportTable'
import Modal from '../../components/Modal'
import { toast } from '../../components/toast'
import { useAuth } from '../../stores/userStore'

/**
 * 饮片库存与预警（含盘点）｜MU `frmHerbStock` / M7 `QR-HERB-STOCK-001`（批次 4：改报表引擎驱动）
 *
 * 取数口径（契约 §3.1）：
 *   - 列表：GET /api/report/QR-HERB-STOCK-001?<M7 参数>&page=&size=
 *     列集合 / 列序 / 合计一律取后端返回的 columns / summary（本页零手写 <th>）；
 *   - 导出：GET /api/report/QR-HERB-STOCK-001/export?format=xlsx|csv（复用 api/report.ts downloadReport），
 *     与查询使用**同一组**已应用条件；
 *   - 盘点：POST /api/herb/<id>/stocktake（写路径保留）；对账：GET /api/herb/<id>/reconcile（「载入已有记录」）。
 *   - 本屏**不再调用**批次 1 的 bespoke 库存接口（api/herb.ts 的 stock / stockExport，契约 §3.1）。
 *
 * 参数映射（契约 §3.2）：txtQryHerbName→herbName、cboQryHerbCategory→herbCategory、
 *   cboQryToxicityLevel→toxicityLevel、numQryStockFrom/To→stockQuantityFrom/To、
 *   cboQryAlertStatus 与 chkOnlyAlert **同源**映射 onlyAlert（任一为「仅预警」→ onlyAlert=true，否则不下发）。
 *   M7 参数 herbStatus / herbCode 在 MU 屏无控件 → 本屏不下发（契约 §5 缺口登记）。
 *
 * 展示口径：herbCategory / toxicityLevel 为字典列 → valueLabels 显示中文；
 *   alertStatus 后端已返回中文「预警 / 正常」→ 原样展示（绝不映射 ALERT/NORMAL）。
 */

/** 本报表码（api/report.ts 的 REPORT 常量只含批次 3 报表，公共件禁改 → 本屏内声明） */
const REPORT_CODE = 'QR-HERB-STOCK-001'
/** MU：actQuery / actExport → PERM-QUERY-HERB-STOCK */
const PERM_QUERY = 'herb:query-stock-and-alert'
/** MU：actStocktake → PERM-HERB-STOCKTAKE */
const PERM_STOCKTAKE = 'herb:stocktake'
/** 对账路由（api/herb.py）既有权限码；仅用于按钮可见性，未改后端 */
const PERM_RECONCILE = 'herb:save'

const PAGE_SIZES = [20, 50, 100]

const today = () => new Date().toISOString().slice(0, 10)

/** 字典 → { code: label }，供 ReportTable 的 valueLabels 渲染（字典列显示中文） */
const labelMap = (dicts: DictionaryMap, key: string): Record<string, string> =>
  (dicts[key] || []).reduce<Record<string, string>>((m, it) => {
    m[it.code] = it.label
    return m
  }, {})

interface QueryState {
  herbName: string
  herbCategory: string
  toxicityLevel: string
  /** MU cboQryAlertStatus：'' 全部 / 'ALERT' 仅预警项 */
  alertStatus: string
  stockQuantityFrom: string
  stockQuantityTo: string
  /** MU chkOnlyAlert：与 cboQryAlertStatus 同源 */
  onlyAlert: boolean
}

const emptyQuery = (): QueryState => ({
  herbName: '',
  herbCategory: '',
  toxicityLevel: '',
  alertStatus: '',
  stockQuantityFrom: '',
  stockQuantityTo: '',
  onlyAlert: false,
})

/** 两控件同源：任一为「仅预警」即 onlyAlert=true */
const onlyAlertOf = (q: QueryState): boolean => q.onlyAlert || q.alertStatus === 'ALERT'

interface StocktakeState {
  id: number
  herbName: string
  bookQty: number
  actual: string
  bizDate: string
  remark: string
  /** 「载入已有记录」（GET /api/herb/<id>/reconcile）回填的账实差异 */
  reconcile: { flowNetQuantity: number; difference: number; consistent: boolean } | null
}

export default function HerbStock() {
  const { user, hasPerm } = useAuth()
  const canQuery = hasPerm(PERM_QUERY)
  const canStocktake = hasPerm(PERM_STOCKTAKE)
  const canReconcile = hasPerm(PERM_RECONCILE)

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
  const [st, setSt] = useState<StocktakeState | null>(null)
  /** herbCode → id：M7 结果列不含 id，盘点需饮片主键（/api/herb/options 登录即可读） */
  const [herbIds, setHerbIds] = useState<Record<string, number>>({})

  /** 已应用条件 → M7 参数名；空值与 onlyAlert=false 一律不下发（约定 13 / skipWhenParameterEmpty） */
  const params = useMemo(() => {
    const only = onlyAlertOf(applied)
    return {
      herbName: applied.herbName.trim() || undefined,
      herbCategory: applied.herbCategory || undefined,
      toxicityLevel: applied.toxicityLevel || undefined,
      stockQuantityFrom: String(applied.stockQuantityFrom).trim() || undefined,
      stockQuantityTo: String(applied.stockQuantityTo).trim() || undefined,
      onlyAlert: only ? true : undefined,
      // herbStatus / herbCode：MU 屏无控件 → 不下发（契约 §5）
    }
  }, [applied])

  const load = async () => {
    if (!canQuery) return
    setLoading(true)
    try {
      const res = await reportApi.query(REPORT_CODE, { ...params, page, size })
      setColumns(res.columns || [])
      setRows(res.list || [])
      setTotal(res.total || 0)
      setSummary(res.summary ?? null)
    } catch (err: any) {
      // 契约 §3.4：接口中文 message 原样提示（含布尔取值非法、无权限），保留上次结果
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

  /** 盘点入口需要 id：预取饮片跳选框（herbCode → id） */
  useEffect(() => {
    if (!canStocktake) return
    herbApi
      .options()
      .then((list) => {
        const m: Record<string, number> = {}
        list.forEach((it) => {
          m[it.herb_code] = it.id
        })
        setHerbIds(m)
      })
      .catch(() => setHerbIds({}))
  }, [canStocktake])

  const valueLabels = useMemo(
    () => ({
      herbCategory: labelMap(dicts, DICT.HERB_HERB_CATEGORY),
      toxicityLevel: labelMap(dicts, DICT.HERB_TOXICITY_LEVEL),
    }),
    [dicts],
  )

  const categoryOptions = dicts[DICT.HERB_HERB_CATEGORY] || []
  const toxicityOptions = dicts[DICT.HERB_TOXICITY_LEVEL] || []
  const bizTypeOptions = dicts[DICT.STOCK_FLOW_FLOW_BIZ_TYPE] || []

  const onQuery = () => {
    setPage(1)
    setApplied({ ...query })
  }

  /** 重置：清空全部条件（onlyAlert 回默认 false）并回第 1 页 */
  const onReset = () => {
    const empty = emptyQuery()
    setQuery(empty)
    setApplied(empty)
    setPage(1)
  }

  const onExport = async () => {
    if (!canQuery) return
    try {
      await downloadReport(REPORT_CODE, format, params)
      toast('导出成功')
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const resolveHerbId = async (herbCode: any): Promise<number | null> => {
    const code = String(herbCode ?? '').trim()
    if (!code) return null
    if (herbIds[code]) return herbIds[code]
    try {
      const list = await herbApi.options(code)
      const hit = list.find((it) => it.herb_code === code)
      if (hit) {
        setHerbIds((m) => ({ ...m, [hit.herb_code]: hit.id }))
        return hit.id
      }
    } catch {
      /* 落到下方统一提示 */
    }
    return null
  }

  const openStocktake = async (row: Record<string, any>) => {
    const code = String(row?.herbCode ?? '')
    const id = await resolveHerbId(code)
    if (!id) {
      toast(`无法定位饮片「${code || '-'}」的库存标识，无法盘点`, 'error')
      return
    }
    setSt({
      id,
      herbName: String(row?.herbName ?? ''),
      bookQty: Number(row?.stockQuantity ?? 0),
      actual: '',
      bizDate: today(),
      remark: '',
      reconcile: null,
    })
  }

  /** 「载入已有记录」：GET /api/herb/<id>/reconcile（R-06 账实差异），回填账面库存 */
  const onLoadExisting = async () => {
    if (!st) return
    try {
      const r = await http.get<any>(`/herb/${st.id}/reconcile`)
      setSt((s) =>
        s
          ? {
              ...s,
              bookQty: Number(r?.stock_quantity ?? s.bookQty),
              reconcile: {
                flowNetQuantity: Number(r?.flow_net_quantity ?? 0),
                difference: Number(r?.difference ?? 0),
                consistent: !!r?.consistent,
              },
            }
          : s,
      )
      toast(
        `已载入已有记录：账面 ${Number(r?.stock_quantity ?? 0)} g，流水净和 ${Number(
          r?.flow_net_quantity ?? 0,
        )} g，差异 ${Number(r?.difference ?? 0)} g`,
      )
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const onSubmitStocktake = async () => {
    if (!st) return
    const actual = Number(st.actual)
    if (!String(st.actual).trim() || !Number.isFinite(actual)) {
      toast('实盘数量不能为空', 'error')
      return
    }
    if (!st.bizDate) {
      toast('业务日期不能为空', 'error')
      return
    }
    if (!st.remark.trim()) {
      toast('盘点/报损原因不能为空', 'error')
      return
    }
    try {
      await herbApi.stocktake(st.id, { actual_quantity: actual, biz_date: st.bizDate, remark: st.remark.trim() })
      toast('盘点成功')
      setSt(null)
      load()
    } catch (err: any) {
      toast(err.message, 'error')
    }
  }

  const adjustQty = st && String(st.actual).trim() ? Number(st.actual) - st.bookQty : 0
  const operator = user?.real_name || user?.username || ''
  const bizTypeLabel = bizTypeOptions.find((it) => it.code === 'STOCKTAKE_ADJUST')?.label || '盘点调整'
  const totalPages = Math.max(1, Math.ceil(total / size))

  if (!canQuery) {
    return (
      <div className="card">
        <div className="text-secondary">
          当前账号无「饮片库存与预警」查询权限（{PERM_QUERY}），请联系系统管理员。
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="card">
        <div className="form-grid-3">
          <div className="form-item">
            <label className="field-label">饮片名称</label>
            <div className="field-control">
              <input
                id="txtQryHerbName"
                value={query.herbName}
                onChange={(e) => setQuery({ ...query, herbName: e.target.value })}
                placeholder="模糊匹配"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">药材类别</label>
            <div className="field-control">
              <select
                id="cboQryHerbCategory"
                value={query.herbCategory}
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
            <label className="field-label">毒性分级</label>
            <div className="field-control">
              <select
                id="cboQryToxicityLevel"
                value={query.toxicityLevel}
                onChange={(e) => setQuery({ ...query, toxicityLevel: e.target.value })}
              >
                <option value="">全部</option>
                {toxicityOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-item">
            <label className="field-label">预警状态</label>
            <div className="field-control">
              <select
                id="cboQryAlertStatus"
                value={query.alertStatus}
                onChange={(e) => setQuery({ ...query, alertStatus: e.target.value })}
              >
                <option value="">全部</option>
                <option value="ALERT">仅预警项</option>
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">库存数量(g)</label>
            <div className="field-control" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                id="numQryStockFrom"
                type="number"
                min={0}
                step="0.1"
                value={query.stockQuantityFrom}
                onChange={(e) => setQuery({ ...query, stockQuantityFrom: e.target.value })}
                placeholder="下限"
              />
              <span className="text-secondary">~</span>
              <input
                id="numQryStockTo"
                type="number"
                min={0}
                step="0.1"
                value={query.stockQuantityTo}
                onChange={(e) => setQuery({ ...query, stockQuantityTo: e.target.value })}
                placeholder="上限"
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label">仅看预警项</label>
            <div className="field-control">
              <input
                id="chkOnlyAlert"
                type="checkbox"
                style={{ width: 'auto' }}
                checked={query.onlyAlert}
                onChange={(e) => setQuery({ ...query, onlyAlert: e.target.checked })}
              />
            </div>
          </div>
        </div>
        <div className="toolbar-right">
          <button id="btnReset" className="btn btn-secondary" onClick={onReset}>
            <RotateCcw size={14} /> 重置
          </button>
          <select
            id="cboExportFormat"
            style={{ width: 110 }}
            value={format}
            onChange={(e) => setFormat(e.target.value as 'xlsx' | 'csv')}
          >
            <option value="xlsx">XLSX</option>
            <option value="csv">CSV</option>
          </select>
          <button id="btnExport" className="btn btn-secondary" onClick={onExport}>
            <Download size={14} /> 导出
          </button>
          <button id="btnQuery" className="btn btn-primary" onClick={onQuery}>
            <Search size={14} /> 查询
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {/* 列 / 列序 / 合计全部来自后端 columns / summary，页面不手写列 */}
        <div id="grdResult">
          <ReportTable
            columns={columns}
            rows={rows}
            loading={loading}
            summary={summary}
            valueLabels={valueLabels}
            emptyText="暂无数据"
            rowActions={
              canStocktake
                ? (row) => (
                    <button className="btn btn-secondary btn-sm" onClick={() => openStocktake(row)}>
                      <Warehouse size={14} /> 盘点
                    </button>
                  )
                : undefined
            }
          />
        </div>
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
          <span className="text-secondary" id="lblPaging">
            共 {total} 条 / {totalPages} 页
          </span>
          <button
            id="btnPrev"
            className="btn btn-secondary"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </button>
          <button
            id="btnNext"
            className="btn btn-secondary"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          >
            下一页
          </button>
        </div>
      </div>

      <Modal
        title="库存盘点 / 报损"
        open={!!st}
        onClose={() => setSt(null)}
        width={620}
        footer={
          <>
            <button id="btnStocktakeCancel" className="btn btn-secondary" onClick={() => setSt(null)}>
              取消
            </button>
            <button id="btnStocktake" className="btn btn-primary" onClick={onSubmitStocktake}>
              盘点
            </button>
          </>
        }
      >
        <div className="form-grid-2">
          <div className="form-item">
            <label className="field-label">饮片</label>
            <div className="field-control">
              <input id="txtStocktakeHerbName" value={st?.herbName || ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">账面库存(g)</label>
            <div className="field-control">
              <input id="numStocktakeBookQty" value={st?.bookQty ?? ''} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">实盘数量(g)</label>
            <div className="field-control">
              <input
                id="numStocktakeQty"
                type="number"
                min={0}
                step="0.1"
                value={st?.actual ?? ''}
                onChange={(e) => setSt((s) => (s ? { ...s, actual: e.target.value } : s))}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">调整数量(g)</label>
            <div className="field-control">
              <input id="numAdjustQuantity" value={adjustQty} disabled />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">业务类型</label>
            <div className="field-control">
              <select id="cboFlowBizType" value="STOCKTAKE_ADJUST" disabled>
                {bizTypeOptions.length === 0 && <option value="STOCKTAKE_ADJUST">{bizTypeLabel}</option>}
                {bizTypeOptions.map((it) => (
                  <option key={it.code} value={it.code}>
                    {it.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">业务日期</label>
            <div className="field-control">
              <input
                id="dtpBizDate"
                type="date"
                value={st?.bizDate ?? ''}
                onChange={(e) => setSt((s) => (s ? { ...s, bizDate: e.target.value } : s))}
              />
            </div>
          </div>
          <div className="form-item">
            <label className="field-label required">操作人</label>
            <div className="field-control">
              <input id="txtOperatorId" value={operator} disabled />
            </div>
          </div>
          <div className="form-item span-2">
            <label className="field-label required">盘点/报损原因</label>
            <div className="field-control">
              <textarea
                id="txaStocktakeRemark"
                rows={3}
                value={st?.remark ?? ''}
                onChange={(e) => setSt((s) => (s ? { ...s, remark: e.target.value } : s))}
              />
            </div>
          </div>
          {canReconcile && (
            <div className="form-item span-2">
              <div className="field-control" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <button id="btnLoadExistingRecord" className="btn btn-secondary" onClick={onLoadExisting}>
                  <RefreshCw size={14} /> 载入已有记录
                </button>
                <span className="text-secondary">
                  {st?.reconcile
                    ? `流水净和 ${st.reconcile.flowNetQuantity} g，账实差异 ${st.reconcile.difference} g（${
                        st.reconcile.consistent ? '账实一致' : '账实不一致'
                      }）`
                    : '按 R-06 载入账面 / 流水净和 / 账实差异'}
                </span>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
