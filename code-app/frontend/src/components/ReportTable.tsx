import type { ReactNode } from 'react'
import type { ReportColumn } from '../api/report'

/**
 * 报表表格（批次 3 公共组件，6 张报表屏 + 随访登记列表共用）。
 *
 * 设计口径（冻结，勿各屏自造）：
 * - 表头与列序一律来自后端返回的 `columns`（M7 resultColumns 顺序），页面不得手写列；
 * - 单元格取值按列 `format` 渲染（#,##0 / #,##0.00 / 0.00% / yyyy-MM-dd / yyyy-MM-dd HH:mm）；
 * - 空值统一显示 `emptyDisplay`（来自 M7 reportOptions.emptyValueDisplay，默认 '-'）；
 * - 字典列（科室/就诊类型/状态/毒性分级/疗效评价…）由页面传 `valueLabels` 做 code → label 渲染；
 * - 合计行取后端 `summary`（键＝列名），仅在 `summary` 非空时渲染。
 */
export interface ReportTableProps {
  columns: ReportColumn[]
  rows: Record<string, any>[]
  loading?: boolean
  /** 合计行（M7 reportOptions.totalFields 求和；键＝列名） */
  summary?: Record<string, any> | null
  /** 空值显示，默认 '-' */
  emptyDisplay?: string
  /** 字典映射：列名 → { 字典 code: 显示文本 } */
  valueLabels?: Record<string, Record<string, string>>
  /** 主键字段名，默认 'id' */
  rowKey?: string
  /** 主从结构下行的点击选中（用于刷新从表） */
  onRowClick?: (row: Record<string, any>) => void
  selectedKey?: string | number | null
  /** 行操作列（如「作废」「编辑」「标记失访」）；不传则不渲染操作列 */
  rowActions?: (row: Record<string, any>) => ReactNode
  /** 需要隐藏的列名（如 M7 中 visible=false 或维度不适用的列） */
  hiddenColumns?: string[]
  /** 无数据提示，默认「暂无数据」 */
  emptyText?: string
}

/** 按 M7 列的 format 渲染单元格文本 */
export function renderCell(value: any, format?: string | null, emptyDisplay = '-'): string {
  if (value === null || value === undefined || value === '') return emptyDisplay
  if (typeof value === 'boolean') return value ? '是' : '否'
  const fmt = (format || '').trim()
  if (fmt === '#,##0') {
    const n = Number(value)
    return Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : String(value)
  }
  if (fmt === '#,##0.00') {
    const n = Number(value)
    return Number.isFinite(n)
      ? n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : String(value)
  }
  if (fmt === '0.00%' || fmt === '0.0%' || fmt === '0%') {
    const n = Number(value)
    if (!Number.isFinite(n)) return String(value)
    const digits = fmt === '0%' ? 0 : fmt === '0.0%' ? 1 : 2
    return `${(n * 100).toFixed(digits)}%`
  }
  if (fmt === 'yyyy-MM-dd') return String(value).slice(0, 10)
  if (fmt === 'yyyy-MM-dd HH:mm') return String(value).slice(0, 16)
  if (fmt === 'yyyy-MM') return String(value).slice(0, 7)
  return String(value)
}

export default function ReportTable({
  columns,
  rows,
  loading = false,
  summary = null,
  emptyDisplay = '-',
  valueLabels = {},
  rowKey = 'id',
  onRowClick,
  selectedKey = null,
  rowActions,
  hiddenColumns = [],
  emptyText = '暂无数据',
}: ReportTableProps) {
  const cols = columns.filter((c) => c.visible !== false && !hiddenColumns.includes(c.name))
  const showSummary = summary && cols.some((c) => summary[c.name] !== undefined && summary[c.name] !== null)

  const cell = (row: Record<string, any>, col: ReportColumn): ReactNode => {
    const map = valueLabels[col.name]
    const raw = row[col.name]
    if (map && raw !== null && raw !== undefined && raw !== '') {
      return map[String(raw)] ?? String(raw)
    }
    return renderCell(raw, col.format, emptyDisplay)
  }

  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.name}>{c.label}</th>
            ))}
            {rowActions ? <th>操作</th> : null}
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr>
              <td colSpan={cols.length + (rowActions ? 1 : 0)} style={{ textAlign: 'center', color: '#94a3b8' }}>
                加载中…
              </td>
            </tr>
          )}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={cols.length + (rowActions ? 1 : 0)} style={{ textAlign: 'center', color: '#94a3b8' }}>
                {emptyText}
              </td>
            </tr>
          )}
          {!loading &&
            rows.map((row, idx) => {
              const key = String(row[rowKey] ?? idx)
              const selected = selectedKey !== null && String(selectedKey) === key
              return (
                <tr
                  key={key}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  style={selected ? { background: '#eff6ff' } : onRowClick ? { cursor: 'pointer' } : undefined}
                >
                  {cols.map((c) => (
                    <td key={c.name}>{cell(row, c)}</td>
                  ))}
                  {rowActions ? <td onClick={(e) => e.stopPropagation()}>{rowActions(row)}</td> : null}
                </tr>
              )
            })}
        </tbody>
        {showSummary && (
          <tfoot>
            <tr style={{ fontWeight: 600, background: '#f9fafb' }}>
              <td>合计</td>
              {cols.slice(1).map((c) => (
                <td key={c.name}>{renderCell(summary![c.name], c.format, emptyDisplay)}</td>
              ))}
              {rowActions ? <td /> : null}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
