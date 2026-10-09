import { http } from './request'
import { getToken } from './request'

/** M7 结果列（columns[] 由后端按 M7 resultColumns 顺序返回） */
export interface ReportColumn {
  name: string
  label: string
  dataType?: string | null
  format?: string | null
  sortable?: boolean
  visible?: boolean
}

/** 统一报表查询响应（后端 /api/report/{reportCode}） */
export interface ReportResult {
  columns: ReportColumn[]
  list: Record<string, any>[]
  total: number
  page: number
  size: number
  /** 合计行（仅需求要求「底部合计」的报表返回，键＝列名） */
  summary?: Record<string, any> | null
  /** 报表元信息（id/name/alias/objectType，便于页面标题与导出文件名） */
  report?: { id: string; name: string; alias?: string | null; objectType?: string | null } | null
}

/** 批次 3 报表编码（M7 query_reports.id） */
export const REPORT = {
  visitStats: 'RPT-VISIT-STATS-001',
  syndromeDist: 'RPT-SYNDROME-DIST-001',
  herbUsage: 'RPT-HERB-USAGE-001',
  visitPrescription: 'QR-VISIT-PRESCRIPTION-001',
  overdoseLedger: 'QR-PRESCRIPTION-OVERDOSE-001',
  followupCompletion: 'RPT-FOLLOWUP-COMPLETION-001',
} as const

export const reportApi = {
  /** 分页查询（params 直接透传 M7 参数名，空值由 http.get 自动丢弃） */
  query<T = ReportResult>(reportCode: string, params?: Record<string, any>) {
    return http.get<T>(`/report/${reportCode}`, params)
  },
}

function buildQuery(params?: Record<string, any>): string {
  if (!params) return ''
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
  return qs ? `?${qs}` : ''
}

/**
 * 下载报表导出文件（需求 D-29：XLSX + CSV，不做 PDF）。
 * 认证走 Authorization 头，故不能用 <a href> 直链，必须 fetch + blob。
 */
export async function downloadReport(
  reportCode: string,
  format: 'xlsx' | 'csv',
  params?: Record<string, any>,
): Promise<void> {
  const qs = buildQuery({ ...params, format })
  const res = await fetch(`/api/report/${reportCode}/export${qs}`, {
    headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
  })
  if (!res.ok) {
    // 后端失败时返回 JSON（统一响应），把中文提示抛给页面 toast
    let message = `导出失败（HTTP ${res.status}）`
    try {
      const body = await res.json()
      if (body?.message) message = body.message
    } catch {
      /* 非 JSON 响应，保留默认提示 */
    }
    throw new Error(message)
  }
  const blob = await res.blob()
  const disp = res.headers.get('Content-Disposition') || ''
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disp)
  const filename = m ? decodeURIComponent(m[1]) : `${reportCode}.${format}`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
