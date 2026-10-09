import { getToken, http, type PageResult } from './request'

export interface Herb {
  id: number
  herb_code: string
  herb_name: string
  alias_name: string | null
  herb_category: string | null
  nature_meridian: string | null
  efficacy: string | null
  min_common_dose: number | string
  max_common_dose: number | string
  toxicity_level: string
  special_managed: number | boolean
  stock_quantity: number | string
  low_stock_threshold: number | string | null
  origin: string | null
  spec: string | null
  herb_status: string
  stock_flows?: HerbStockFlow[]
  created_at?: string
  updated_at?: string
}

export interface HerbStockFlow {
  id?: number
  flow_no?: string
  herb_id?: number
  biz_type: string
  quantity: number | string
  biz_date: string
  operator_id?: string | number | null
  prescription_id?: number | null
  inbound_no?: string | null
  remark?: string | null
  /** 列表/详情返回的操作人显示名 */
  operator_name?: string | null
}

/** 建档/修改入参：`herb_code`、`stock_quantity` 免填（后者由流水驱动） */
export interface HerbPayload {
  herb_name: string
  alias_name?: string | null
  herb_category?: string | null
  nature_meridian?: string | null
  efficacy?: string | null
  min_common_dose: number | null
  max_common_dose: number | null
  toxicity_level: string
  special_managed: number
  low_stock_threshold?: number | null
  origin?: string | null
  spec?: string | null
  herb_status: string
}

export interface HerbQuery {
  page?: number
  size?: number
  herb_name?: string
  herb_category?: string
  herb_status?: string
}

export interface HerbStockQuery {
  page?: number
  size?: number
  herb_name?: string
  herb_category?: string
  toxicity_level?: string
  alert_only?: number | boolean
  stock_from?: number | string
  stock_to?: number | string
}

/** QR-HERB-STOCK-001 结果行（兼容后端 snake_case 与对象属性两种命名） */
export interface HerbStockRow {
  id?: number
  herb_code?: string
  herb_name?: string
  alias_name?: string
  herb_category?: string
  toxicity_level?: string
  stock_quantity?: number | string
  low_stock_threshold?: number | string | null
  alert_status?: string
  alertStatus?: string
  alert_gap?: number | string
  alertGap?: number | string
  latest_inbound_date?: string | null
  latestInboundDate?: string | null
  [key: string]: any
}

export interface HerbStocktakePayload {
  actual_quantity: number
  biz_date: string
  remark?: string | null
}

export interface HerbInboundPayload {
  quantity: number
  biz_date: string
  inbound_no?: string | null
  remark?: string | null
}

export interface HerbOption {
  id: number
  herb_code: string
  herb_name: string
}

function buildQuery(params?: Record<string, any>): string {
  if (!params) return ''
  return Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
}

/** 导出 CSV（UTF-8 BOM，由后端返回），走原生 fetch 以免 JSON 解析 */
async function downloadCsv(path: string, params?: Record<string, any>): Promise<void> {
  const qs = buildQuery(params)
  const token = getToken()
  const res = await fetch(`/api${path}${qs ? `?${qs}` : ''}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (!res.ok) throw new Error('导出失败')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `饮片库存与预警_${Date.now()}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const herbApi = {
  list(params: HerbQuery) {
    return http.get<PageResult<Herb>>('/herb', params)
  },
  /** 返回主表 + stock_flows[] */
  get(id: number) {
    return http.get<Herb>(`/herb/${id}`)
  },
  create(data: HerbPayload) {
    return http.post<Herb>('/herb', data)
  },
  update(id: number, data: HerbPayload) {
    return http.put<Herb>(`/herb/${id}`, data)
  },
  /** Herb_ChangeStatus：停用 / 启用 */
  changeStatus(id: number, herb_status: string) {
    return http.post<Herb>(`/herb/${id}/status`, { herb_status })
  },
  /** Herb_Inbound：入库登记（写「入库」正数流水 + 库存累加） */
  inbound(id: number, data: HerbInboundPayload) {
    return http.post<Herb>(`/herb/${id}/inbound`, data)
  },
  /** Herb_Stocktake：盘点调整（差异流水 + 库存同步为实盘值） */
  stocktake(id: number, data: HerbStocktakePayload) {
    return http.post<Herb>(`/herb/${id}/stocktake`, data)
  },
  /** Herb_QueryStockAndAlert：库存与预警分页查询 */
  stock(params: HerbStockQuery) {
    return http.get<PageResult<HerbStockRow>>('/herb/stock', params)
  },
  /** 导出同查询条件的 CSV */
  stockExport(params: HerbStockQuery) {
    return downloadCsv('/herb/stock/export', params)
  },
  /** 方剂模板「药味」跳选框数据源 */
  options(keyword?: string) {
    return http.get<HerbOption[]>('/herb/options', { keyword })
  },
}
